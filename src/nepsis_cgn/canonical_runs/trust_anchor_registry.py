from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from typing import Any, Iterator, Mapping, Sequence

from nepsis_cgn.contracts.canonical_json import (
    CanonicalJsonError,
    canonical_bytes,
    canonical_hash,
    canonical_json,
)
from nepsis_cgn.verification.receipts import (
    ActionReceiptError,
    validate_trust_anchor,
)


TRUST_ANCHOR_LIFECYCLE_EVENT_VERSION = (
    "nepsis.action_receipt_trust_anchor_lifecycle_event@0.1.0"
)
TRUST_ANCHOR_ACTIVATION_VERSION = (
    "nepsis.action_receipt_trust_anchor_activation@0.1.0"
)
TRUST_ANCHOR_REVOCATION_VERSION = (
    "nepsis.action_receipt_trust_anchor_revocation@0.1.0"
)
TRUST_ANCHOR_REGISTRY_EXPORT_VERSION = (
    "nepsis.action_receipt_trust_anchor_registry_export@0.1.0"
)
TRUST_ANCHOR_REGISTRY_ACTOR_ID = (
    "system:nepsis.receipt_trust_anchor_registry@0.1.0"
)
TRUST_ANCHOR_LIFECYCLE_GENESIS_HASH = hashlib.sha256(
    b"nepsis.action_receipt_trust_anchor_lifecycle.genesis@0.1.0"
).hexdigest()

_EVENT_FIELDS = {
    "actor_id",
    "created_at",
    "event_hash",
    "event_type",
    "idempotency_key",
    "payload",
    "payload_hash",
    "prev_event_hash",
    "provenance_class",
    "sequence",
    "trust_anchor_lifecycle_event_schema_version",
}
_ACTIVATION_FIELDS = {
    "activation_id",
    "action_receipt_trust_anchor_activation_schema_version",
    "trust_anchor",
    "trust_anchor_hash",
}
_REVOCATION_FIELDS = {
    "action_receipt_trust_anchor_revocation_schema_version",
    "key_id",
    "reason",
    "revocation_id",
    "revoked_at",
    "trust_anchor_hash",
}


class TrustAnchorRegistryError(RuntimeError):
    """The durable trust-anchor lifecycle cannot be used safely."""


class TrustAnchorRevokedError(TrustAnchorRegistryError):
    """The sole configured receipt anchor has been explicitly revoked."""


@dataclass(frozen=True)
class TrustAnchorRegistryResult:
    event: Mapping[str, Any]
    replayed: bool = False


