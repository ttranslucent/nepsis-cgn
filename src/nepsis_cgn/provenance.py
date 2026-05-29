from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Literal, Protocol
from uuid import uuid4

LOGGER = logging.getLogger("nepsis_cgn.provenance")

PROVENANCE_RECORD_SCHEMA_ID = "nepsis.packet_provenance_record"
PROVENANCE_RECORD_SCHEMA_VERSION = "1.0.0"
AUDIT_EXPORT_SCHEMA_ID = "nepsis.audit_export"
AUDIT_EXPORT_SCHEMA_VERSION = "1.0.0"

RetentionMode = Literal["retained", "hash_only"]
AppendStatus = Literal["appended", "duplicate"]


class IntegrityConflict(ValueError):
    pass


class PacketSigner(Protocol):
    def sign(self, record: dict[str, Any]) -> dict[str, Any]:
        ...

    def verify(self, record: dict[str, Any]) -> bool:
        ...


class UnsignedPacketSigner:
    algorithm = "unsigned"
    key_id = None

    def sign(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "signature": None,
            "signed_at": None,
        }

    def verify(self, record: dict[str, Any]) -> bool:
        return verify_payload_hash(record)


class HmacSha256PacketSigner:
    algorithm = "hmac-sha256"

    def __init__(self, *, secret: str, key_id: str = "default") -> None:
        if not secret:
            raise ValueError("secret must be non-empty")
        self._secret = secret.encode("utf-8")
        self.key_id = key_id or "default"

    def sign(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "signature": hmac.new(self._secret, _signing_bytes(record), hashlib.sha256).hexdigest(),
            "signed_at": _now_iso8601(),
        }

    def verify(self, record: dict[str, Any]) -> bool:
        signature = record.get("signature")
        if not isinstance(signature, dict):
            return False
        if signature.get("algorithm") != self.algorithm or signature.get("key_id") != self.key_id:
            return False
        value = signature.get("signature")
        if not isinstance(value, str):
            return False
        expected = hmac.new(self._secret, _signing_bytes(record), hashlib.sha256).hexdigest()
        return verify_payload_hash(record) and hmac.compare_digest(value, expected)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def configured_packet_signer() -> PacketSigner:
    secret = os.getenv("NEPSIS_PACKET_SIGNING_SECRET", "").strip()
    if not secret:
        return UnsignedPacketSigner()
    key_id = os.getenv("NEPSIS_PACKET_SIGNING_KEY_ID", "default").strip() or "default"
    return HmacSha256PacketSigner(secret=secret, key_id=key_id)


