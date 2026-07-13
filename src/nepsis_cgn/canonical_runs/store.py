from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
import threading
from typing import Any, Callable, Iterator, Mapping, Sequence

from nepsis_cgn.contracts.canonical_json import (
    CanonicalJsonError,
    canonical_bytes,
    canonical_hash,
    canonical_json,
)
from nepsis_cgn.contracts.canonical_run import (
    ActorContext,
    CANONICAL_RUN_GENESIS_HASH,
    build_event,
    require_capability,
    verify_event_chain,
)


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_VERSION_RE = re.compile(r"^nepsis\.[a-z0-9_.-]+@[0-9]+\.[0-9]+\.[0-9]+$")

_ACTION_REQUEST_REQUIRED = {
    "action_request_schema_version",
    "action_type",
    "artifact_hashes",
    "capability",
    "capability_id",
    "created_at",
    "effective_policy_hash",
    "expected_head_event_hash",
    "expected_head_sequence",
    "idempotency_key",
    "intent_hash",
    "operator_governance_profile_hash",
    "payload",
    "payload_hash",
    "run_id",
    "session_governance_snapshot_hash",
    "trusted_adapter_intent_id",
}
_ACTION_REQUEST_OPTIONAL = {
    "context_manifest_hash",
    "external_codex_ref_hash",
    "operator_confirmation",
    "operator_visible_proposal_hash",
}
_ACTION_CAPABILITIES = {
    "submit_model_candidate",
    "submit_operator_disposition",
    "release_still",
    "perform_zeroback",
    "request_decision_commit",
}
_OPERATOR_CAPABILITIES = {
    "submit_operator_disposition",
    "release_still",
    "perform_zeroback",
    "request_decision_commit",
}
_DEFAULT_EVENT_TYPES = {
    "submit_model_candidate": "model_candidate_recorded",
    "submit_operator_disposition": "operator_proposal_disposition_recorded",
    "release_still": "still_released",
    "perform_zeroback": "zeroback_performed",
    "request_decision_commit": "decision_committed",
}
_FORK_PROVENANCE_FIELDS = {
    "fork_reason",
    "forked_from_run_id",
    "inherited_evidence_root_hashes",
    "parent_head_event_hash",
    "policy_diff_artifact_hash",
}
_GOVERNANCE_POLICY_DIFF_VERSION = "nepsis.governance_policy_diff@0.1.0"


class CanonicalRunStoreError(RuntimeError):
    """Base error for canonical-run persistence."""


class InvalidRequest(CanonicalRunStoreError):
    """The request cannot enter the canonical append boundary."""


class IdempotencyConflict(CanonicalRunStoreError):
    """An idempotency key was reused for different request bytes."""


class RunNotFound(CanonicalRunStoreError):
    """The addressed canonical run does not exist."""


@dataclass(frozen=True)
class ArtifactInput:
    artifact_schema_version: str
    roles: tuple[str, ...]
    artifact: Mapping[str, Any]

    @property
    def artifact_hash(self) -> str:
        return canonical_hash(dict(self.artifact))


@dataclass(frozen=True)
class AdmissionDecision:
    """Server-validator output after structural and concurrency admission.

    A refusal advances only the audit head. An admitted decision may supply a
    new packet projection and postcondition; both are embedded in the event so
    projection state remains reconstructable from the export.
    """

    admitted: bool
    event_type: str = ""
    reason_code: str = ""
    detail: str = ""
    packet_projection: Mapping[str, Any] | None = None
    postcondition: Mapping[str, Any] | None = None
    validator_binding: Mapping[str, Any] | None = None

    @classmethod
    def accept(
        cls,
        *,
        event_type: str = "",
        packet_projection: Mapping[str, Any] | None = None,
        postcondition: Mapping[str, Any] | None = None,
        validator_binding: Mapping[str, Any] | None = None,
    ) -> "AdmissionDecision":
        return cls(
            admitted=True,
            event_type=event_type,
            packet_projection=packet_projection,
            postcondition=postcondition,
            validator_binding=validator_binding,
        )

    @classmethod
    def refuse(
        cls,
        *,
        reason_code: str,
        detail: str,
        validator_binding: Mapping[str, Any] | None = None,
    ) -> "AdmissionDecision":
        return cls(
            admitted=False,
            reason_code=reason_code,
            detail=detail,
            validator_binding=validator_binding,
        )


@dataclass(frozen=True)
class AppendResult:
    record: Mapping[str, Any]
    replayed: bool = False

    @property
    def outcome(self) -> str:
        return str(self.record["outcome"])

    @property
    def event_hash(self) -> str | None:
        value = self.record.get("event_hash")
        return value if isinstance(value, str) else None


AdmissionValidator = Callable[[Mapping[str, Any], Mapping[str, Any]], AdmissionDecision]