class ReceiptTrustAnchorRegistry:
    """Append-only single-anchor lifecycle registry.

    Version 0.1 intentionally supports one activation and one optional
    revocation. A second activation is rotation, which is unsupported and
    therefore refused rather than inferred from key files or export history.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        path: Path | None = None,
        allow_initial_activation: bool,
    ) -> None:
        self._connection = connection
        self._path = path
        self._allow_initial_activation = allow_initial_activation
        self._lock = threading.RLock()
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA synchronous = FULL")
        if path is not None:
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    @classmethod
    def in_memory(cls) -> "ReceiptTrustAnchorRegistry":
        return cls(
            sqlite3.connect(
                ":memory:", isolation_level=None, check_same_thread=False
            ),
            allow_initial_activation=True,
        )

    @classmethod
    def initialize(cls, path: str | Path) -> "ReceiptTrustAnchorRegistry":
        """Create a new ledger explicitly; never reinterpret a missing restart."""

        resolved = _validated_ledger_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                resolved,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as exc:
            raise TrustAnchorRegistryError(
                "trust-anchor ledger already exists; open it as existing"
            ) from exc
        except OSError as exc:
            raise TrustAnchorRegistryError(
                "trust-anchor ledger could not be initialized"
            ) from exc
        else:
            os.close(descriptor)
        connection = sqlite3.connect(
            str(resolved), isolation_level=None, check_same_thread=False
        )
        return cls(
            connection,
            path=resolved,
            allow_initial_activation=True,
        )

    @classmethod
    def open_existing(cls, path: str | Path) -> "ReceiptTrustAnchorRegistry":
        """Open a previously activated ledger without any create semantics."""

        resolved = _validated_ledger_path(path)
        if not resolved.is_file():
            raise TrustAnchorRegistryError(
                "existing trust-anchor ledger is required; explicit initialization is separate"
            )
        try:
            connection = sqlite3.connect(
                resolved.as_uri() + "?mode=rw",
                uri=True,
                isolation_level=None,
                check_same_thread=False,
            )
        except sqlite3.Error as exc:
            raise TrustAnchorRegistryError(
                "existing trust-anchor ledger could not be opened"
            ) from exc
        required_objects = {
            ("table", "receipt_trust_anchor_events"),
            ("trigger", "receipt_trust_anchor_events_no_delete"),
            ("trigger", "receipt_trust_anchor_events_no_update"),
        }
        present = {
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                "SELECT type, name FROM sqlite_master WHERE type IN ('table', 'trigger')"
            ).fetchall()
        }
        if not required_objects <= present:
            connection.close()
            raise TrustAnchorRegistryError(
                "existing trust-anchor ledger was not explicitly initialized"
            )
        try:
            registry = cls(
                connection,
                path=resolved,
                allow_initial_activation=False,
            )
            if not registry._verified_events():
                raise TrustAnchorRegistryError(
                    "existing trust-anchor ledger has no activation record"
                )
            registry._verify_append_only_guards()
        except BaseException:
            connection.close()
            raise
        return registry

    @classmethod
    def open(cls, path: str | Path) -> "ReceiptTrustAnchorRegistry":
        """Compatibility alias with safe open-existing semantics."""

        return cls.open_existing(path)

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS receipt_trust_anchor_events (
                sequence INTEGER PRIMARY KEY,
                event_hash TEXT NOT NULL UNIQUE,
                event_json TEXT NOT NULL
            );

            CREATE TRIGGER IF NOT EXISTS receipt_trust_anchor_events_no_update
            BEFORE UPDATE ON receipt_trust_anchor_events
            BEGIN
                SELECT RAISE(ABORT, 'receipt trust-anchor events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS receipt_trust_anchor_events_no_delete
            BEFORE DELETE ON receipt_trust_anchor_events
            BEGIN
                SELECT RAISE(ABORT, 'receipt trust-anchor events are append-only');
            END;
            """
        )

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._connection.rollback()
                raise
            else:
                self._connection.commit()

    def ensure_active_anchor(
        self, trust_anchor: Mapping[str, Any]
    ) -> dict[str, Any]:
        configured = _validate_unrevoked_anchor(trust_anchor)
        with self._atomic():
            events = self._verified_events()
            if not events:
                if not self._allow_initial_activation:
                    raise TrustAnchorRegistryError(
                        "existing trust-anchor ledger has no activation record"
                    )
                activation = _activation_payload(configured)
                event = _build_event(
                    sequence=0,
                    event_type="trust_anchor_activated",
                    created_at=str(configured["activated_at"]),
                    idempotency_key=str(activation["activation_id"]),
                    prev_event_hash=TRUST_ANCHOR_LIFECYCLE_GENESIS_HASH,
                    payload=activation,
                )
                self._insert_event(event)
                events = self._verified_events()
                self._allow_initial_activation = False
            state = _project_lifecycle(events)
            recorded = state["trust_anchor"]
            if recorded.get("key_id") != configured.get("key_id") or recorded.get(
                "public_key"
            ) != configured.get("public_key"):
                raise TrustAnchorRegistryError(
                    "configured signing key does not match the recorded trust anchor; rotation is unsupported"
                )
            if recorded.get("activated_at") != configured.get("activated_at"):
                raise TrustAnchorRegistryError(
                    "configured activation timestamp does not match the recorded trust anchor"
                )
            if canonical_bytes(recorded) != canonical_bytes(configured):
                raise TrustAnchorRegistryError(
                    "configured trust anchor bytes do not match the activation record"
                )
            if state["revocation"] is not None:
                raise TrustAnchorRevokedError(
                    "the configured receipt trust anchor is revoked"
                )
            return deepcopy(recorded)

    def revoke_active_anchor(
        self,
        *,
        expected_key_id: str,
        revoked_at: str,
        reason: str,
        idempotency_key: str,
    ) -> TrustAnchorRegistryResult:
        if not isinstance(reason, str) or not reason:
            raise TrustAnchorRegistryError("revocation reason is required")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise TrustAnchorRegistryError("revocation idempotency_key is required")
        with self._atomic():
            events = self._verified_events()
            state = _project_lifecycle(events)
            anchor = state["trust_anchor"]
            if expected_key_id != anchor["key_id"]:
                raise TrustAnchorRegistryError(
                    "revocation expected_key_id does not match the active anchor"
                )
            payload = _revocation_payload(
                anchor=anchor,
                revoked_at=revoked_at,
                reason=reason,
                idempotency_key=idempotency_key,
            )
            existing = state["revocation"]
            if existing is not None:
                existing_event = events[-1]
                if (
                    existing_event["idempotency_key"] == idempotency_key
                    and canonical_bytes(existing) == canonical_bytes(payload)
                ):
                    return TrustAnchorRegistryResult(
                        event=deepcopy(existing_event), replayed=True
                    )
                raise TrustAnchorRevokedError(
                    "the receipt trust anchor is already revoked"
                )
            event = _build_event(
                sequence=len(events),
                event_type="trust_anchor_revoked",
                created_at=revoked_at,
                idempotency_key=idempotency_key,
                prev_event_hash=str(events[-1]["event_hash"]),
                payload=payload,
            )
            self._insert_event(event)
            verified = self._verified_events()
            projected = _project_lifecycle(verified)
            if projected["revocation"] != payload:
                raise TrustAnchorRegistryError(
                    "post-commit trust-anchor revocation reread mismatch"
                )
            return TrustAnchorRegistryResult(event=deepcopy(event))

    def export_ledger(self) -> dict[str, Any]:
        with self._lock:
            events = self._verified_events()
            state = _project_lifecycle(events) if events else None
            return {
                "events": deepcopy(events),
                "registry_export_schema_version": (
                    TRUST_ANCHOR_REGISTRY_EXPORT_VERSION
                ),
                "status": (
                    "missing"
                    if state is None
                    else "revoked"
                    if state["revocation"] is not None
                    else "active"
                ),
                "tip_event_hash": (
                    TRUST_ANCHOR_LIFECYCLE_GENESIS_HASH
                    if not events
                    else events[-1]["event_hash"]
                ),
                "trust_anchor_hash": (
                    ""
                    if state is None
                    else canonical_hash(state["trust_anchor"])
                ),
            }

    def _verified_events(self) -> list[dict[str, Any]]:
        rows = self._connection.execute(
            """
            SELECT sequence, event_hash, event_json
            FROM receipt_trust_anchor_events
            ORDER BY sequence
            """
        ).fetchall()
        events: list[dict[str, Any]] = []
        expected_prev = TRUST_ANCHOR_LIFECYCLE_GENESIS_HASH
        for expected_sequence, row in enumerate(rows):
            stored_json = str(row["event_json"])
            try:
                event = json.loads(stored_json)
            except (TypeError, json.JSONDecodeError) as exc:
                raise TrustAnchorRegistryError(
                    "trust-anchor ledger event JSON is unreadable"
                ) from exc
            if not isinstance(event, dict):
                raise TrustAnchorRegistryError(
                    "trust-anchor ledger event must be an object"
                )
            if stored_json != canonical_json(event):
                raise TrustAnchorRegistryError(
                    "trust-anchor ledger event bytes are not canonical"
                )
            if set(event) != _EVENT_FIELDS:
                raise TrustAnchorRegistryError(
                    "trust-anchor ledger event fields are invalid"
                )
            if event["trust_anchor_lifecycle_event_schema_version"] != (
                TRUST_ANCHOR_LIFECYCLE_EVENT_VERSION
            ):
                raise TrustAnchorRegistryError(
                    "trust-anchor lifecycle event version is unsupported"
                )
            if event["actor_id"] != TRUST_ANCHOR_REGISTRY_ACTOR_ID or event[
                "provenance_class"
            ] != "system":
                raise TrustAnchorRegistryError(
                    "trust-anchor lifecycle event authority mismatch"
                )
            if (
                event["sequence"] != expected_sequence
                or row["sequence"] != expected_sequence
            ):
                raise TrustAnchorRegistryError(
                    "trust-anchor lifecycle sequence is not contiguous"
                )
            if event["prev_event_hash"] != expected_prev:
                raise TrustAnchorRegistryError(
                    "trust-anchor lifecycle previous hash mismatch"
                )
            payload = event.get("payload")
            if not isinstance(payload, dict) or canonical_hash(payload) != event.get(
                "payload_hash"
            ):
                raise TrustAnchorRegistryError(
                    "trust-anchor lifecycle payload hash mismatch"
                )
            envelope = {
                key: deepcopy(value)
                for key, value in event.items()
                if key not in {"event_hash", "payload"}
            }
            if canonical_hash(envelope) != event.get("event_hash") or row[
                "event_hash"
            ] != event.get("event_hash"):
                raise TrustAnchorRegistryError(
                    "trust-anchor lifecycle event hash mismatch"
                )
            expected_prev = str(event["event_hash"])
            events.append(event)
        if events:
            _project_lifecycle(events)
        return events

    def _insert_event(self, event: Mapping[str, Any]) -> None:
        self._connection.execute(
            """
            INSERT INTO receipt_trust_anchor_events
                (sequence, event_hash, event_json)
            VALUES (?, ?, ?)
            """,
            (
                event["sequence"],
                event["event_hash"],
                canonical_json(dict(event)),
            ),
        )

    def _verify_append_only_guards(self) -> None:
        """Prove the persisted ledger refuses mutation before trusting it.

        Object names alone are not sufficient: a replaced no-op trigger could
        otherwise preserve the expected schema names while allowing history to
        be rewritten. Both probes are rolled back even if a guard is missing.
        """

        probes = (
            (
                "UPDATE receipt_trust_anchor_events "
                "SET event_json = event_json WHERE sequence = 0",
                "update",
            ),
            (
                "DELETE FROM receipt_trust_anchor_events WHERE sequence = 0",
                "delete",
            ),
        )
        for statement, operation in probes:
            self._connection.execute("SAVEPOINT verify_append_only_guard")
            try:
                self._connection.execute(statement)
            except sqlite3.IntegrityError as exc:
                if "append-only" not in str(exc):
                    raise TrustAnchorRegistryError(
                        f"trust-anchor ledger {operation} guard is invalid"
                    ) from exc
            else:
                raise TrustAnchorRegistryError(
                    f"trust-anchor ledger {operation} guard is missing"
                )
            finally:
                self._connection.execute(
                    "ROLLBACK TO SAVEPOINT verify_append_only_guard"
                )
                self._connection.execute("RELEASE SAVEPOINT verify_append_only_guard")