def provenance_enabled() -> bool:
    return os.getenv("NEPSIS_PACKET_PROVENANCE_ENABLED", "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def default_provenance_path() -> Path:
    configured = os.getenv("NEPSIS_PACKET_PROVENANCE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.cwd() / "ledger" / "sessions" / "packet_provenance.jsonl"


def build_packet_record(
    *,
    packet: dict[str, Any],
    source: str,
    retention_mode: RetentionMode,
    request_id: str | None = None,
    method: str | None = None,
    path: str | None = None,
    sequence: int | None = None,
    direction: str = "response",
    session_id: str | None = None,
    owner_id: str | None = None,
    parent_packet_id: str | None = None,
    signer: PacketSigner | None = None,
) -> dict[str, Any]:
    if retention_mode not in {"retained", "hash_only"}:
        raise ValueError("retention_mode must be retained or hash_only")
    if not isinstance(packet, dict):
        raise ValueError("packet must be an object")

    digest = sha256_payload(packet)
    packet_id = _packet_id(packet, digest)
    resolved_session_id = session_id or _packet_session_id(packet)
    resolved_parent_packet_id = parent_packet_id if parent_packet_id is not None else _packet_parent_id(packet)
    packet_schema_id = _optional_string(packet.get("schema_id"))
    packet_schema_version = _optional_string(packet.get("schema_version"))

    record: dict[str, Any] = {
        "schema_id": PROVENANCE_RECORD_SCHEMA_ID,
        "schema_version": PROVENANCE_RECORD_SCHEMA_VERSION,
        "record_id": str(uuid4()),
        "created_at": _now_iso8601(),
        "source": str(source),
        "direction": str(direction or "response"),
        "packet_id": packet_id,
        "packet_schema_id": packet_schema_id,
        "packet_schema_version": packet_schema_version,
        "session_id": resolved_session_id,
        "parent_packet_id": resolved_parent_packet_id,
        "payload_hash": f"sha256:{digest}",
        "request": {
            "request_id": request_id,
            "method": method,
            "path": path,
            "sequence": sequence,
        },
        "retention": {
            "mode": retention_mode,
            "payload_retained": retention_mode == "retained",
        },
        "integrity": {
            "payload_hash_verified": True if retention_mode == "retained" else None,
            "signature_verified": None,
        },
    }
    if owner_id:
        record["request"]["owner_hash"] = f"sha256:{hashlib.sha256(owner_id.encode('utf-8')).hexdigest()}"
    if retention_mode == "retained":
        record["payload"] = _json_copy(packet)

    signer = signer or configured_packet_signer()
    record["signature"] = signer.sign(record)
    record["integrity"]["signature_verified"] = signer.verify(record)
    return record


def record_packet_observation(
    *,
    packet: dict[str, Any],
    source: str,
    retention_mode: RetentionMode,
    request_context: dict[str, Any] | None = None,
    session_id: str | None = None,
    owner_id: str | None = None,
    parent_packet_id: str | None = None,
    sequence: int | None = None,
) -> dict[str, Any] | None:
    if not provenance_enabled():
        return None
    context = request_context or {}
    record = build_packet_record(
        packet=packet,
        source=source,
        retention_mode=retention_mode,
        request_id=_optional_string(context.get("request_id")),
        method=_optional_string(context.get("method")),
        path=_optional_string(context.get("path")),
        sequence=sequence if sequence is not None else _optional_int(context.get("sequence")),
        session_id=session_id,
        owner_id=owner_id,
        parent_packet_id=parent_packet_id,
    )
    try:
        PacketProvenanceStore(default_provenance_path()).append(record)
    except IntegrityConflict:
        raise
    except Exception:
        LOGGER.exception("packet_provenance_record_failed source=%s packet_id=%s", source, record["packet_id"])
        return None
    return record


def verify_payload_hash(record: dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    retained = record.get("payload")
    if not isinstance(retained, dict):
        return record.get("retention", {}).get("mode") == "hash_only"
    expected = record.get("payload_hash")
    if not isinstance(expected, str) or not expected.startswith("sha256:"):
        return False
    return hmac.compare_digest(expected.removeprefix("sha256:"), sha256_payload(retained))


def verify_record_signature(record: dict[str, Any]) -> bool:
    signature = record.get("signature")
    if not isinstance(signature, dict):
        return False
    algorithm = signature.get("algorithm")
    if algorithm == "unsigned":
        return verify_payload_hash(record)
    if algorithm == "hmac-sha256":
        secret = os.getenv("NEPSIS_PACKET_SIGNING_SECRET", "").strip()
        key_id = str(signature.get("key_id") or "default")
        if not secret:
            return False
        return HmacSha256PacketSigner(secret=secret, key_id=key_id).verify(record)
    return False


class PacketProvenanceStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = RLock()

    def append(self, record: dict[str, Any]) -> AppendStatus:
        _validate_record(record)
        with self._lock:
            existing = self.records()
            for item in existing:
                if item.get("record_id") == record.get("record_id"):
                    if item == record:
                        return "duplicate"
                    raise IntegrityConflict(f"record_id conflict: {record.get('record_id')}")
                if item.get("packet_id") == record.get("packet_id") and item.get("payload_hash") != record.get("payload_hash"):
                    raise IntegrityConflict(f"packet_id hash conflict: {record.get('packet_id')}")

            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            return "appended"

    def records(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict):
                rows.append(item)
        return rows

    def records_for_session(self, session_id: str) -> list[dict[str, Any]]:
        return [record for record in self.records() if record.get("session_id") == session_id]

    def records_for_request(self, request_id: str) -> list[dict[str, Any]]:
        return _sort_records(
            [record for record in self.records() if record.get("request", {}).get("request_id") == request_id]
        )

    def graph_for_session(self, session_id: str) -> dict[str, Any]:
        return build_graph(self.records_for_session(session_id))

    def lineage_for_packet(self, packet_id: str) -> dict[str, Any]:
        records = self.records()
        related_ids = {packet_id}
        changed = True
        while changed:
            changed = False
            for record in records:
                current = record.get("packet_id")
                parent = record.get("parent_packet_id")
                if current in related_ids and parent and parent not in related_ids:
                    related_ids.add(parent)
                    changed = True
                if parent in related_ids and current and current not in related_ids:
                    related_ids.add(current)
                    changed = True
        return build_graph([record for record in records if record.get("packet_id") in related_ids])


def build_graph(records: list[dict[str, Any]]) -> dict[str, Any]:
    nodes_by_id: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str]] = set()
    for record in _sort_records(records):
        packet_id = _optional_string(record.get("packet_id"))
        if not packet_id:
            continue
        nodes_by_id.setdefault(
            packet_id,
            {
                "packet_id": packet_id,
                "packet_schema_id": record.get("packet_schema_id"),
                "session_id": record.get("session_id"),
                "source": record.get("source"),
                "payload_hash": record.get("payload_hash"),
                "signature": record.get("signature"),
                "retention": record.get("retention"),
                "created_at": record.get("created_at"),
                "request_id": record.get("request", {}).get("request_id"),
            },
        )
        parent_id = _optional_string(record.get("parent_packet_id"))
        if parent_id:
            edge = (parent_id, packet_id)
            if edge not in seen_edges:
                edges.append({"parent_packet_id": parent_id, "child_packet_id": packet_id})
                seen_edges.add(edge)
    return {"nodes": list(nodes_by_id.values()), "edges": edges}


def build_audit_export(
    *,
    session: dict[str, Any],
    packets: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    graph = build_graph(records)
    hash_failures = [
        record.get("record_id")
        for record in records
        if record.get("retention", {}).get("payload_retained") and not verify_payload_hash(record)
    ]
    signature_failures = [
        record.get("record_id")
        for record in records
        if record.get("signature", {}).get("algorithm") != "unsigned" and not verify_record_signature(record)
    ]
    hash_only_omissions = [
        record.get("record_id")
        for record in records
        if record.get("retention", {}).get("mode") == "hash_only"
    ]
    return {
        "schema_id": AUDIT_EXPORT_SCHEMA_ID,
        "schema_version": AUDIT_EXPORT_SCHEMA_VERSION,
        "created_at": _now_iso8601(),
        "session": _json_copy(session),
        "packets": _json_copy(packets) or [],
        "provenance": {
            "records": _json_copy(_sort_records(records)) or [],
            "graph": graph,
        },
        "verification": {
            "record_count": len(records),
            "hash_failures": [value for value in hash_failures if isinstance(value, str)],
            "signature_failures": [value for value in signature_failures if isinstance(value, str)],
            "hash_only_omissions": [value for value in hash_only_omissions if isinstance(value, str)],
        },
    }


def _validate_record(record: dict[str, Any]) -> None:
    if record.get("schema_id") != PROVENANCE_RECORD_SCHEMA_ID:
        raise ValueError("packet provenance record schema_id is invalid")
    if not isinstance(record.get("record_id"), str) or not record["record_id"]:
        raise ValueError("packet provenance record requires record_id")
    if not isinstance(record.get("packet_id"), str) or not record["packet_id"]:
        raise ValueError("packet provenance record requires packet_id")
    if not isinstance(record.get("payload_hash"), str) or not record["payload_hash"].startswith("sha256:"):
        raise ValueError("packet provenance record requires sha256 payload_hash")


def _signing_bytes(record: dict[str, Any]) -> bytes:
    payload = {
        key: value
        for key, value in record.items()
        if key not in {"signature", "integrity"}
    }
    return canonical_json_bytes(payload)


def _packet_id(packet: dict[str, Any], digest: str) -> str:
    meta = packet.get("meta")
    if isinstance(meta, dict):
        value = _optional_string(meta.get("packet_id"))
        if value:
            return value
    value = _optional_string(packet.get("packet_id"))
    if value:
        return value
    return f"hash:{digest[:32]}"


def _packet_session_id(packet: dict[str, Any]) -> str | None:
    meta = packet.get("meta")
    if isinstance(meta, dict):
        value = _optional_string(meta.get("session_id"))
        if value:
            return value
    return _optional_string(packet.get("session_id"))


def _packet_parent_id(packet: dict[str, Any]) -> str | None:
    meta = packet.get("meta")
    if isinstance(meta, dict):
        value = _optional_string(meta.get("parent_packet_id"))
        if value:
            return value
    value = _optional_string(packet.get("parent_packet_id"))
    if value:
        return value
    return _optional_string(packet.get("latest_iteration_packet_id"))


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sort_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(indexed: tuple[int, dict[str, Any]]) -> tuple[str, int, str, str]:
        index, item = indexed
        sequence = _optional_int(item.get("request", {}).get("sequence"))
        return (
            _optional_string(item.get("request", {}).get("request_id")) or "",
            sequence if sequence is not None else index,
            _optional_string(item.get("created_at")) or "",
            _optional_string(item.get("record_id")) or "",
        )

    return [item for _, item in sorted(enumerate(records), key=sort_key)]


def _json_copy(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, sort_keys=True))


def _now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


__all__ = [
    "AUDIT_EXPORT_SCHEMA_ID",
    "AUDIT_EXPORT_SCHEMA_VERSION",
    "HmacSha256PacketSigner",
    "IntegrityConflict",
    "PacketProvenanceStore",
    "UnsignedPacketSigner",
    "build_audit_export",
    "build_graph",
    "build_packet_record",
    "canonical_json_bytes",
    "default_provenance_path",
    "provenance_enabled",
    "record_packet_observation",
    "sha256_payload",
    "verify_payload_hash",
    "verify_record_signature",
]