class CanonicalRunStore:
    """SQLite append boundary for canonical private Nepsis runs.

    The store owns durability, compare-and-swap, idempotency, and transaction
    atomicity. Domain legality remains an injected deterministic validator.
    Receipt signing remains above this layer because only a post-commit reread
    may produce a writer verification receipt.
    """

    def __init__(self, connection: sqlite3.Connection, *, path: Path | None = None):
        self._connection = connection
        self._path = path
        self._lock = threading.RLock()
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA synchronous = FULL")
        if path is not None:
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    @classmethod
    def in_memory(cls) -> "CanonicalRunStore":
        return cls(
            sqlite3.connect(
                ":memory:", isolation_level=None, check_same_thread=False
            )
        )

    @classmethod
    def open(cls, path: str | Path) -> "CanonicalRunStore":
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(resolved),
            isolation_level=None,
            check_same_thread=False,
        )
        return cls(connection, path=resolved)

    def close(self) -> None:
        self._connection.close()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS canonical_runs (
                run_id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                head_sequence INTEGER NOT NULL,
                head_event_hash TEXT NOT NULL,
                packet_projection_hash TEXT NOT NULL,
                operator_governance_profile_hash TEXT NOT NULL,
                session_governance_snapshot_hash TEXT NOT NULL,
                effective_policy_hash TEXT NOT NULL,
                system_policy_bindings_json TEXT NOT NULL,
                fork_provenance_json TEXT,
                creation_fingerprint TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS canonical_run_events (
                run_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_hash TEXT NOT NULL,
                event_json TEXT NOT NULL,
                PRIMARY KEY (run_id, sequence),
                UNIQUE (run_id, event_hash),
                FOREIGN KEY (run_id) REFERENCES canonical_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS canonical_run_artifacts (
                run_id TEXT NOT NULL,
                artifact_hash TEXT NOT NULL,
                artifact_schema_version TEXT NOT NULL,
                created_sequence INTEGER NOT NULL,
                roles_json TEXT NOT NULL,
                artifact_json TEXT NOT NULL,
                row_json TEXT NOT NULL,
                PRIMARY KEY (run_id, artifact_hash),
                FOREIGN KEY (run_id) REFERENCES canonical_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS canonical_run_projections (
                run_id TEXT PRIMARY KEY,
                head_sequence INTEGER NOT NULL,
                head_event_hash TEXT NOT NULL,
                packet_projection_hash TEXT NOT NULL,
                packet_projection_json TEXT NOT NULL,
                phase TEXT NOT NULL,
                governance_status TEXT NOT NULL,
                active_hold INTEGER NOT NULL CHECK (active_hold IN (0, 1)),
                FOREIGN KEY (run_id) REFERENCES canonical_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS canonical_run_outcomes (
                run_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                outcome_ordinal INTEGER NOT NULL,
                intent_hash TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                outcome_json TEXT NOT NULL,
                UNIQUE (run_id, outcome_ordinal),
                PRIMARY KEY (run_id, actor_id, idempotency_key),
                FOREIGN KEY (run_id) REFERENCES canonical_runs(run_id)
            );

            CREATE TRIGGER IF NOT EXISTS canonical_run_events_no_update
            BEFORE UPDATE ON canonical_run_events
            BEGIN
                SELECT RAISE(ABORT, 'canonical run events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS canonical_run_events_no_delete
            BEFORE DELETE ON canonical_run_events
            BEGIN
                SELECT RAISE(ABORT, 'canonical run events are append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS canonical_run_artifacts_no_update
            BEFORE UPDATE ON canonical_run_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'canonical run artifacts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS canonical_run_artifacts_no_delete
            BEFORE DELETE ON canonical_run_artifacts
            BEGIN
                SELECT RAISE(ABORT, 'canonical run artifacts are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS canonical_run_outcomes_no_update
            BEFORE UPDATE ON canonical_run_outcomes
            BEGIN
                SELECT RAISE(ABORT, 'canonical run outcomes are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS canonical_run_outcomes_no_delete
            BEFORE DELETE ON canonical_run_outcomes
            BEGIN
                SELECT RAISE(ABORT, 'canonical run outcomes are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS canonical_run_pins_no_update
            BEFORE UPDATE OF
                owner_id,
                created_at,
                operator_governance_profile_hash,
                session_governance_snapshot_hash,
                effective_policy_hash,
                system_policy_bindings_json,
                creation_fingerprint
            ON canonical_runs
            BEGIN
                SELECT RAISE(ABORT, 'canonical run pins are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS canonical_runs_no_delete
            BEFORE DELETE ON canonical_runs
            BEGIN
                SELECT RAISE(ABORT, 'canonical runs cannot be deleted');
            END;
            """
        )
        columns = {
            str(row[1])
            for row in self._connection.execute(
                "PRAGMA table_info(canonical_runs)"
            ).fetchall()
        }
        if "fork_provenance_json" not in columns:
            self._connection.execute(
                "ALTER TABLE canonical_runs ADD COLUMN fork_provenance_json TEXT"
            )
        self._connection.executescript(
            """
            DROP TRIGGER IF EXISTS canonical_run_fork_provenance_no_update;
            CREATE TRIGGER canonical_run_fork_provenance_no_update
            BEFORE UPDATE OF fork_provenance_json ON canonical_runs
            BEGIN
                SELECT RAISE(ABORT, 'canonical run fork provenance is immutable');
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

    def create_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        created_at: str,
        actor: ActorContext,
        capability_id: str,
        idempotency_key: str,
        operator_governance_profile_hash: str,
        session_governance_snapshot_hash: str,
        effective_policy_hash: str,
        system_policy_bindings: Sequence[Mapping[str, Any]],
        initial_packet_projection: Mapping[str, Any],
        initial_postcondition: Mapping[str, Any],
        fork_provenance: Mapping[str, Any] | None = None,
        fork_policy_diff_artifact: ArtifactInput | Mapping[str, Any] | None = None,
    ) -> AppendResult:
        self._require_actor_capability(actor, "create_run", capability_id)
        if actor.provenance_class != "operator":
            raise InvalidRequest("create_run requires operator provenance")
        _require_nonempty(run_id, "run_id")
        _require_nonempty(owner_id, "owner_id")
        _require_nonempty(idempotency_key, "idempotency_key")
        _require_timestamp(created_at, "created_at")
        for field, value in (
            ("operator_governance_profile_hash", operator_governance_profile_hash),
            ("session_governance_snapshot_hash", session_governance_snapshot_hash),
            ("effective_policy_hash", effective_policy_hash),
        ):
            _require_hash(value, field)
        bindings = _normalize_policy_bindings(system_policy_bindings)
        packet = dict(initial_packet_projection)
        postcondition = _normalize_postcondition(initial_postcondition, packet)
        packet_hash = canonical_hash(packet)
        if postcondition["packet_projection_hash"] != packet_hash:
            raise InvalidRequest("initial postcondition packet hash mismatch")
        normalized_fork = (
            _normalize_fork_provenance(fork_provenance)
            if fork_provenance is not None
            else None
        )
        normalized_diff = (
            _normalize_artifact(fork_policy_diff_artifact)
            if fork_policy_diff_artifact is not None
            else None
        )
        if (normalized_fork is None) != (normalized_diff is None):
            raise InvalidRequest(
                "fork provenance and policy-diff artifact must be supplied together"
            )
        if normalized_fork is not None:
            if normalized_fork["forked_from_run_id"] == run_id:
                raise InvalidRequest("fork predecessor and successor run_ids must differ")
            if normalized_diff is None or normalized_diff.artifact_hash != (
                normalized_fork["policy_diff_artifact_hash"]
            ):
                raise InvalidRequest(
                    "fork policy-diff artifact does not match fork provenance"
                )

        creation_input = {
            "actor_id": actor.actor_id,
            "capability_id": capability_id,
            "created_at": created_at,
            "effective_policy_hash": effective_policy_hash,
            "idempotency_key": idempotency_key,
            "initial_packet_projection": packet,
            "initial_postcondition": postcondition,
            "operator_governance_profile_hash": operator_governance_profile_hash,
            "owner_id": owner_id,
            "run_id": run_id,
            "session_governance_snapshot_hash": session_governance_snapshot_hash,
            "system_policy_bindings": bindings,
        }
        if normalized_fork is not None and normalized_diff is not None:
            creation_input["fork_provenance"] = normalized_fork
            creation_input["fork_policy_diff_artifact"] = {
                "artifact": dict(normalized_diff.artifact),
                "artifact_schema_version": normalized_diff.artifact_schema_version,
                "roles": list(normalized_diff.roles),
            }
        creation_fingerprint = canonical_hash(creation_input)
        intent_hash = canonical_hash(
            {"create_run": creation_input, "operation": "create_run"}
        )

        with self._atomic():
            existing = self._connection.execute(
                "SELECT creation_fingerprint FROM canonical_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if existing is not None:
                replay = self._lookup_outcome(
                    run_id, actor.actor_id, idempotency_key
                )
                if (
                    replay is not None
                    and replay["request_hash"] == creation_fingerprint
                    and replay["intent_hash"] == intent_hash
                ):
                    return AppendResult(json.loads(replay["outcome_json"]), replayed=True)
                raise IdempotencyConflict("run_id or create idempotency key conflicts")

            inherited_artifacts: list[ArtifactInput] = []
            caused_by_event_hashes: tuple[str, ...] = ()
            genesis_artifact_hashes: tuple[str, ...] = ()
            if normalized_fork is not None and normalized_diff is not None:
                parent = self._run_row(str(normalized_fork["forked_from_run_id"]))
                parent_projection = self._projection_row(
                    str(normalized_fork["forked_from_run_id"])
                )
                parent_snapshot = self._snapshot_from_rows(
                    parent, parent_projection
                )
                if parent["status"] != "active":
                    raise InvalidRequest("fork predecessor must be active")
                if parent["owner_id"] != owner_id:
                    raise InvalidRequest("fork predecessor owner mismatch")
                _validate_fork_policy_diff_artifact(
                    normalized_diff,
                    fork_provenance=normalized_fork,
                    parent_effective_policy_hash=str(
                        parent["effective_policy_hash"]
                    ),
                    successor_run_id=run_id,
                    successor_effective_policy_hash=effective_policy_hash,
                    created_at=created_at,
                )
                if parent["head_event_hash"] != normalized_fork[
                    "parent_head_event_hash"
                ]:
                    raise InvalidRequest("fork predecessor head is stale")
                if packet != parent_snapshot["packet_projection"]:
                    raise InvalidRequest(
                        "fork genesis packet must equal the predecessor checkpoint"
                    )
                if postcondition != parent_snapshot["postcondition"]:
                    raise InvalidRequest(
                        "fork genesis postcondition must equal the predecessor checkpoint"
                    )
                inherited_artifacts = self._inherited_artifacts(
                    parent_run_id=str(parent["run_id"]),
                    artifact_hashes=normalized_fork[
                        "inherited_evidence_root_hashes"
                    ],
                )
                parent_event = build_event(
                    run_id=str(parent["run_id"]),
                    sequence=int(parent["head_sequence"]) + 1,
                    event_type="run_forked",
                    created_at=created_at,
                    actor_context=actor,
                    prev_event_hash=str(parent["head_event_hash"]),
                    payload={
                        "fork_provenance": normalized_fork,
                        "packet_projection": parent_snapshot["packet_projection"],
                        "postcondition": parent_snapshot["postcondition"],
                        "resulting_status": "read_only",
                        "successor_run_id": run_id,
                    },
                    caused_by_artifact_hashes=(
                        str(normalized_fork["policy_diff_artifact_hash"]),
                    ),
                    caused_by_event_hashes=(str(parent["head_event_hash"]),),
                    idempotency_key=f"fork-parent:{idempotency_key}",
                    intent_hash=intent_hash,
                    trusted_adapter_intent_id=f"fork-parent:{idempotency_key}",
                )
                self._insert_artifact(
                    str(parent["run_id"]), int(parent_event["sequence"]), normalized_diff
                )
                self._connection.execute(
                    """
                    INSERT INTO canonical_run_events
                        (run_id, sequence, event_hash, event_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        parent["run_id"],
                        parent_event["sequence"],
                        parent_event["event_hash"],
                        canonical_json(parent_event),
                    ),
                )
                self._write_projection(
                    run_id=str(parent["run_id"]),
                    head_sequence=int(parent_event["sequence"]),
                    head_event_hash=str(parent_event["event_hash"]),
                    packet_projection=parent_snapshot["packet_projection"],
                    postcondition=parent_snapshot["postcondition"],
                    insert=False,
                )
                frozen = self._connection.execute(
                    """
                    UPDATE canonical_runs
                    SET status = 'read_only', head_sequence = ?,
                        head_event_hash = ?
                    WHERE run_id = ? AND status = 'active'
                        AND head_sequence = ? AND head_event_hash = ?
                    """,
                    (
                        parent_event["sequence"],
                        parent_event["event_hash"],
                        parent["run_id"],
                        parent["head_sequence"],
                        parent["head_event_hash"],
                    ),
                )
                if frozen.rowcount != 1:
                    raise CanonicalRunStoreError(
                        "fork predecessor freeze compare-and-swap failed"
                    )
                frozen_parent = self._run_row(str(parent["run_id"]))
                parent_fork_idempotency_key = f"fork-parent:{idempotency_key}"
                parent_fork_request_hash = canonical_hash(
                    {
                        "child_creation_fingerprint": creation_fingerprint,
                        "fork_provenance": normalized_fork,
                        "operation": "fork_run",
                    }
                )
                parent_outcome = self._build_outcome(
                    request_hash=parent_fork_request_hash,
                    intent_hash=intent_hash,
                    run=frozen_parent,
                    actor=actor,
                    capability="fork_run",
                    capability_id=capability_id,
                    idempotency_key=parent_fork_idempotency_key,
                    trusted_adapter_intent_id=parent_fork_idempotency_key,
                    expected_head_sequence=int(parent["head_sequence"]),
                    expected_head_event_hash=str(parent["head_event_hash"]),
                    prior_head_sequence=int(parent["head_sequence"]),
                    prior_head_event_hash=str(parent["head_event_hash"]),
                    outcome="committed",
                    event_hash=str(parent_event["event_hash"]),
                    artifact_hashes=(normalized_diff.artifact_hash,),
                    resulting_head_sequence=int(parent_event["sequence"]),
                    resulting_head_event_hash=str(parent_event["event_hash"]),
                    packet_projection_hash=str(
                        parent_snapshot["postcondition"][
                            "packet_projection_hash"
                        ]
                    ),
                    postcondition=parent_snapshot["postcondition"],
                    issued_at=created_at,
                )
                self._insert_outcome(
                    run_id=str(parent["run_id"]),
                    actor_id=actor.actor_id,
                    idempotency_key=parent_fork_idempotency_key,
                    intent_hash=intent_hash,
                    request_hash=parent_fork_request_hash,
                    outcome=parent_outcome,
                )
                caused_by_event_hashes = (str(parent_event["event_hash"]),)
                genesis_artifact_hashes = tuple(
                    sorted(
                        {
                            normalized_diff.artifact_hash,
                            *(item.artifact_hash for item in inherited_artifacts),
                        }
                    )
                )

            payload = {
                "effective_policy_hash": effective_policy_hash,
                "initial_packet_projection": packet,
                "initial_postcondition": postcondition,
                "operator_governance_profile_hash": operator_governance_profile_hash,
                "owner_id": owner_id,
                "session_governance_snapshot_hash": session_governance_snapshot_hash,
                "system_policy_bindings": bindings,
            }
            if normalized_fork is not None:
                payload["fork_provenance"] = normalized_fork
            event = build_event(
                run_id=run_id,
                sequence=0,
                event_type="run_created",
                created_at=created_at,
                actor_context=actor,
                prev_event_hash=CANONICAL_RUN_GENESIS_HASH,
                payload=payload,
                caused_by_artifact_hashes=genesis_artifact_hashes,
                caused_by_event_hashes=caused_by_event_hashes,
                idempotency_key=idempotency_key,
                intent_hash=intent_hash,
                trusted_adapter_intent_id=f"create:{idempotency_key}",
            )
            event_json = canonical_json(event)
            self._connection.execute(
                """
                INSERT INTO canonical_runs (
                    run_id, owner_id, created_at, status, head_sequence,
                    head_event_hash, packet_projection_hash,
                    operator_governance_profile_hash,
                    session_governance_snapshot_hash, effective_policy_hash,
                    system_policy_bindings_json, fork_provenance_json,
                    creation_fingerprint
                ) VALUES (?, ?, ?, 'active', 0, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    owner_id,
                    created_at,
                    event["event_hash"],
                    packet_hash,
                    operator_governance_profile_hash,
                    session_governance_snapshot_hash,
                    effective_policy_hash,
                    canonical_json(bindings),
                    (
                        canonical_json(normalized_fork)
                        if normalized_fork is not None
                        else None
                    ),
                    creation_fingerprint,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO canonical_run_events
                    (run_id, sequence, event_hash, event_json)
                VALUES (?, 0, ?, ?)
                """,
                (run_id, event["event_hash"], event_json),
            )
            for inherited in inherited_artifacts:
                self._insert_artifact(run_id, 0, inherited)
            if normalized_diff is not None:
                self._insert_artifact(run_id, 0, normalized_diff)
            self._write_projection(
                run_id=run_id,
                head_sequence=0,
                head_event_hash=event["event_hash"],
                packet_projection=packet,
                postcondition=postcondition,
                insert=True,
            )
            outcome = self._build_outcome(
                request_hash=creation_fingerprint,
                intent_hash=intent_hash,
                run=self._run_row(run_id),
                actor=actor,
                capability="create_run",
                capability_id=capability_id,
                idempotency_key=idempotency_key,
                trusted_adapter_intent_id=f"create:{idempotency_key}",
                expected_head_sequence=0,
                expected_head_event_hash=CANONICAL_RUN_GENESIS_HASH,
                prior_head_sequence=0,
                prior_head_event_hash=CANONICAL_RUN_GENESIS_HASH,
                outcome="committed",
                event_hash=event["event_hash"],
                artifact_hashes=genesis_artifact_hashes,
                resulting_head_sequence=0,
                resulting_head_event_hash=event["event_hash"],
                packet_projection_hash=packet_hash,
                postcondition=postcondition,
                issued_at=created_at,
            )
            self._insert_outcome(
                run_id=run_id,
                actor_id=actor.actor_id,
                idempotency_key=idempotency_key,
                intent_hash=intent_hash,
                request_hash=creation_fingerprint,
                outcome=outcome,
            )
        return AppendResult(outcome)

    def append_action(
        self,
        *,
        actor: ActorContext,
        request: Mapping[str, Any],
        artifacts: Sequence[ArtifactInput | Mapping[str, Any]] = (),
        validator: AdmissionValidator,
    ) -> AppendResult:
        try:
            normalized = _validate_action_request(request)
            self._require_actor_capability(
                actor,
                str(normalized["capability"]),
                str(normalized["capability_id"]),
            )
        except (CanonicalJsonError, InvalidRequest) as exc:
            return self._invalid_outcome(actor=actor, request=request, detail=str(exc))

        run_id = str(normalized["run_id"])
        capability = str(normalized["capability"])
        request_hash = canonical_hash(normalized)
        intent_hash = str(normalized["intent_hash"])
        idempotency_key = str(normalized["idempotency_key"])
        artifact_inputs = tuple(_normalize_artifact(item) for item in artifacts)

        with self._atomic():
            run = self._run_row(run_id)
            replay = self._lookup_outcome(run_id, actor.actor_id, idempotency_key)
            if replay is not None:
                if (
                    replay["request_hash"] == request_hash
                    and replay["intent_hash"] == intent_hash
                ):
                    return AppendResult(json.loads(replay["outcome_json"]), replayed=True)
                raise IdempotencyConflict(
                    "idempotency key was already used for different request bytes"
                )

            projection = self._projection_row(run_id)
            expected_sequence = int(normalized["expected_head_sequence"])
            expected_hash = str(normalized["expected_head_event_hash"])
            if run["status"] != "active":
                return AppendResult(
                    self._build_nonmutating_outcome(
                        actor=actor,
                        request=normalized,
                        request_hash=request_hash,
                        run=run,
                        projection=projection,
                        outcome="invalid_request",
                        reason_code="run_not_active",
                        detail=(
                            "canonical run is read-only and cannot accept new actions"
                        ),
                    )
                )
            if (
                expected_sequence != int(run["head_sequence"])
                or expected_hash != str(run["head_event_hash"])
            ):
                outcome = self._build_nonmutating_outcome(
                    actor=actor,
                    request=normalized,
                    request_hash=request_hash,
                    run=run,
                    projection=projection,
                    outcome="stale_head",
                    reason_code="stale_expected_head",
                    detail="expected head does not match the current canonical head",
                )
                self._insert_outcome(
                    run_id=run_id,
                    actor_id=actor.actor_id,
                    idempotency_key=idempotency_key,
                    intent_hash=intent_hash,
                    request_hash=request_hash,
                    outcome=outcome,
                )
                return AppendResult(outcome)

            pin_error = self._pin_error(run, normalized)
            if pin_error:
                return self._invalid_outcome(
                    actor=actor,
                    request=normalized,
                    detail=pin_error,
                    known_run=run,
                    known_projection=projection,
                )

            supplied = {item.artifact_hash: item for item in artifact_inputs}
            if len(supplied) != len(artifact_inputs):
                return self._invalid_outcome(
                    actor=actor,
                    request=normalized,
                    detail="duplicate supplied artifact hash",
                    known_run=run,
                    known_projection=projection,
                )
            referenced_hashes = tuple(str(value) for value in normalized["artifact_hashes"])
            if set(supplied) - set(referenced_hashes):
                return self._invalid_outcome(
                    actor=actor,
                    request=normalized,
                    detail="supplied artifact is not referenced by the request",
                    known_run=run,
                    known_projection=projection,
                )
            missing = [
                value
                for value in referenced_hashes
                if value not in supplied and not self._artifact_exists(run_id, value)
            ]
            if missing:
                return self._invalid_outcome(
                    actor=actor,
                    request=normalized,
                    detail=f"referenced artifact is unavailable: {missing[0]}",
                    known_run=run,
                    known_projection=projection,
                )

            current_snapshot = self._snapshot_from_rows(run, projection)
            decision = validator(normalized, current_snapshot)
            _validate_admission_decision(decision)

            next_sequence = int(run["head_sequence"]) + 1
            for item in artifact_inputs:
                self._insert_artifact(run_id, next_sequence, item)

            current_packet = json.loads(projection["packet_projection_json"])
            current_postcondition = {
                "active_hold": bool(projection["active_hold"]),
                "governance_status": str(projection["governance_status"]),
                "packet_projection_hash": str(projection["packet_projection_hash"]),
                "phase": str(projection["phase"]),
            }
            if decision.admitted:
                resulting_packet = (
                    dict(decision.packet_projection)
                    if decision.packet_projection is not None
                    else current_packet
                )
                postcondition = _normalize_postcondition(
                    decision.postcondition or current_postcondition,
                    resulting_packet,
                )
                event_type = decision.event_type or _DEFAULT_EVENT_TYPES[capability]
                event_actor = (
                    self._validator_actor()
                    if capability == "request_decision_commit"
                    else actor
                )
                event_payload = {
                    "action_payload": dict(normalized["payload"]),
                    "capability": capability,
                    "packet_projection": resulting_packet,
                    "postcondition": postcondition,
                }
                if "operator_confirmation" in normalized:
                    event_payload["operator_confirmation"] = dict(
                        normalized["operator_confirmation"]
                    )
                if capability == "request_decision_commit":
                    event_payload["requested_by_actor_id"] = actor.actor_id
                outcome_name = (
                    "candidate_recorded"
                    if capability == "submit_model_candidate"
                    else "committed"
                )
                reason_code = ""
                detail = ""
            else:
                resulting_packet = current_packet
                postcondition = current_postcondition
                event_type = "validator_refusal_created"
                event_actor = self._validator_actor()
                event_payload = {
                    "attempted_action_type": str(normalized["action_type"]),
                    "attempted_capability": capability,
                    "attempted_intent_hash": intent_hash,
                    "detail": decision.detail,
                    "reason_code": decision.reason_code,
                    "requested_by_actor_id": actor.actor_id,
                }
                outcome_name = "refused"
                reason_code = decision.reason_code
                detail = decision.detail
            if decision.validator_binding is not None:
                event_payload["validator_binding"] = dict(
                    decision.validator_binding
                )

            event = build_event(
                run_id=run_id,
                sequence=next_sequence,
                event_type=event_type,
                created_at=str(normalized["created_at"]),
                actor_context=event_actor,
                prev_event_hash=str(run["head_event_hash"]),
                payload=event_payload,
                caused_by_artifact_hashes=referenced_hashes,
                caused_by_event_hashes=(str(run["head_event_hash"]),),
                idempotency_key=idempotency_key,
                intent_hash=intent_hash,
                trusted_adapter_intent_id=str(
                    normalized["trusted_adapter_intent_id"]
                ),
                context_manifest_hash=normalized.get("context_manifest_hash"),
            )
            self._connection.execute(
                """
                INSERT INTO canonical_run_events
                    (run_id, sequence, event_hash, event_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    run_id,
                    next_sequence,
                    event["event_hash"],
                    canonical_json(event),
                ),
            )
            packet_hash = canonical_hash(resulting_packet)
            self._write_projection(
                run_id=run_id,
                head_sequence=next_sequence,
                head_event_hash=event["event_hash"],
                packet_projection=resulting_packet,
                postcondition=postcondition,
                insert=False,
            )
            updated = self._connection.execute(
                """
                UPDATE canonical_runs
                SET head_sequence = ?, head_event_hash = ?, packet_projection_hash = ?
                WHERE run_id = ? AND head_sequence = ? AND head_event_hash = ?
                """,
                (
                    next_sequence,
                    event["event_hash"],
                    packet_hash,
                    run_id,
                    run["head_sequence"],
                    run["head_event_hash"],
                ),
            )
            if updated.rowcount != 1:
                raise CanonicalRunStoreError("canonical head compare-and-swap failed")

            reread_run = self._run_row(run_id)
            reread_projection = self._projection_row(run_id)
            if (
                reread_run["head_event_hash"] != event["event_hash"]
                or reread_projection["head_event_hash"] != event["event_hash"]
            ):
                raise CanonicalRunStoreError("post-write head reread mismatch")
            outcome = self._build_outcome(
                request_hash=request_hash,
                intent_hash=intent_hash,
                run=reread_run,
                actor=actor,
                capability=capability,
                capability_id=str(normalized["capability_id"]),
                idempotency_key=idempotency_key,
                trusted_adapter_intent_id=str(
                    normalized["trusted_adapter_intent_id"]
                ),
                expected_head_sequence=expected_sequence,
                expected_head_event_hash=expected_hash,
                prior_head_sequence=int(run["head_sequence"]),
                prior_head_event_hash=str(run["head_event_hash"]),
                outcome=outcome_name,
                event_hash=event["event_hash"],
                artifact_hashes=referenced_hashes,
                resulting_head_sequence=next_sequence,
                resulting_head_event_hash=event["event_hash"],
                packet_projection_hash=str(
                    reread_projection["packet_projection_hash"]
                ),
                postcondition=postcondition,
                issued_at=str(normalized["created_at"]),
                context_manifest_hash=normalized.get("context_manifest_hash"),
                reason_code=reason_code,
                detail=detail,
            )
            self._insert_outcome(
                run_id=run_id,
                actor_id=actor.actor_id,
                idempotency_key=idempotency_key,
                intent_hash=intent_hash,
                request_hash=request_hash,
                outcome=outcome,
            )
        return AppendResult(outcome)

    def get_snapshot(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_from_rows(
                self._run_row(run_id), self._projection_row(run_id)
            )

    def get_artifact(self, run_id: str, artifact_hash: str) -> dict[str, Any]:
        _require_hash(artifact_hash, "artifact_hash")
        with self._lock:
            row = self._connection.execute(
                """
                SELECT artifact_hash, artifact_schema_version, roles_json,
                       artifact_json, row_json
                FROM canonical_run_artifacts
                WHERE run_id = ? AND artifact_hash = ?
                """,
                (run_id, artifact_hash),
            ).fetchone()
            if row is None:
                raise InvalidRequest(
                    f"referenced artifact is unavailable: {artifact_hash}"
                )
            try:
                roles = json.loads(str(row["roles_json"]))
                artifact = json.loads(str(row["artifact_json"]))
                exported = json.loads(str(row["row_json"]))
            except json.JSONDecodeError as exc:
                raise CanonicalRunStoreError(
                    "canonical run artifact row is unreadable"
                ) from exc
            if (
                canonical_json(roles) != row["roles_json"]
                or canonical_json(artifact) != row["artifact_json"]
                or canonical_json(exported) != row["row_json"]
                or canonical_hash(artifact) != artifact_hash
                or exported.get("run_id") != run_id
                or exported.get("artifact_hash") != artifact_hash
                or exported.get("artifact") != artifact
                or exported.get("roles") != roles
                or exported.get("artifact_schema_version")
                != row["artifact_schema_version"]
            ):
                raise CanonicalRunStoreError(
                    "canonical run artifact row does not match its canonical bytes"
                )
            return deepcopy(exported)

    def get_outcome(
        self, *, run_id: str, actor_id: str, idempotency_key: str
    ) -> AppendResult | None:
        with self._lock:
            row = self._lookup_outcome(run_id, actor_id, idempotency_key)
            if row is None:
                return None
            return AppendResult(json.loads(row["outcome_json"]), replayed=True)

    def export_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._run_row(run_id)
            projection = self._projection_row(run_id)
            verified_snapshot = self._snapshot_from_rows(run, projection)
            event_rows = self._connection.execute(
                """
                SELECT event_json FROM canonical_run_events
                WHERE run_id = ? ORDER BY sequence
                """,
                (run_id,),
            ).fetchall()
            artifact_rows = self._connection.execute(
                """
                SELECT row_json FROM canonical_run_artifacts
                WHERE run_id = ? ORDER BY created_sequence, artifact_hash
                """,
                (run_id,),
            ).fetchall()
            outcome_rows = self._connection.execute(
                """
                SELECT outcome_json FROM canonical_run_outcomes
                WHERE run_id = ? ORDER BY outcome_ordinal
                """,
                (run_id,),
            ).fetchall()
            events = [json.loads(row["event_json"]) for row in event_rows]
            verify_event_chain(events)
            if (
                not events
                or events[-1]["event_hash"] != run["head_event_hash"]
                or events[-1]["sequence"] != run["head_sequence"]
            ):
                raise CanonicalRunStoreError("stored run head does not match event chain")
            if canonical_hash(
                json.loads(projection["packet_projection_json"])
            ) != projection["packet_projection_hash"]:
                raise CanonicalRunStoreError("stored packet projection hash mismatch")
            if projection["packet_projection_hash"] != run["packet_projection_hash"]:
                raise CanonicalRunStoreError("run and projection packet hashes differ")
            exported = {
                "artifacts": [json.loads(row["row_json"]) for row in artifact_rows],
                "effective_policy_hash": str(run["effective_policy_hash"]),
                "events": events,
                "export_schema_version": "nepsis.canonical_run_store_export@0.1.0",
                "outcomes": [
                    json.loads(row["outcome_json"]) for row in outcome_rows
                ],
                "packet_projection": verified_snapshot["packet_projection"],
                "postcondition": verified_snapshot["postcondition"],
                "run": {
                    "canonical_run_schema_version": "nepsis.canonical_run@0.1.0",
                    "created_at": str(run["created_at"]),
                    "head_event_hash": str(run["head_event_hash"]),
                    "head_sequence": int(run["head_sequence"]),
                    "operator_governance_profile_hash": str(
                        run["operator_governance_profile_hash"]
                    ),
                    "owner_id": str(run["owner_id"]),
                    "packet_projection_hash": str(
                        run["packet_projection_hash"]
                    ),
                    "run_id": str(run["run_id"]),
                    "session_governance_snapshot_hash": str(
                        run["session_governance_snapshot_hash"]
                    ),
                    "status": str(run["status"]),
                    "system_policy_bindings": json.loads(
                        run["system_policy_bindings_json"]
                    ),
                },
            }
            if verified_snapshot.get("fork_provenance") is not None:
                exported["run"]["fork_provenance"] = deepcopy(
                    verified_snapshot["fork_provenance"]
                )
            return exported

    def export_run_bytes(self, run_id: str) -> bytes:
        return canonical_bytes(self.export_run(run_id))

    def _run_row(self, run_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM canonical_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise RunNotFound(run_id)
        return row

    def _projection_row(self, run_id: str) -> sqlite3.Row:
        row = self._connection.execute(
            "SELECT * FROM canonical_run_projections WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise CanonicalRunStoreError("canonical run projection is missing")
        return row

    def _lookup_outcome(
        self, run_id: str, actor_id: str, idempotency_key: str
    ) -> sqlite3.Row | None:
        return self._connection.execute(
            """
            SELECT * FROM canonical_run_outcomes
            WHERE run_id = ? AND actor_id = ? AND idempotency_key = ?
            """,
            (run_id, actor_id, idempotency_key),
        ).fetchone()

    def _insert_outcome(
        self,
        *,
        run_id: str,
        actor_id: str,
        idempotency_key: str,
        intent_hash: str,
        request_hash: str,
        outcome: Mapping[str, Any],
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO canonical_run_outcomes (
                run_id, actor_id, idempotency_key, outcome_ordinal,
                intent_hash, request_hash, outcome_json
            )
            SELECT ?, ?, ?, COALESCE(MAX(outcome_ordinal), -1) + 1, ?, ?, ?
            FROM canonical_run_outcomes
            WHERE run_id = ?
            """,
            (
                run_id,
                actor_id,
                idempotency_key,
                intent_hash,
                request_hash,
                canonical_json(dict(outcome)),
                run_id,
            ),
        )

    def _write_projection(
        self,
        *,
        run_id: str,
        head_sequence: int,
        head_event_hash: str,
        packet_projection: Mapping[str, Any],
        postcondition: Mapping[str, Any],
        insert: bool,
    ) -> None:
        packet = dict(packet_projection)
        packet_hash = canonical_hash(packet)
        if postcondition["packet_projection_hash"] != packet_hash:
            raise CanonicalRunStoreError("projection postcondition hash mismatch")
        values = (
            head_sequence,
            head_event_hash,
            packet_hash,
            canonical_json(packet),
            str(postcondition["phase"]),
            str(postcondition["governance_status"]),
            int(bool(postcondition["active_hold"])),
            run_id,
        )
        if insert:
            self._connection.execute(
                """
                INSERT INTO canonical_run_projections (
                    head_sequence, head_event_hash, packet_projection_hash,
                    packet_projection_json, phase, governance_status,
                    active_hold, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        else:
            updated = self._connection.execute(
                """
                UPDATE canonical_run_projections
                SET head_sequence = ?, head_event_hash = ?,
                    packet_projection_hash = ?, packet_projection_json = ?,
                    phase = ?, governance_status = ?, active_hold = ?
                WHERE run_id = ?
                """,
                values,
            )
            if updated.rowcount != 1:
                raise CanonicalRunStoreError("projection update failed")

    def _insert_artifact(
        self, run_id: str, created_sequence: int, item: ArtifactInput
    ) -> None:
        artifact_hash = item.artifact_hash
        existing = self._connection.execute(
            """
            SELECT artifact_schema_version, roles_json, artifact_json
            FROM canonical_run_artifacts
            WHERE run_id = ? AND artifact_hash = ?
            """,
            (run_id, artifact_hash),
        ).fetchone()
        roles = sorted(set(item.roles))
        artifact = dict(item.artifact)
        roles_json = canonical_json(roles)
        artifact_json = canonical_json(artifact)
        if existing is not None:
            if (
                existing["artifact_schema_version"] != item.artifact_schema_version
                or existing["roles_json"] != roles_json
                or existing["artifact_json"] != artifact_json
            ):
                raise InvalidRequest("artifact hash conflicts with immutable row")
            return
        row = {
            "artifact": artifact,
            "artifact_hash": artifact_hash,
            "artifact_schema_version": item.artifact_schema_version,
            "canonical_run_artifact_schema_version": (
                "nepsis.canonical_run_artifact@0.1.0"
            ),
            "created_sequence": created_sequence,
            "roles": roles,
            "run_id": run_id,
        }
        self._connection.execute(
            """
            INSERT INTO canonical_run_artifacts (
                run_id, artifact_hash, artifact_schema_version,
                created_sequence, roles_json, artifact_json, row_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                artifact_hash,
                item.artifact_schema_version,
                created_sequence,
                roles_json,
                artifact_json,
                canonical_json(row),
            ),
        )

    def _artifact_exists(self, run_id: str, artifact_hash: str) -> bool:
        return (
            self._connection.execute(
                """
                SELECT 1 FROM canonical_run_artifacts
                WHERE run_id = ? AND artifact_hash = ?
                """,
                (run_id, artifact_hash),
            ).fetchone()
            is not None
        )

    def _inherited_artifacts(
        self, *, parent_run_id: str, artifact_hashes: Sequence[str]
    ) -> list[ArtifactInput]:
        inherited: list[ArtifactInput] = []
        for artifact_hash in artifact_hashes:
            row = self._connection.execute(
                """
                SELECT artifact_hash, artifact_schema_version, roles_json,
                       artifact_json, row_json
                FROM canonical_run_artifacts
                WHERE run_id = ? AND artifact_hash = ?
                """,
                (parent_run_id, artifact_hash),
            ).fetchone()
            if row is None:
                raise InvalidRequest(
                    f"inherited evidence root is unavailable: {artifact_hash}"
                )
            try:
                roles = json.loads(str(row["roles_json"]))
                artifact = json.loads(str(row["artifact_json"]))
                stored_row = json.loads(str(row["row_json"]))
            except json.JSONDecodeError as exc:
                raise CanonicalRunStoreError(
                    "inherited artifact row is unreadable"
                ) from exc
            if (
                canonical_json(roles) != row["roles_json"]
                or canonical_json(artifact) != row["artifact_json"]
                or canonical_json(stored_row) != row["row_json"]
                or canonical_hash(artifact) != artifact_hash
                or stored_row.get("artifact_hash") != artifact_hash
                or stored_row.get("run_id") != parent_run_id
                or stored_row.get("artifact") != artifact
                or stored_row.get("roles") != roles
                or stored_row.get("artifact_schema_version")
                != row["artifact_schema_version"]
            ):
                raise CanonicalRunStoreError(
                    "inherited artifact row does not match its canonical bytes"
                )
            inherited.append(
                ArtifactInput(
                    artifact_schema_version=str(row["artifact_schema_version"]),
                    roles=tuple(roles),
                    artifact=dict(artifact),
                )
            )
        return inherited

    def _pin_error(
        self, run: sqlite3.Row, request: Mapping[str, Any]
    ) -> str:
        for field in (
            "operator_governance_profile_hash",
            "session_governance_snapshot_hash",
            "effective_policy_hash",
        ):
            if request[field] != run[field]:
                return f"request {field} does not match the pinned run value"
        return ""

    def _snapshot_from_rows(
        self, run: sqlite3.Row, projection: sqlite3.Row
    ) -> dict[str, Any]:
        event_rows = self._connection.execute(
            """
            SELECT sequence, event_hash, event_json
            FROM canonical_run_events
            WHERE run_id = ? ORDER BY sequence
            """,
            (run["run_id"],),
        ).fetchall()
        events: list[dict[str, Any]] = []
        for row in event_rows:
            try:
                event = json.loads(row["event_json"])
            except json.JSONDecodeError as exc:
                raise CanonicalRunStoreError(
                    "canonical run event JSON is invalid"
                ) from exc
            if (
                canonical_json(event) != row["event_json"]
                or event.get("sequence") != row["sequence"]
                or event.get("event_hash") != row["event_hash"]
            ):
                raise CanonicalRunStoreError(
                    "canonical run event row does not match its canonical bytes"
                )
            events.append(event)
        try:
            verify_event_chain(events)
        except ValueError as exc:
            raise CanonicalRunStoreError(str(exc)) from exc
        if not events:
            raise CanonicalRunStoreError("canonical run event chain is missing")
        genesis = events[0]
        genesis_payload = genesis.get("payload")
        if (
            genesis.get("event_type") != "run_created"
            or genesis.get("actor_id") != run["owner_id"]
            or genesis.get("created_at") != run["created_at"]
            or not isinstance(genesis_payload, dict)
        ):
            raise CanonicalRunStoreError(
                "canonical run pins do not match the genesis event"
            )
        pin_fields = {
            "effective_policy_hash": "effective_policy_hash",
            "operator_governance_profile_hash": (
                "operator_governance_profile_hash"
            ),
            "owner_id": "owner_id",
            "session_governance_snapshot_hash": (
                "session_governance_snapshot_hash"
            ),
        }
        for payload_field, run_field in pin_fields.items():
            if genesis_payload.get(payload_field) != run[run_field]:
                raise CanonicalRunStoreError(
                    f"canonical run {run_field} does not match genesis"
                )
        try:
            pinned_bindings = _normalize_policy_bindings(
                genesis_payload.get("system_policy_bindings")
            )
            stored_bindings = json.loads(run["system_policy_bindings_json"])
        except (InvalidRequest, TypeError, json.JSONDecodeError) as exc:
            raise CanonicalRunStoreError(
                "canonical run policy bindings are invalid"
            ) from exc
        if (
            canonical_json(stored_bindings) != run["system_policy_bindings_json"]
            or stored_bindings != pinned_bindings
        ):
            raise CanonicalRunStoreError(
                "canonical run policy bindings do not match genesis"
            )
        stored_fork_json = run["fork_provenance_json"]
        genesis_fork = genesis_payload.get("fork_provenance")
        if stored_fork_json is None:
            if genesis_fork is not None:
                raise CanonicalRunStoreError(
                    "genesis fork provenance is missing from immutable run pins"
                )
            fork_provenance = None
            if genesis.get("caused_by_event_hashes"):
                raise CanonicalRunStoreError(
                    "non-fork genesis cannot claim a predecessor event"
                )
        else:
            try:
                stored_fork = json.loads(str(stored_fork_json))
                fork_provenance = _normalize_fork_provenance(stored_fork)
            except (InvalidRequest, TypeError, json.JSONDecodeError) as exc:
                raise CanonicalRunStoreError(
                    "stored fork provenance is invalid"
                ) from exc
            if (
                canonical_json(stored_fork) != stored_fork_json
                or genesis_fork != fork_provenance
            ):
                raise CanonicalRunStoreError(
                    "canonical run fork provenance does not match genesis"
                )
            expected_artifacts = sorted(
                {
                    str(fork_provenance["policy_diff_artifact_hash"]),
                    *fork_provenance["inherited_evidence_root_hashes"],
                }
            )
            if genesis.get("caused_by_artifact_hashes") != expected_artifacts:
                raise CanonicalRunStoreError(
                    "fork genesis artifact lineage does not match provenance"
                )
            for artifact_hash in expected_artifacts:
                if not self._artifact_exists(str(run["run_id"]), artifact_hash):
                    raise CanonicalRunStoreError(
                        "fork genesis references an unavailable artifact"
                    )
            self._verify_fork_predecessor(
                child_run=run,
                child_genesis=genesis,
                fork_provenance=fork_provenance,
            )
        initial_packet = genesis_payload.get("initial_packet_projection")
        initial_postcondition = genesis_payload.get("initial_postcondition")
        if not isinstance(initial_packet, dict):
            raise CanonicalRunStoreError("genesis packet projection is invalid")
        packet = dict(initial_packet)
        try:
            postcondition = _normalize_postcondition(
                initial_postcondition, packet
            )
        except InvalidRequest as exc:
            raise CanonicalRunStoreError(str(exc)) from exc
        replayed_status = "active"
        for event_index, event in enumerate(events[1:], start=1):
            payload = event.get("payload")
            if not isinstance(payload, dict):
                raise CanonicalRunStoreError("canonical event payload is invalid")
            if replayed_status != "active":
                raise CanonicalRunStoreError(
                    "canonical run contains an event after becoming read-only"
                )
            if event.get("event_type") == "run_forked":
                if set(payload) != {
                    "fork_provenance",
                    "packet_projection",
                    "postcondition",
                    "resulting_status",
                    "successor_run_id",
                }:
                    raise CanonicalRunStoreError(
                        "run-forked event payload fields are invalid"
                    )
                try:
                    transition_fork = _normalize_fork_provenance(
                        payload["fork_provenance"]
                    )
                except InvalidRequest as exc:
                    raise CanonicalRunStoreError(str(exc)) from exc
                if (
                    transition_fork["forked_from_run_id"] != run["run_id"]
                    or transition_fork["parent_head_event_hash"]
                    != event.get("prev_event_hash")
                    or payload["successor_run_id"] == run["run_id"]
                    or payload["resulting_status"] != "read_only"
                    or event.get("actor_id") != run["owner_id"]
                    or event.get("provenance_class") != "operator"
                    or event.get("caused_by_event_hashes")
                    != [event.get("prev_event_hash")]
                    or event.get("caused_by_artifact_hashes")
                    != [transition_fork["policy_diff_artifact_hash"]]
                    or event_index != len(events) - 1
                ):
                    raise CanonicalRunStoreError(
                        "run-forked event does not bind a terminal predecessor transition"
                    )
                replayed_status = "read_only"
            has_packet = "packet_projection" in payload
            has_postcondition = "postcondition" in payload
            if has_packet != has_postcondition:
                raise CanonicalRunStoreError(
                    "canonical event has a partial projection transition"
                )
            if not has_packet:
                continue
            next_packet = payload["packet_projection"]
            if not isinstance(next_packet, dict):
                raise CanonicalRunStoreError(
                    "canonical event packet projection is invalid"
                )
            packet = dict(next_packet)
            try:
                postcondition = _normalize_postcondition(
                    payload["postcondition"], packet
                )
            except InvalidRequest as exc:
                raise CanonicalRunStoreError(str(exc)) from exc

        if run["status"] != replayed_status:
            raise CanonicalRunStoreError(
                "mutable run status does not match event replay"
            )
        head_event = events[-1]
        packet_hash = canonical_hash(packet)
        if (
            run["head_sequence"] != head_event["sequence"]
            or run["head_event_hash"] != head_event["event_hash"]
            or run["packet_projection_hash"] != packet_hash
            or projection["head_sequence"] != head_event["sequence"]
            or projection["head_event_hash"] != head_event["event_hash"]
            or projection["packet_projection_hash"] != packet_hash
        ):
            raise CanonicalRunStoreError(
                "mutable run or projection head does not match event replay"
            )
        try:
            projected_packet = json.loads(projection["packet_projection_json"])
        except json.JSONDecodeError as exc:
            raise CanonicalRunStoreError(
                "stored packet projection JSON is invalid"
            ) from exc
        if (
            canonical_json(projected_packet)
            != projection["packet_projection_json"]
            or projected_packet != packet
            or bool(projection["active_hold"])
            is not postcondition["active_hold"]
            or projection["governance_status"]
            != postcondition["governance_status"]
            or projection["phase"] != postcondition["phase"]
        ):
            raise CanonicalRunStoreError(
                "mutable run projection does not match event replay"
            )
        snapshot = {
            "effective_policy_hash": str(run["effective_policy_hash"]),
            "head_event_hash": str(run["head_event_hash"]),
            "head_sequence": int(run["head_sequence"]),
            "head_created_at": str(head_event["created_at"]),
            "operator_governance_profile_hash": str(
                run["operator_governance_profile_hash"]
            ),
            "packet_projection": packet,
            "postcondition": postcondition,
            "run_id": str(run["run_id"]),
            "session_governance_snapshot_hash": str(
                run["session_governance_snapshot_hash"]
            ),
            "status": str(run["status"]),
            "system_policy_bindings": stored_bindings,
        }
        if fork_provenance is not None:
            snapshot["fork_provenance"] = deepcopy(fork_provenance)
        return snapshot

    def _verify_fork_predecessor(
        self,
        *,
        child_run: sqlite3.Row,
        child_genesis: Mapping[str, Any],
        fork_provenance: Mapping[str, Any],
    ) -> None:
        parent_id = str(fork_provenance["forked_from_run_id"])
        parent = self._run_row(parent_id)
        rows = self._connection.execute(
            """
            SELECT sequence, event_hash, event_json
            FROM canonical_run_events
            WHERE run_id = ? ORDER BY sequence
            """,
            (parent_id,),
        ).fetchall()
        parent_events: list[dict[str, Any]] = []
        for row in rows:
            try:
                event = json.loads(str(row["event_json"]))
            except json.JSONDecodeError as exc:
                raise CanonicalRunStoreError(
                    "fork predecessor event JSON is invalid"
                ) from exc
            if (
                canonical_json(event) != row["event_json"]
                or event.get("sequence") != row["sequence"]
                or event.get("event_hash") != row["event_hash"]
            ):
                raise CanonicalRunStoreError(
                    "fork predecessor event row is not canonical"
                )
            parent_events.append(event)
        try:
            verify_event_chain(parent_events)
        except ValueError as exc:
            raise CanonicalRunStoreError(str(exc)) from exc
        if len(parent_events) < 2:
            raise CanonicalRunStoreError(
                "fork predecessor terminal transition is missing"
            )
        transition = parent_events[-1]
        payload = transition.get("payload")
        if not isinstance(payload, Mapping):
            raise CanonicalRunStoreError(
                "fork predecessor terminal payload is invalid"
            )
        expected_source = str(fork_provenance["parent_head_event_hash"])
        if (
            parent["status"] != "read_only"
            or parent["head_sequence"] != transition.get("sequence")
            or parent["head_event_hash"] != transition.get("event_hash")
            or transition.get("event_type") != "run_forked"
            or transition.get("prev_event_hash") != expected_source
            or parent_events[-2].get("event_hash") != expected_source
            or payload.get("successor_run_id") != child_run["run_id"]
            or payload.get("fork_provenance") != fork_provenance
            or payload.get("resulting_status") != "read_only"
            or child_genesis.get("caused_by_event_hashes")
            != [transition.get("event_hash")]
        ):
            raise CanonicalRunStoreError(
                "fork successor does not bind the exact terminal predecessor transition"
            )

    def _build_nonmutating_outcome(
        self,
        *,
        actor: ActorContext,
        request: Mapping[str, Any],
        request_hash: str,
        run: sqlite3.Row,
        projection: sqlite3.Row,
        outcome: str,
        reason_code: str,
        detail: str,
    ) -> dict[str, Any]:
        postcondition = {
            "active_hold": bool(projection["active_hold"]),
            "governance_status": str(projection["governance_status"]),
            "packet_projection_hash": str(projection["packet_projection_hash"]),
            "phase": str(projection["phase"]),
        }
        return self._build_outcome(
            request_hash=request_hash,
            intent_hash=str(request["intent_hash"]),
            run=run,
            actor=actor,
            capability=str(request["capability"]),
            capability_id=str(request["capability_id"]),
            idempotency_key=str(request["idempotency_key"]),
            trusted_adapter_intent_id=str(request["trusted_adapter_intent_id"]),
            expected_head_sequence=int(request["expected_head_sequence"]),
            expected_head_event_hash=str(request["expected_head_event_hash"]),
            prior_head_sequence=int(run["head_sequence"]),
            prior_head_event_hash=str(run["head_event_hash"]),
            outcome=outcome,
            event_hash=None,
            artifact_hashes=(),
            resulting_head_sequence=int(run["head_sequence"]),
            resulting_head_event_hash=str(run["head_event_hash"]),
            packet_projection_hash=str(projection["packet_projection_hash"]),
            postcondition=postcondition,
            issued_at=str(request["created_at"]),
            context_manifest_hash=request.get("context_manifest_hash"),
            reason_code=reason_code,
            detail=detail,
        )

    def _invalid_outcome(
        self,
        *,
        actor: ActorContext,
        request: Mapping[str, Any],
        detail: str,
        known_run: sqlite3.Row | None = None,
        known_projection: sqlite3.Row | None = None,
    ) -> AppendResult:
        run_id = request.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise InvalidRequest(detail)
        try:
            run = known_run or self._run_row(run_id)
            projection = known_projection or self._projection_row(run_id)
        except RunNotFound as exc:
            raise InvalidRequest(detail) from exc
        safe_request = _safe_invalid_request(request, run)
        try:
            request_hash = canonical_hash(dict(request))
        except (CanonicalJsonError, TypeError, ValueError):
            request_hash = canonical_hash(safe_request)
        outcome = self._build_nonmutating_outcome(
            actor=actor,
            request=safe_request,
            request_hash=request_hash,
            run=run,
            projection=projection,
            outcome="invalid_request",
            reason_code="invalid_request",
            detail=detail,
        )
        actor_id = actor.actor_id
        idempotency_key = str(safe_request["idempotency_key"])
        intent_hash = str(safe_request["intent_hash"])

        def persist() -> AppendResult:
            replay = self._lookup_outcome(run_id, actor_id, idempotency_key)
            if replay is not None:
                if (
                    replay["request_hash"] == request_hash
                    and replay["intent_hash"] == intent_hash
                ):
                    return AppendResult(
                        json.loads(replay["outcome_json"]), replayed=True
                    )
                raise IdempotencyConflict(
                    "idempotency key was already used for different request bytes"
                )
            self._insert_outcome(
                run_id=run_id,
                actor_id=actor_id,
                idempotency_key=idempotency_key,
                intent_hash=intent_hash,
                request_hash=request_hash,
                outcome=outcome,
            )
            return AppendResult(outcome)

        if self._connection.in_transaction:
            return persist()
        with self._atomic():
            return persist()

    def _build_outcome(
        self,
        *,
        request_hash: str,
        intent_hash: str,
        run: sqlite3.Row,
        actor: ActorContext,
        capability: str,
        capability_id: str,
        idempotency_key: str,
        trusted_adapter_intent_id: str,
        expected_head_sequence: int,
        expected_head_event_hash: str,
        prior_head_sequence: int,
        prior_head_event_hash: str,
        outcome: str,
        event_hash: str | None,
        artifact_hashes: Sequence[str],
        resulting_head_sequence: int,
        resulting_head_event_hash: str,
        packet_projection_hash: str,
        postcondition: Mapping[str, Any],
        issued_at: str,
        context_manifest_hash: Any = None,
        reason_code: str = "",
        detail: str = "",
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "actor_id": actor.actor_id,
            "advanced_head": resulting_head_event_hash != prior_head_event_hash,
            "artifact_hashes": list(artifact_hashes),
            "capability": capability,
            "capability_id": capability_id,
            "effective_policy_hash": str(run["effective_policy_hash"]),
            "expected_head_event_hash": expected_head_event_hash,
            "expected_head_sequence": expected_head_sequence,
            "idempotency_key": idempotency_key,
            "intent_hash": intent_hash,
            "issued_at": issued_at,
            "operator_governance_profile_hash": str(
                run["operator_governance_profile_hash"]
            ),
            "outcome": outcome,
            "packet_projection_hash": packet_projection_hash,
            "policy_bindings": json.loads(run["system_policy_bindings_json"]),
            "postcondition": dict(postcondition),
            "postcondition_hash": canonical_hash(dict(postcondition)),
            "prior_head_event_hash": prior_head_event_hash,
            "prior_head_sequence": prior_head_sequence,
            "provenance_class": actor.provenance_class,
            "request_hash": request_hash,
            "resulting_head_event_hash": resulting_head_event_hash,
            "resulting_head_sequence": resulting_head_sequence,
            "run_id": str(run["run_id"]),
            "session_governance_snapshot_hash": str(
                run["session_governance_snapshot_hash"]
            ),
            "trusted_adapter_intent_id": trusted_adapter_intent_id,
        }
        if event_hash is not None:
            record["event_hash"] = event_hash
        if isinstance(context_manifest_hash, str):
            record["context_manifest_hash"] = context_manifest_hash
        if reason_code:
            record["reason_code"] = reason_code
        if detail:
            record["detail"] = detail
        record["outcome_id"] = canonical_hash(
            {"outcome_record": record, "schema": "canonical_run_store_outcome@0.1.0"}
        )
        return record

    @staticmethod
    def _require_actor_capability(
        actor: ActorContext, capability: str, capability_id: str
    ) -> None:
        try:
            require_capability(actor, capability)
            if actor.capability_id != capability_id:
                raise ValueError("capability_id does not match authenticated context")
        except (PermissionError, TypeError, ValueError) as exc:
            raise InvalidRequest(str(exc)) from exc

    @staticmethod
    def _validator_actor() -> ActorContext:
        return ActorContext(
            actor_id="validator:nepsis.canonical_run_store@0.1.0",
            provenance_class="validator",
            capability_id="internal:canonical_run_store",
            capabilities=frozenset({"append_validator_event"}),
        )


def _validate_action_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise InvalidRequest("action request must be an object")
    fields = set(request)
    missing = _ACTION_REQUEST_REQUIRED - fields
    unknown = fields - _ACTION_REQUEST_REQUIRED - _ACTION_REQUEST_OPTIONAL
    if missing:
        raise InvalidRequest(f"missing request field: {sorted(missing)[0]}")
    if unknown:
        raise InvalidRequest(f"unknown request field: {sorted(unknown)[0]}")
    normalized = dict(request)
    if normalized["action_request_schema_version"] != "nepsis.action_request@0.1.0":
        raise InvalidRequest("unsupported action request schema version")
    capability = normalized["capability"]
    if capability not in _ACTION_CAPABILITIES:
        raise InvalidRequest("capability is not a run append capability")
    for field in (
        "action_type",
        "capability_id",
        "idempotency_key",
        "run_id",
        "trusted_adapter_intent_id",
    ):
        _require_nonempty(normalized[field], field)
    _require_timestamp(normalized["created_at"], "created_at")
    required_hash_fields = (
        "effective_policy_hash",
        "expected_head_event_hash",
        "intent_hash",
        "operator_governance_profile_hash",
        "payload_hash",
        "session_governance_snapshot_hash",
    )
    optional_hash_fields = (
        "context_manifest_hash",
        "external_codex_ref_hash",
        "operator_visible_proposal_hash",
    )
    for field in required_hash_fields + tuple(
        field for field in optional_hash_fields if field in normalized
    ):
        _require_hash(normalized[field], field)
    if not isinstance(normalized["expected_head_sequence"], int) or isinstance(
        normalized["expected_head_sequence"], bool
    ):
        raise InvalidRequest("expected_head_sequence must be an integer")
    if normalized["expected_head_sequence"] < 0:
        raise InvalidRequest("expected_head_sequence must be non-negative")
    payload = normalized["payload"]
    if not isinstance(payload, Mapping):
        raise InvalidRequest("payload must be an object")
    normalized["payload"] = dict(payload)
    if canonical_hash(normalized["payload"]) != normalized["payload_hash"]:
        raise InvalidRequest("payload_hash mismatch")
    artifact_hashes = normalized["artifact_hashes"]
    if not isinstance(artifact_hashes, list) or len(set(artifact_hashes)) != len(
        artifact_hashes
    ):
        raise InvalidRequest("artifact_hashes must be a unique array")
    for value in artifact_hashes:
        _require_hash(value, "artifact_hashes item")
    if capability == "submit_model_candidate":
        for field in (
            "context_manifest_hash",
            "external_codex_ref_hash",
            "operator_visible_proposal_hash",
        ):
            if field not in normalized:
                raise InvalidRequest(f"model candidate requires {field}")
    if capability in _OPERATOR_CAPABILITIES:
        confirmation = normalized.get("operator_confirmation")
        _validate_operator_confirmation(confirmation)
        expected_intent_hash = canonical_hash(
            {
                "action": normalized["action_type"],
                "capability": capability,
                "operator_confirmation": dict(confirmation),
                "payload": normalized["payload"],
            }
        )
        if normalized["intent_hash"] != expected_intent_hash:
            raise InvalidRequest(
                "operator intent_hash must bind action, capability, confirmation, and payload"
            )
    else:
        expected_intent_hash = canonical_hash(
            {
                "action": normalized["action_type"],
                "payload": normalized["payload"],
            }
        )
        if normalized["intent_hash"] != expected_intent_hash:
            raise InvalidRequest("model intent_hash mismatch")
    if capability == "submit_operator_disposition":
        if "operator_visible_proposal_hash" not in normalized:
            raise InvalidRequest(
                "operator disposition requires operator_visible_proposal_hash"
            )
    canonical_json(normalized)
    return normalized


def _normalize_artifact(item: ArtifactInput | Mapping[str, Any]) -> ArtifactInput:
    if isinstance(item, ArtifactInput):
        normalized = item
    elif isinstance(item, Mapping):
        try:
            normalized = ArtifactInput(
                artifact_schema_version=str(item["artifact_schema_version"]),
                roles=tuple(item["roles"]),
                artifact=dict(item["artifact"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRequest("invalid artifact input") from exc
    else:
        raise InvalidRequest("artifact input must be an object")
    if not _VERSION_RE.match(normalized.artifact_schema_version):
        raise InvalidRequest("artifact_schema_version must be a full version")
    if not normalized.roles or not all(
        isinstance(role, str) and role for role in normalized.roles
    ):
        raise InvalidRequest("artifact roles must be non-empty strings")
    if len(set(normalized.roles)) != len(normalized.roles):
        raise InvalidRequest("artifact roles must be unique")
    if not normalized.artifact:
        raise InvalidRequest("artifact body must be non-empty")
    canonical_json(dict(normalized.artifact))
    return normalized


def _validate_admission_decision(decision: AdmissionDecision) -> None:
    if not isinstance(decision, AdmissionDecision):
        raise CanonicalRunStoreError("validator returned an invalid admission decision")
    if decision.admitted:
        if decision.reason_code or decision.detail:
            raise CanonicalRunStoreError("admitted decision cannot contain refusal detail")
        if decision.event_type:
            _require_nonempty(decision.event_type, "event_type")
        if decision.packet_projection is not None:
            canonical_json(dict(decision.packet_projection))
        if decision.postcondition is not None:
            canonical_json(dict(decision.postcondition))
    else:
        _require_nonempty(decision.reason_code, "reason_code")
        _require_nonempty(decision.detail, "detail")
    if decision.validator_binding is not None:
        binding = decision.validator_binding
        if not isinstance(binding, Mapping) or set(binding) != {
            "adapter_version",
            "policy_hash",
            "policy_version",
            "validator_id",
        }:
            raise CanonicalRunStoreError("validator binding fields are invalid")
        _require_nonempty(binding["adapter_version"], "adapter_version")
        _require_hash(binding["policy_hash"], "policy_hash")
        _require_nonempty(binding["policy_version"], "policy_version")
        _require_nonempty(binding["validator_id"], "validator_id")
        canonical_json(dict(binding))


def _normalize_policy_bindings(
    bindings: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not bindings:
        raise InvalidRequest("at least one system policy binding is required")
    normalized: list[dict[str, Any]] = []
    for binding in bindings:
        if not isinstance(binding, Mapping) or set(binding) != {
            "policy_hash",
            "policy_id",
            "policy_version",
        }:
            raise InvalidRequest("invalid policy binding")
        row = dict(binding)
        _require_hash(row["policy_hash"], "policy_hash")
        _require_nonempty(row["policy_id"], "policy_id")
        if not isinstance(row["policy_version"], str) or not _VERSION_RE.match(
            row["policy_version"]
        ):
            raise InvalidRequest("policy_version must be a full version")
        normalized.append(row)
    normalized.sort(
        key=lambda row: (
            str(row["policy_id"]),
            str(row["policy_version"]),
            str(row["policy_hash"]),
        )
    )
    if len({canonical_json(row) for row in normalized}) != len(normalized):
        raise InvalidRequest("system policy bindings must be unique")
    return normalized


def _normalize_fork_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FORK_PROVENANCE_FIELDS:
        raise InvalidRequest("fork provenance fields are invalid")
    normalized = dict(value)
    _require_nonempty(normalized["fork_reason"], "fork_reason")
    _require_nonempty(normalized["forked_from_run_id"], "forked_from_run_id")
    _require_hash(normalized["parent_head_event_hash"], "parent_head_event_hash")
    _require_hash(
        normalized["policy_diff_artifact_hash"], "policy_diff_artifact_hash"
    )
    inherited = normalized["inherited_evidence_root_hashes"]
    if not isinstance(inherited, list) or any(
        not isinstance(item, str) for item in inherited
    ):
        raise InvalidRequest(
            "inherited_evidence_root_hashes must be a hash array"
        )
    for item in inherited:
        _require_hash(item, "inherited_evidence_root_hashes item")
    if len(set(inherited)) != len(inherited):
        raise InvalidRequest("inherited evidence root hashes must be unique")
    normalized["inherited_evidence_root_hashes"] = sorted(inherited)
    canonical_json(normalized)
    return normalized


def _validate_fork_policy_diff_artifact(
    item: ArtifactInput,
    *,
    fork_provenance: Mapping[str, Any],
    parent_effective_policy_hash: str,
    successor_run_id: str,
    successor_effective_policy_hash: str,
    created_at: str,
) -> None:
    if (
        item.artifact_schema_version != _GOVERNANCE_POLICY_DIFF_VERSION
        or item.roles != ("policy_diff",)
    ):
        raise InvalidRequest("fork policy-diff artifact type or roles mismatch")
    artifact = dict(item.artifact)
    if set(artifact) != {
        "changes",
        "child_run_id",
        "fork_reason",
        "from_effective_policy_hash",
        "governance_policy_diff_schema_version",
        "operator_confirmation",
        "parent_run_id",
        "to_effective_policy_hash",
    }:
        raise InvalidRequest("fork policy-diff artifact fields are invalid")
    if artifact["governance_policy_diff_schema_version"] != (
        _GOVERNANCE_POLICY_DIFF_VERSION
    ):
        raise InvalidRequest("fork policy-diff artifact version mismatch")
    expected = {
        "child_run_id": successor_run_id,
        "fork_reason": fork_provenance["fork_reason"],
        "from_effective_policy_hash": parent_effective_policy_hash,
        "parent_run_id": fork_provenance["forked_from_run_id"],
        "to_effective_policy_hash": successor_effective_policy_hash,
    }
    if any(artifact[field] != value for field, value in expected.items()):
        raise InvalidRequest(
            "fork policy-diff artifact does not bind predecessor and successor"
        )
    _validate_operator_confirmation(artifact["operator_confirmation"])
    if artifact["operator_confirmation"]["confirmed_at"] != created_at:
        raise InvalidRequest(
            "fork policy-diff confirmation timestamp must match run creation"
        )
    changes = artifact["changes"]
    if not isinstance(changes, list):
        raise InvalidRequest("fork policy-diff changes must be an array")
    paths: list[str] = []
    for change in changes:
        if not isinstance(change, Mapping) or set(change) != {
            "comparison",
            "field_path",
            "prior_value_hash",
            "resulting_value_hash",
        }:
            raise InvalidRequest("fork policy-diff change fields are invalid")
        if change["comparison"] not in {"replaceable", "tighter"}:
            raise InvalidRequest("fork policy-diff comparison is unsupported")
        _require_nonempty(change["field_path"], "field_path")
        _require_hash(change["prior_value_hash"], "prior_value_hash")
        _require_hash(change["resulting_value_hash"], "resulting_value_hash")
        if change["prior_value_hash"] == change["resulting_value_hash"]:
            raise InvalidRequest("fork policy-diff change is not a change")
        paths.append(str(change["field_path"]))
    if paths != sorted(set(paths)):
        raise InvalidRequest(
            "fork policy-diff changes must be sorted by unique field_path"
        )
    if (parent_effective_policy_hash == successor_effective_policy_hash) != (
        not changes
    ):
        raise InvalidRequest(
            "fork policy-diff changes do not match the effective policy hashes"
        )
    canonical_json(artifact)


def _normalize_postcondition(
    postcondition: Mapping[str, Any], packet_projection: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(postcondition, Mapping) or set(postcondition) != {
        "active_hold",
        "governance_status",
        "packet_projection_hash",
        "phase",
    }:
        raise InvalidRequest("postcondition has invalid fields")
    row = dict(postcondition)
    if not isinstance(row["active_hold"], bool):
        raise InvalidRequest("postcondition active_hold must be boolean")
    _require_nonempty(row["governance_status"], "governance_status")
    _require_nonempty(row["phase"], "phase")
    _require_hash(row["packet_projection_hash"], "packet_projection_hash")
    if row["packet_projection_hash"] != canonical_hash(dict(packet_projection)):
        raise InvalidRequest("postcondition packet_projection_hash mismatch")
    return row


def _validate_operator_confirmation(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "confirmed",
        "confirmed_at",
        "consequence_acknowledged",
        "rationale",
    }:
        raise InvalidRequest("operator capability requires exact confirmation fields")
    if value["confirmed"] is not True or value["consequence_acknowledged"] is not True:
        raise InvalidRequest("operator confirmation must be affirmative")
    _require_timestamp(value["confirmed_at"], "confirmed_at")
    _require_nonempty(value["rationale"], "rationale")


def _safe_invalid_request(
    request: Mapping[str, Any], run: sqlite3.Row
) -> dict[str, Any]:
    """Build a canonical non-mutating identity without trusting bad fields."""

    created_at = request.get("created_at")
    if not isinstance(created_at, str) or not _TIMESTAMP_RE.match(created_at):
        created_at = str(run["created_at"])
    expected_sequence = request.get("expected_head_sequence")
    if not isinstance(expected_sequence, int) or isinstance(expected_sequence, bool):
        expected_sequence = int(run["head_sequence"])
    expected_hash = request.get("expected_head_event_hash")
    if not isinstance(expected_hash, str) or not _HASH_RE.match(expected_hash):
        expected_hash = str(run["head_event_hash"])
    intent_hash = request.get("intent_hash")
    if not isinstance(intent_hash, str) or not _HASH_RE.match(intent_hash):
        intent_hash = canonical_hash(
            {
                "invalid_action_type": str(request.get("action_type", "invalid")),
                "run_id": str(run["run_id"]),
            }
        )
    capability = request.get("capability")
    if capability not in _ACTION_CAPABILITIES:
        capability = "submit_operator_disposition"
    return {
        "capability": capability,
        "capability_id": str(request.get("capability_id") or "invalid"),
        "created_at": created_at,
        "expected_head_event_hash": expected_hash,
        "expected_head_sequence": max(0, expected_sequence),
        "idempotency_key": str(request.get("idempotency_key") or "invalid"),
        "intent_hash": intent_hash,
        "run_id": str(run["run_id"]),
        "trusted_adapter_intent_id": str(
            request.get("trusted_adapter_intent_id") or "invalid"
        ),
    }


def _require_hash(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _HASH_RE.match(value):
        raise InvalidRequest(f"{field} must be a lowercase SHA-256 hash")


def _require_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or not _TIMESTAMP_RE.match(value):
        raise InvalidRequest(f"{field} must use YYYY-MM-DDTHH:MM:SS.mmmZ")


def _require_nonempty(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value:
        raise InvalidRequest(f"{field} must be a non-empty string")


__all__ = [
    "AdmissionDecision",
    "AdmissionValidator",
    "AppendResult",
    "ArtifactInput",
    "CanonicalRunStore",
    "CanonicalRunStoreError",
    "IdempotencyConflict",
    "InvalidRequest",
    "RunNotFound",
]