def _activation_payload(anchor: Mapping[str, Any]) -> dict[str, Any]:
    anchor_hash = canonical_hash(dict(anchor))
    payload = {
        "activation_id": f"anchor-activation:{anchor_hash}",
        "action_receipt_trust_anchor_activation_schema_version": (
            TRUST_ANCHOR_ACTIVATION_VERSION
        ),
        "trust_anchor": deepcopy(dict(anchor)),
        "trust_anchor_hash": anchor_hash,
    }
    canonical_json(payload)
    return payload


def _revocation_payload(
    *,
    anchor: Mapping[str, Any],
    revoked_at: str,
    reason: str,
    idempotency_key: str,
) -> dict[str, Any]:
    try:
        validate_trust_anchor(
            {**dict(anchor), "revoked_at": revoked_at},
            signing_at=str(anchor["activated_at"]),
        )
    except ActionReceiptError as exc:
        raise TrustAnchorRegistryError(str(exc)) from exc
    anchor_hash = canonical_hash(dict(anchor))
    payload = {
        "action_receipt_trust_anchor_revocation_schema_version": (
            TRUST_ANCHOR_REVOCATION_VERSION
        ),
        "key_id": anchor["key_id"],
        "reason": reason,
        "revocation_id": f"anchor-revocation:{canonical_hash({'idempotency_key': idempotency_key, 'key_id': anchor['key_id'], 'reason': reason, 'revoked_at': revoked_at, 'trust_anchor_hash': anchor_hash})}",
        "revoked_at": revoked_at,
        "trust_anchor_hash": anchor_hash,
    }
    canonical_json(payload)
    return payload


