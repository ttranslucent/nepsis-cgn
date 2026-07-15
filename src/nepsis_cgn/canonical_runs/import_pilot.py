from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
import threading
from typing import Any, Iterator, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from nepsis_cgn.contracts.canonical_json import (
    canonical_hash,
    canonical_json,
)
from nepsis_cgn.contracts.canonical_run import ActorContext, require_capability
from nepsis_cgn.verification.interop_bundle import verify_interop_bundle
from nepsis_cgn.verification.receipts import (
    sign_action_receipt,
    verify_action_receipt,
)


IMPORT_RECEIPT_VERSION = "nepsis.import_receipt@0.1.0"
IMPORT_PILOT_VERSION = "nepsis.cgn_import_pilot@0.1.0"


class ImportPilotError(ValueError):
    """A sealed MC bundle cannot enter the read-only import pilot."""


class ImportConflict(ImportPilotError):
    """A source session or idempotency key was reused for different bytes."""


@dataclass(frozen=True)
class ImportResult:
    receipt: Mapping[str, Any]
    replayed: bool = False


class ImportPilotStore:
    """Durable read-only registry for sealed, independently verified MC bundles."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        private_key: Ed25519PrivateKey,
        trust_anchor: Mapping[str, Any],
        durable: bool,
    ) -> None:
        self._db = connection
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.execute("PRAGMA synchronous = FULL")
        if durable:
            self._db.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.RLock()
        self._private_key = private_key
        self._public_key: Ed25519PublicKey = private_key.public_key()
        self._trust_anchor = dict(trust_anchor)
        self._initialize()

    @classmethod
    def in_memory(
        cls,
        *,
        private_key: Ed25519PrivateKey,
        trust_anchor: Mapping[str, Any],
    ) -> ImportPilotStore:
        return cls(
            sqlite3.connect(
                ":memory:", isolation_level=None, check_same_thread=False
            ),
            private_key=private_key,
            trust_anchor=trust_anchor,
            durable=False,
        )

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        private_key: Ed25519PrivateKey,
        trust_anchor: Mapping[str, Any],
    ) -> ImportPilotStore:
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return cls(
            sqlite3.connect(
                str(resolved), isolation_level=None, check_same_thread=False
            ),
            private_key=private_key,
            trust_anchor=trust_anchor,
            durable=True,
        )

    def close(self) -> None:
        self._db.close()

    def import_sealed_bundle(
        self,
        *,
        bundle: Mapping[str, Any],
        actor: ActorContext,
        idempotency_key: str,
        imported_at: str,
    ) -> ImportResult:
        _require_import_actor(actor)
        _nonempty(idempotency_key, "idempotency_key")
        _timestamp(imported_at, "imported_at")
        if not isinstance(bundle, Mapping):
            raise ImportPilotError("bundle must be an object")
        normalized_bundle = dict(bundle)
        verification = verify_interop_bundle(normalized_bundle)
        subject = normalized_bundle.get("subject")
        if not isinstance(subject, Mapping):
            raise ImportPilotError("bundle subject is missing")
        _require_sealed_subject(subject)
        source_session_id = _nonempty(subject.get("session_id"), "session_id")
        bundle_hash = canonical_hash(normalized_bundle)
        request_hash = canonical_hash(
            {
                "actor_id": actor.actor_id,
                "bundle_hash": bundle_hash,
                "idempotency_key": idempotency_key,
                "imported_at": imported_at,
                "operation": "import_sealed_bundle",
                "source_session_id": source_session_id,
            }
        )

        with self._atomic():
            replay = self._db.execute(
                """
                SELECT request_hash, receipt_json
                FROM mc_import_idempotency WHERE actor_id = ? AND idempotency_key = ?
                """,
                (actor.actor_id, idempotency_key),
            ).fetchone()
            if replay is not None:
                if replay["request_hash"] != request_hash:
                    raise ImportConflict(
                        "import idempotency key was reused for different bytes"
                    )
                return ImportResult(
                    receipt=json.loads(replay["receipt_json"]), replayed=True
                )

            existing = self._db.execute(
                """
                SELECT bundle_hash, receipt_json FROM mc_sealed_imports
                WHERE source_session_id = ?
                """,
                (source_session_id,),
            ).fetchone()
            if existing is not None:
                if existing["bundle_hash"] != bundle_hash:
                    raise ImportConflict(
                        "source session was already imported from different bytes"
                    )
                receipt = json.loads(existing["receipt_json"])
                self._record_idempotency(
                    actor_id=actor.actor_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    receipt=receipt,
                )
                return ImportResult(receipt=receipt, replayed=True)

            imported_run_id = _imported_run_id(source_session_id)
            unsigned = {
                "artifact_root": subject["artifact_root"],
                "authenticity": verification["authenticity"],
                "bundle_hash": bundle_hash,
                "import_pilot_version": IMPORT_PILOT_VERSION,
                "import_receipt_schema_version": IMPORT_RECEIPT_VERSION,
                "imported_at": imported_at,
                "imported_run_id": imported_run_id,
                "read_only": True,
                "receipt_id": f"import-receipt:{bundle_hash}",
                "source_audit_tip": verification["audit_tip"],
                "source_session_id": source_session_id,
                "subject_hash": normalized_bundle["subject_hash"],
                "verification_scope": verification["verification_scope"],
            }
            receipt = sign_action_receipt(
                unsigned,
                private_key=self._private_key,
                trust_anchor=self._trust_anchor,
                signing_at=imported_at,
            )
            if not self.verify_receipt(receipt):
                raise ImportPilotError("issued import receipt did not verify")
            self._db.execute(
                """
                INSERT INTO mc_sealed_imports (
                    source_session_id, imported_run_id, bundle_hash, subject_hash,
                    source_audit_tip, artifact_root, bundle_json, receipt_json,
                    imported_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'read_only')
                """,
                (
                    source_session_id,
                    imported_run_id,
                    bundle_hash,
                    normalized_bundle["subject_hash"],
                    verification["audit_tip"],
                    subject["artifact_root"],
                    canonical_json(normalized_bundle),
                    canonical_json(receipt),
                    imported_at,
                ),
            )
            self._record_idempotency(
                actor_id=actor.actor_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                receipt=receipt,
            )
        return ImportResult(receipt=receipt)

    def get_import(self, source_session_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                """
                SELECT bundle_json, receipt_json, status
                FROM mc_sealed_imports WHERE source_session_id = ?
                """,
                (_nonempty(source_session_id, "source_session_id"),),
            ).fetchone()
            if row is None:
                raise ImportPilotError("import not found")
            if row["status"] != "read_only":
                raise ImportPilotError("import registry contains a mutable status")
            return {
                "bundle": json.loads(row["bundle_json"]),
                "receipt": json.loads(row["receipt_json"]),
                "status": "read_only",
            }

    def verify_receipt(self, receipt: Mapping[str, Any]) -> bool:
        return verify_action_receipt(
            receipt,
            public_key=self._public_key,
            trust_anchor=self._trust_anchor,
        )

    def _record_idempotency(
        self,
        *,
        actor_id: str,
        idempotency_key: str,
        request_hash: str,
        receipt: Mapping[str, Any],
    ) -> None:
        self._db.execute(
            """
            INSERT INTO mc_import_idempotency (
                actor_id, idempotency_key, request_hash, receipt_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                actor_id,
                idempotency_key,
                request_hash,
                canonical_json(dict(receipt)),
            ),
        )

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self._db.rollback()
                raise
            else:
                self._db.commit()

    def _initialize(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS mc_sealed_imports (
                source_session_id TEXT PRIMARY KEY,
                imported_run_id TEXT NOT NULL UNIQUE,
                bundle_hash TEXT NOT NULL UNIQUE,
                subject_hash TEXT NOT NULL,
                source_audit_tip TEXT NOT NULL,
                artifact_root TEXT NOT NULL,
                bundle_json TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status = 'read_only')
            );

            CREATE TABLE IF NOT EXISTS mc_import_idempotency (
                actor_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                receipt_json TEXT NOT NULL,
                PRIMARY KEY(actor_id, idempotency_key)
            );

            CREATE TRIGGER IF NOT EXISTS mc_sealed_imports_no_update
            BEFORE UPDATE ON mc_sealed_imports
            BEGIN
                SELECT RAISE(ABORT, 'sealed MC imports are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS mc_sealed_imports_no_delete
            BEFORE DELETE ON mc_sealed_imports
            BEGIN
                SELECT RAISE(ABORT, 'sealed MC imports cannot be deleted');
            END;

            CREATE TRIGGER IF NOT EXISTS mc_import_idempotency_no_update
            BEFORE UPDATE ON mc_import_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'import outcomes are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS mc_import_idempotency_no_delete
            BEFORE DELETE ON mc_import_idempotency
            BEGIN
                SELECT RAISE(ABORT, 'import outcomes cannot be deleted');
            END;
            """
        )


def _require_import_actor(actor: ActorContext) -> None:
    if not isinstance(actor, ActorContext) or actor.provenance_class != "validator":
        raise ImportPilotError("trusted import-service ActorContext is required")
    try:
        require_capability(actor, "import_sealed_bundle")
    except PermissionError as exc:
        raise ImportPilotError(str(exc)) from exc


def _require_sealed_subject(subject: Mapping[str, Any]) -> None:
    if subject.get("profile") != "full" or subject.get(
        "guarantee_level"
    ) != "full_reconstruction":
        raise ImportPilotError("import pilot requires a full reconstruction bundle")
    if subject.get("redacted_sequences") != [] or subject.get(
        "redacted_artifact_hashes"
    ) != []:
        raise ImportPilotError("redacted or partial bundles cannot be imported")
    decision = subject.get("decision_projection")
    phase = subject.get("phase_projection")
    if not isinstance(decision, Mapping) or decision.get("status") != "committed":
        raise ImportPilotError("source session is not sealed at a committed decision")
    if not isinstance(phase, Mapping) or phase.get("projected_phase") != "exported":
        raise ImportPilotError("source session has not reached exported phase")
    if phase.get("active_hold") is not False:
        raise ImportPilotError("source session retains an active hold")


def _imported_run_id(source_session_id: str) -> str:
    return f"imported-mc:{canonical_hash({'source_session_id': source_session_id})}"


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ImportPilotError(f"{field} must be non-empty text")
    return value


def _timestamp(value: Any, field: str) -> str:
    text = _nonempty(value, field)
    if (
        len(text) != 24
        or text[4] != "-"
        or text[7] != "-"
        or text[10] != "T"
        or text[13] != ":"
        or text[16] != ":"
        or text[19] != "."
        or not text.endswith("Z")
    ):
        raise ImportPilotError(f"{field} must use YYYY-MM-DDTHH:MM:SS.mmmZ")
    return text


__all__ = [
    "IMPORT_PILOT_VERSION",
    "IMPORT_RECEIPT_VERSION",
    "ImportConflict",
    "ImportPilotError",
    "ImportPilotStore",
    "ImportResult",
]