def _build_event(
    *,
    sequence: int,
    event_type: str,
    created_at: str,
    idempotency_key: str,
    prev_event_hash: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    envelope = {
        "actor_id": TRUST_ANCHOR_REGISTRY_ACTOR_ID,
        "created_at": created_at,
        "event_type": event_type,
        "idempotency_key": idempotency_key,
        "payload_hash": canonical_hash(dict(payload)),
        "prev_event_hash": prev_event_hash,
        "provenance_class": "system",
        "sequence": sequence,
        "trust_anchor_lifecycle_event_schema_version": (
            TRUST_ANCHOR_LIFECYCLE_EVENT_VERSION
        ),
    }
    event = {
        **envelope,
        "payload": deepcopy(dict(payload)),
        "event_hash": canonical_hash(envelope),
    }
    canonical_json(event)
    return event


def _project_lifecycle(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    activations: list[tuple[dict[str, Any], Mapping[str, Any]]] = []
    revocations: list[tuple[dict[str, Any], Mapping[str, Any]]] = []
    for sequence, event in enumerate(events):
        event_type = event.get("event_type")
        payload = event.get("payload")
        if event_type == "trust_anchor_activated":
            if sequence != 0:
                raise TrustAnchorRegistryError(
                    "receipt trust-anchor rotation is unsupported"
                )
            activation = _validate_activation_payload(payload)
            if event.get("created_at") != activation["trust_anchor"][
                "activated_at"
            ] or event.get("idempotency_key") != activation["activation_id"]:
                raise TrustAnchorRegistryError(
                    "trust-anchor activation event binding mismatch"
                )
            activations.append((activation, event))
        elif event_type == "trust_anchor_revoked":
            revocation = _validate_revocation_payload(payload)
            if event.get("created_at") != revocation["revoked_at"]:
                raise TrustAnchorRegistryError(
                    "trust-anchor revocation event timestamp mismatch"
                )
            revocations.append((revocation, event))
        else:
            raise TrustAnchorRegistryError(
                "trust-anchor lifecycle event_type is unsupported"
            )
    if len(activations) != 1:
        raise TrustAnchorRegistryError(
            "trust-anchor ledger must contain exactly one activation"
        )
    if len(revocations) > 1:
        raise TrustAnchorRegistryError(
            "trust-anchor ledger contains ambiguous revocations"
        )
    anchor = activations[0][0]["trust_anchor"]
    if revocations:
        revocation, revocation_event = revocations[0]
        if revocation["key_id"] != anchor["key_id"] or revocation[
            "trust_anchor_hash"
        ] != canonical_hash(anchor):
            raise TrustAnchorRegistryError(
                "trust-anchor revocation does not bind the activated anchor"
            )
        try:
            validate_trust_anchor(
                {**anchor, "revoked_at": revocation["revoked_at"]},
                signing_at=str(anchor["activated_at"]),
            )
        except ActionReceiptError as exc:
            raise TrustAnchorRegistryError(str(exc)) from exc
        expected_revocation = _revocation_payload(
            anchor=anchor,
            revoked_at=str(revocation["revoked_at"]),
            reason=str(revocation["reason"]),
            idempotency_key=str(revocation_event["idempotency_key"]),
        )
        if canonical_bytes(expected_revocation) != canonical_bytes(revocation):
            raise TrustAnchorRegistryError(
                "trust-anchor revocation identity mismatch"
            )
    else:
        revocation = None
    return {"revocation": revocation, "trust_anchor": anchor}


def _validate_activation_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _ACTIVATION_FIELDS:
        raise TrustAnchorRegistryError("trust-anchor activation fields are invalid")
    payload = deepcopy(dict(value))
    if payload["action_receipt_trust_anchor_activation_schema_version"] != (
        TRUST_ANCHOR_ACTIVATION_VERSION
    ):
        raise TrustAnchorRegistryError(
            "trust-anchor activation version is unsupported"
        )
    anchor = _validate_unrevoked_anchor(payload["trust_anchor"])
    anchor_hash = canonical_hash(anchor)
    if payload["trust_anchor_hash"] != anchor_hash or payload[
        "activation_id"
    ] != f"anchor-activation:{anchor_hash}":
        raise TrustAnchorRegistryError(
            "trust-anchor activation identity or hash mismatch"
        )
    payload["trust_anchor"] = anchor
    return payload


def _validate_revocation_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _REVOCATION_FIELDS:
        raise TrustAnchorRegistryError("trust-anchor revocation fields are invalid")
    payload = deepcopy(dict(value))
    if payload["action_receipt_trust_anchor_revocation_schema_version"] != (
        TRUST_ANCHOR_REVOCATION_VERSION
    ):
        raise TrustAnchorRegistryError(
            "trust-anchor revocation version is unsupported"
        )
    for field in ("key_id", "reason", "revocation_id", "revoked_at"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise TrustAnchorRegistryError(
                f"trust-anchor revocation {field} is required"
            )
    if not isinstance(payload["trust_anchor_hash"], str) or len(
        payload["trust_anchor_hash"]
    ) != 64:
        raise TrustAnchorRegistryError(
            "trust-anchor revocation anchor hash is invalid"
        )
    canonical_json(payload)
    return payload


def _validate_unrevoked_anchor(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TrustAnchorRegistryError("trust anchor must be an object")
    anchor = deepcopy(dict(value))
    if "revoked_at" in anchor:
        raise TrustAnchorRevokedError(
            "a revoked anchor cannot be activated in the lifecycle registry"
        )
    try:
        validate_trust_anchor(anchor, signing_at=str(anchor.get("activated_at")))
        canonical_bytes(anchor)
    except (ActionReceiptError, CanonicalJsonError) as exc:
        raise TrustAnchorRegistryError(str(exc)) from exc
    return anchor


def _validated_ledger_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        raise TrustAnchorRegistryError(
            "trust-anchor ledger path must be absolute"
        )
    resolved = resolved.resolve(strict=False)
    temporary_roots = {
        Path(tempfile.gettempdir()).resolve(strict=False),
        Path("/tmp").resolve(strict=False),
    }
    if any(resolved == root or root in resolved.parents for root in temporary_roots):
        raise TrustAnchorRegistryError(
            "trust-anchor ledger cannot use the temporary directory"
        )
    return resolved


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Append an explicit revocation to the receipt anchor ledger."
    )
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--expected-key-id", required=True)
    parser.add_argument("--revoked-at", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--idempotency-key", required=True)
    args = parser.parse_args(argv)
    registry = ReceiptTrustAnchorRegistry.open_existing(args.ledger)
    try:
        result = registry.revoke_active_anchor(
            expected_key_id=args.expected_key_id,
            revoked_at=args.revoked_at,
            reason=args.reason,
            idempotency_key=args.idempotency_key,
        )
        print(
            canonical_json(
                {"event": dict(result.event), "replayed": result.replayed}
            )
        )
    finally:
        registry.close()


__all__ = [
    "TRUST_ANCHOR_ACTIVATION_VERSION",
    "TRUST_ANCHOR_LIFECYCLE_EVENT_VERSION",
    "TRUST_ANCHOR_LIFECYCLE_GENESIS_HASH",
    "TRUST_ANCHOR_REGISTRY_EXPORT_VERSION",
    "TRUST_ANCHOR_REVOCATION_VERSION",
    "ReceiptTrustAnchorRegistry",
    "TrustAnchorRegistryError",
    "TrustAnchorRegistryResult",
    "TrustAnchorRevokedError",
    "main",
]
