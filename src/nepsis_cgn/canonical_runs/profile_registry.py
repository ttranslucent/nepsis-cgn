from __future__ import annotations

import json
from datetime import datetime
import re
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from nepsis_cgn.contracts.canonical_json import canonical_hash, canonical_json
from nepsis_cgn.contracts.governance_profile import (
    GOVERNANCE_COMPARATOR_POLICY_VERSION,
    GovernanceProfileError,
    comparator_policy_hash,
    resolve_override,
    validate_maximum_tolerated_severity,
    validate_rule_override_mode,
)
from nepsis_cgn.contracts.canonical_run import ActorContext, require_capability


PROFILE_SCHEMA_VERSION = "nepsis.operator_governance_profile@0.1.0"
SNAPSHOT_SCHEMA_VERSION = "nepsis.session_governance_snapshot@0.1.0"
SYSTEM_CONSTITUTION_VERSION = "nepsis.system_constitution@0.1.0"

_REPLACEABLE_DEFAULTS = {
    "clarification_budget",
    "proposal_mode",
    "uncertainty_display",
    "unresolved_optional_policy",
}
_TIGHTEN_ONLY_DEFAULTS = {"data_scope", "evidence_floor"}
_TIGHTEN_ONLY_RISK_FIELDS = {
    "evidence_requirement",
    "loss_posture",
    "maximum_tolerated_severity",
    "reversibility_requirement",
}
_PROFILE_REQUIRED_FIELDS = {
    "baseline_constraints",
    "constitution_hash",
    "constitution_version",
    "created_at",
    "created_by",
    "governance_comparator_policy_hash",
    "governance_comparator_policy_version",
    "operator_defaults",
    "operator_governance_profile_schema_version",
    "profile_id",
    "profile_revision",
    "risk_dimensions",
    "ruin_criteria",
}
_PROFILE_OPTIONAL_FIELDS = {"parent_profile_hash", "parent_profile_revision"}
_FORK_PROVENANCE_FIELDS = {
    "fork_reason",
    "forked_from_run_id",
    "inherited_evidence_root_hashes",
    "parent_head_event_hash",
    "policy_diff_artifact_hash",
}
_RISK_DIMENSIONS = {
    "human_harm",
    "data_security_privacy",
    "legal_authority_commitment",
    "operational_recoverability",
    "resource_financial_loss",
    "epistemic_integrity",
}
_SYSTEM_CONSTITUTION = {
    "baseline_constraints": [
        {
            "action_on_breach": "block",
            "applicability": "All governed actions.",
            "constraint_id": "audit_required",
            "evaluability_type": "deterministic_boolean",
            "label": "Audit required",
            "override_mode": "locked",
            "rationale": "Canonical history must remain reconstructable.",
            "source_refs": ["system_constitution"],
            "strength": "hard",
        }
    ],
    "constitution_version": SYSTEM_CONSTITUTION_VERSION,
    "risk_dimensions": [
        {
            "default_response": "block",
            "dimension": "data_security_privacy",
            "evaluability_type": "ordinal_evidence",
            "evidence_requirement": "elevated",
            "loss_posture": "downside_weighted",
            "maximum_tolerated_severity": 2,
            "reversibility_requirement": "required",
        },
        {
            "default_response": "block",
            "dimension": "epistemic_integrity",
            "evaluability_type": "ordinal_evidence",
            "evidence_requirement": "standard",
            "loss_posture": "balanced",
            "maximum_tolerated_severity": 3,
            "reversibility_requirement": "none",
        },
        {
            "default_response": "still",
            "dimension": "human_harm",
            "evaluability_type": "ordinal_evidence",
            "evidence_requirement": "elevated",
            "loss_posture": "downside_weighted",
            "maximum_tolerated_severity": 2,
            "reversibility_requirement": "preferred",
        },
        {
            "default_response": "still",
            "dimension": "legal_authority_commitment",
            "evaluability_type": "operator_attestation",
            "evidence_requirement": "strict",
            "loss_posture": "ruin_averse",
            "maximum_tolerated_severity": 2,
            "reversibility_requirement": "required",
        },
        {
            "default_response": "zeroback",
            "dimension": "operational_recoverability",
            "evaluability_type": "deterministic_boolean",
            "evidence_requirement": "elevated",
            "loss_posture": "downside_weighted",
            "maximum_tolerated_severity": 2,
            "reversibility_requirement": "required",
        },
        {
            "default_response": "still",
            "dimension": "resource_financial_loss",
            "evaluability_type": "ordinal_evidence",
            "evidence_requirement": "standard",
            "loss_posture": "balanced",
            "maximum_tolerated_severity": 3,
            "reversibility_requirement": "preferred",
        },
    ],
    "ruin_criteria": [
        {
            "actions_made_inadmissible": ["decision_commit"],
            "applicability": "Canonical provenance is unavailable.",
            "category": "audit_loss",
            "evaluability_type": "deterministic_boolean",
            "override_mode": "locked",
            "protected": True,
            "rationale": "Audit loss invalidates the governed result.",
            "response": "block",
            "ruin_id": "loss_of_audit",
            "source_refs": ["system_constitution"],
            "unwanted_outcome": "Unable to determine what became true.",
            "waivable": False,
        }
    ],
    "system_governance_constitution_schema_version": (
        SYSTEM_CONSTITUTION_VERSION
    ),
}
SYSTEM_CONSTITUTION_HASH = canonical_hash(_SYSTEM_CONSTITUTION)
_CONSTITUTIONAL_DATA_SCOPES = {
    "operator_cleared_non_phi": frozenset({"operator_cleared_non_phi"})
}
_SYSTEM_RISKS_BY_DIMENSION = {
    row["dimension"]: row for row in _SYSTEM_CONSTITUTION["risk_dimensions"]
}
_SYSTEM_CONSTRAINTS_BY_ID = {
    row["constraint_id"]: row
    for row in _SYSTEM_CONSTITUTION["baseline_constraints"]
}
_SYSTEM_RUINS_BY_ID = {
    row["ruin_id"]: row for row in _SYSTEM_CONSTITUTION["ruin_criteria"]
}
_RANKS = {
    "evidence_requirement": {"standard": 0, "elevated": 1, "strict": 2},
    "loss_posture": {"balanced": 0, "downside_weighted": 1, "ruin_averse": 2},
    "reversibility_requirement": {"none": 0, "preferred": 1, "required": 2},
}
_EVALUABILITY_TYPES = {
    "deterministic_boolean",
    "ordinal_evidence",
    "operator_attestation",
}
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^nepsis\.[a-z0-9_.-]+@[0-9]+\.[0-9]+\.[0-9]+$")


class ProfileRegistryError(ValueError):
    """Raised when a registry operation cannot be admitted safely."""


class ProfileHeadConflict(ProfileRegistryError):
    """Raised when the expected immutable profile head is stale."""


class IdempotencyConflict(ProfileRegistryError):
    """Raised when an idempotency key is reused for another intent."""


class GovernanceProfileRegistry:
    """Append-only SQLite registry for immutable operator profile revisions."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        data_scopes: Mapping[str, frozenset[str]] | None = None,
    ) -> None:
        self._db = connection
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.execute("PRAGMA synchronous = FULL")
        database_path = str(self._db.execute("PRAGMA database_list").fetchone()[2])
        if database_path:
            self._db.execute("PRAGMA journal_mode = WAL")
        configured_data_scopes = {
            name: frozenset(values)
            for name, values in (data_scopes or _CONSTITUTIONAL_DATA_SCOPES).items()
        }
        if configured_data_scopes != _CONSTITUTIONAL_DATA_SCOPES:
            raise ProfileRegistryError(
                "data scopes must match the constitutional remote-data boundary"
            )
        self._data_scopes = dict(_CONSTITUTIONAL_DATA_SCOPES)
        self._initialize_schema()

    @classmethod
    def in_memory(
        cls, *, data_scopes: Mapping[str, frozenset[str]] | None = None
    ) -> GovernanceProfileRegistry:
        return cls(
            sqlite3.connect(":memory:", check_same_thread=False),
            data_scopes=data_scopes,
        )

    @classmethod
    def open(
        cls,
        path: str | Path,
        *,
        data_scopes: Mapping[str, frozenset[str]] | None = None,
    ) -> GovernanceProfileRegistry:
        resolved = Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        return cls(
            sqlite3.connect(str(resolved), check_same_thread=False),
            data_scopes=data_scopes,
        )

    def close(self) -> None:
        self._db.close()

    def create_revision(
        self,
        profile: Mapping[str, Any],
        *,
        actor: ActorContext,
        expected_head_revision: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        _require_operator(actor, "revise_operator_profile")
        profile_value = deepcopy(dict(profile))
        self._validate_profile(profile_value, actor=actor)
        profile_id = _nonempty_string(profile_value.get("profile_id"), "profile_id")
        intent = {
            "operation": "create_revision",
            "operator_id": actor.actor_id,
            "profile": profile_value,
            "expected_head_revision": expected_head_revision,
        }
        intent_hash = canonical_hash(intent)

        with self._write_transaction():
            prior = self._idempotent_result(idempotency_key, intent_hash)
            if prior is not None:
                return prior
            head = self._head(profile_id)
            actual_head_revision = head[0] if head else 0
            if actual_head_revision != expected_head_revision:
                raise ProfileHeadConflict(
                    f"expected profile head {expected_head_revision}, found "
                    f"{actual_head_revision}"
                )
            revision = _integer(profile_value.get("profile_revision"), "profile_revision")
            if revision != expected_head_revision + 1:
                raise ProfileRegistryError(
                    "profile_revision must be exactly one greater than expected head"
                )
            self._validate_parent(profile_value, head=head)

            profile_hash = canonical_hash(profile_value)
            profile_json = canonical_json(profile_value)
            self._db.execute(
                """
                INSERT INTO governance_profile_revisions (
                    profile_id, profile_revision, operator_id, profile_hash,
                    profile_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    revision,
                    actor.actor_id,
                    profile_hash,
                    profile_json,
                    profile_value["created_at"],
                ),
            )
            self._db.execute(
                """
                INSERT INTO governance_profile_heads (
                    profile_id, head_revision, head_hash
                ) VALUES (?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    head_revision = excluded.head_revision,
                    head_hash = excluded.head_hash
                """,
                (profile_id, revision, profile_hash),
            )
            event_sequence = self._append_lifecycle_event(
                profile_id=profile_id,
                revision=revision,
                operator_id=actor.actor_id,
                event_type="revision_created",
                resulting_state="draft",
                occurred_at=profile_value["created_at"],
                request_idempotency_key=idempotency_key,
            )
            self._db.execute(
                """
                INSERT INTO governance_profile_projection (
                    profile_id, profile_revision, operator_id, state,
                    last_event_sequence
                ) VALUES (?, ?, ?, 'draft', ?)
                """,
                (profile_id, revision, actor.actor_id, event_sequence),
            )
            result = {
                "outcome": "created",
                "profile_id": profile_id,
                "profile_revision": revision,
                "profile_hash": profile_hash,
                "state": "draft",
                "head_revision": revision,
                "event_sequence": event_sequence,
            }
            self._record_idempotency(idempotency_key, intent_hash, result)
            return result

    def activate(
        self,
        profile_id: str,
        revision: int,
        *,
        actor: ActorContext,
        expected_head_revision: int,
        idempotency_key: str,
        occurred_at: str,
    ) -> dict[str, Any]:
        return self._lifecycle_change(
            action="activate",
            profile_id=profile_id,
            revision=revision,
            actor=actor,
            expected_head_revision=expected_head_revision,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
        )

    def revoke(
        self,
        profile_id: str,
        revision: int,
        *,
        actor: ActorContext,
        expected_head_revision: int,
        idempotency_key: str,
        occurred_at: str,
    ) -> dict[str, Any]:
        return self._lifecycle_change(
            action="revoke",
            profile_id=profile_id,
            revision=revision,
            actor=actor,
            expected_head_revision=expected_head_revision,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
        )

    def active_profile(self, *, operator_id: str) -> dict[str, Any] | None:
        row = self._db.execute(
            """
            SELECT r.profile_id, r.profile_revision, r.profile_hash, r.profile_json
            FROM governance_profile_projection AS p
            JOIN governance_profile_revisions AS r
              ON r.profile_id = p.profile_id
             AND r.profile_revision = p.profile_revision
            WHERE p.operator_id = ? AND p.state = 'active'
            """,
            (operator_id,),
        ).fetchone()
        return self._revision_result(row) if row else None

    def get_revision(self, profile_id: str, revision: int) -> dict[str, Any]:
        row = self._db.execute(
            """
            SELECT profile_id, profile_revision, profile_hash, profile_json
            FROM governance_profile_revisions
            WHERE profile_id = ? AND profile_revision = ?
            """,
            (profile_id, revision),
        ).fetchone()
        if row is None:
            raise ProfileRegistryError("profile revision not found")
        return self._revision_result(row)

    def lifecycle_state(self, profile_id: str, revision: int) -> str:
        row = self._db.execute(
            """
            SELECT state FROM governance_profile_projection
            WHERE profile_id = ? AND profile_revision = ?
            """,
            (profile_id, revision),
        ).fetchone()
        if row is None:
            raise ProfileRegistryError("profile revision not found")
        return str(row["state"])

    def get_session_snapshot_result(self, run_id: str) -> dict[str, Any]:
        row = self._db.execute(
            """
            SELECT result_json FROM governance_session_snapshot_results
            WHERE run_id = ?
            """,
            (_nonempty_string(run_id, "run_id"),),
        ).fetchone()
        if row is None:
            raise ProfileRegistryError("session governance snapshot not found")
        return json.loads(row["result_json"])

    def build_session_snapshot(
        self,
        profile_id: str,
        *,
        run_id: str,
        overrides: Sequence[Mapping[str, Any]],
        created_at: str,
        actor: ActorContext,
        session_started: bool = False,
        fork_provenance: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        _require_operator(actor, "create_run")
        _nonempty_string(profile_id, "profile_id")
        _nonempty_string(run_id, "run_id")
        normalized_fork = (
            _normalize_fork_provenance(fork_provenance)
            if fork_provenance is not None
            else None
        )
        if normalized_fork is not None and normalized_fork[
            "forked_from_run_id"
        ] == run_id:
            raise ProfileRegistryError(
                "fork predecessor and successor run_ids must differ"
            )
        derivation_intent = {
            "profile_id": profile_id,
            "run_id": run_id,
            "overrides": [deepcopy(dict(item)) for item in overrides],
            "created_at": created_at,
            "operator_id": actor.actor_id,
            "session_started": session_started,
        }
        if normalized_fork is not None:
            derivation_intent["fork_provenance"] = normalized_fork
        derivation_hash = canonical_hash(derivation_intent)

        with self._write_transaction():
            existing = self._db.execute(
                """
                SELECT derivation_hash, result_json
                FROM governance_session_snapshot_results WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if existing is not None:
                if existing["derivation_hash"] != derivation_hash:
                    raise IdempotencyConflict(
                        "run_id is already bound to another snapshot derivation"
                    )
                return json.loads(existing["result_json"])

            active = self.active_profile(operator_id=actor.actor_id)
            if active is None or active["profile_id"] != profile_id:
                raise ProfileRegistryError("requested profile is not active for operator")
            profile = active["profile"]
            effective_policy = {
                "constitution_hash": profile["constitution_hash"],
                "constitution_version": profile["constitution_version"],
                "operator_defaults": deepcopy(profile["operator_defaults"]),
                "baseline_constraints": deepcopy(profile["baseline_constraints"]),
                "risk_dimensions": deepcopy(profile["risk_dimensions"]),
                "ruin_criteria": deepcopy(profile["ruin_criteria"]),
            }
            source_annotations = _profile_source_annotations(
                profile, profile_hash=active["profile_hash"]
            )

            decisions: list[dict[str, Any]] = []
            validated_overrides: list[dict[str, Any]] = []
            for raw_override in overrides:
                override = deepcopy(dict(raw_override))
                decision, location = self._evaluate_override(
                    effective_policy,
                    override,
                    session_started=session_started,
                )
                decisions.append(decision)
                if decision["outcome"] == "accepted":
                    container, field = location
                    container[field] = deepcopy(override["proposed_value"])
                    override_hash = canonical_hash(override["proposed_value"])
                    validated_overrides.append(
                        {
                            "override_id": override["override_id"],
                            "field_path": override["field_path"],
                            "comparison": decision["comparison"],
                            "created_at": created_at,
                            "operator_id": actor.actor_id,
                            "proposed_value_artifact_hash": override_hash,
                            "rationale": override["rationale"],
                        }
                    )
                    source_annotations = [
                        row
                        for row in source_annotations
                        if row["field_path"] != override["field_path"]
                    ]
                    source_annotations.append(
                        {
                            "field_path": override["field_path"],
                            "source": "session_override",
                            "source_hash": canonical_hash(override),
                        }
                    )

            outcome = _override_outcome(decisions)
            if outcome != "accepted":
                result = {
                    "outcome": outcome,
                    "profile_id": profile_id,
                    "profile_revision": active["profile_revision"],
                    "override_decisions": decisions,
                }
                self._store_snapshot_result(run_id, derivation_hash, result)
                return result

            self._validate_effective_policy(effective_policy)
            source_annotations.sort(key=lambda row: row["field_path"])
            validated_overrides.sort(key=lambda row: row["override_id"])
            effective_policy_hash = canonical_hash(effective_policy)
            snapshot = {
                "session_governance_snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
                "snapshot_id": f"snapshot_{run_id}",
                "run_id": run_id,
                "created_at": created_at,
                "created_by": "validator:nepsis_cgn.profile_registry",
                "constitution_version": profile["constitution_version"],
                "constitution_hash": profile["constitution_hash"],
                "governance_comparator_policy_version": (
                    GOVERNANCE_COMPARATOR_POLICY_VERSION
                ),
                "governance_comparator_policy_hash": comparator_policy_hash(),
                "profile_id": profile_id,
                "profile_revision": active["profile_revision"],
                "operator_governance_profile_hash": active["profile_hash"],
                "effective_policy": effective_policy,
                "effective_policy_hash": effective_policy_hash,
                "source_annotations": source_annotations,
                "validated_overrides": validated_overrides,
            }
            if normalized_fork is not None:
                snapshot["fork_provenance"] = normalized_fork
            result = {
                "outcome": "accepted",
                "snapshot_hash": canonical_hash(snapshot),
                "snapshot": snapshot,
                "override_decisions": decisions,
            }
            self._store_snapshot_result(run_id, derivation_hash, result)
            return result

    def _lifecycle_change(
        self,
        *,
        action: str,
        profile_id: str,
        revision: int,
        actor: ActorContext,
        expected_head_revision: int,
        idempotency_key: str,
        occurred_at: str,
    ) -> dict[str, Any]:
        _require_operator(actor, "revise_operator_profile")
        intent = {
            "operation": action,
            "profile_id": profile_id,
            "profile_revision": revision,
            "operator_id": actor.actor_id,
            "expected_head_revision": expected_head_revision,
            "occurred_at": occurred_at,
        }
        intent_hash = canonical_hash(intent)
        with self._write_transaction():
            prior = self._idempotent_result(idempotency_key, intent_hash)
            if prior is not None:
                return prior
            head = self._head(profile_id)
            actual_head_revision = head[0] if head else 0
            if actual_head_revision != expected_head_revision:
                raise ProfileHeadConflict(
                    f"expected profile head {expected_head_revision}, found "
                    f"{actual_head_revision}"
                )
            row = self._projection_row(profile_id, revision)
            if row["operator_id"] != actor.actor_id:
                raise ProfileRegistryError("operator does not own profile revision")

            event_sequences: list[int] = []
            if action == "activate":
                if revision != actual_head_revision:
                    raise ProfileHeadConflict(
                        "only the current profile head revision can be activated"
                    )
                if row["state"] != "draft":
                    raise ProfileRegistryError("only a draft revision can be activated")
                active = self._db.execute(
                    """
                    SELECT profile_id, profile_revision
                    FROM governance_profile_projection
                    WHERE operator_id = ? AND state = 'active'
                    """,
                    (actor.actor_id,),
                ).fetchone()
                if active is not None:
                    sequence = self._append_lifecycle_event(
                        profile_id=active["profile_id"],
                        revision=active["profile_revision"],
                        operator_id=actor.actor_id,
                        event_type="superseded",
                        resulting_state="superseded",
                        occurred_at=occurred_at,
                        request_idempotency_key=idempotency_key,
                    )
                    self._set_projection_state(
                        active["profile_id"],
                        active["profile_revision"],
                        "superseded",
                        sequence,
                    )
                    event_sequences.append(sequence)
                sequence = self._append_lifecycle_event(
                    profile_id=profile_id,
                    revision=revision,
                    operator_id=actor.actor_id,
                    event_type="activated",
                    resulting_state="active",
                    occurred_at=occurred_at,
                    request_idempotency_key=idempotency_key,
                )
                self._set_projection_state(profile_id, revision, "active", sequence)
                event_sequences.append(sequence)
                state = "active"
            elif action == "revoke":
                if row["state"] == "revoked":
                    raise ProfileRegistryError("profile revision is already revoked")
                sequence = self._append_lifecycle_event(
                    profile_id=profile_id,
                    revision=revision,
                    operator_id=actor.actor_id,
                    event_type="revoked",
                    resulting_state="revoked",
                    occurred_at=occurred_at,
                    request_idempotency_key=idempotency_key,
                )
                self._set_projection_state(profile_id, revision, "revoked", sequence)
                event_sequences.append(sequence)
                state = "revoked"
            else:
                raise ProfileRegistryError("unsupported lifecycle action")

            result = {
                "outcome": action + "d",
                "profile_id": profile_id,
                "profile_revision": revision,
                "state": state,
                "head_revision": actual_head_revision,
                "event_sequences": event_sequences,
            }
            self._record_idempotency(idempotency_key, intent_hash, result)
            return result

    def _evaluate_override(
        self,
        effective_policy: dict[str, Any],
        override: dict[str, Any],
        *,
        session_started: bool,
    ) -> tuple[dict[str, Any], tuple[dict[str, Any], str]]:
        _nonempty_string(override.get("override_id"), "override_id")
        field_path = _nonempty_string(override.get("field_path"), "field_path")
        _nonempty_string(override.get("rationale"), "rationale")
        if "proposed_value" not in override:
            raise ProfileRegistryError("override proposed_value is required")
        container, field, mode, comparator_field = _override_location(
            effective_policy, field_path
        )
        inherited = container[field]
        proposed = override["proposed_value"]
        try:
            resolved = resolve_override(
                mode=mode,
                field=comparator_field,
                inherited=inherited,
                proposed=proposed,
                session_started=session_started,
                data_scopes=self._data_scopes,
            )
        except GovernanceProfileError as exc:
            raise ProfileRegistryError(str(exc)) from exc
        if resolved.outcome == "accepted":
            candidate_policy = deepcopy(effective_policy)
            candidate_container, candidate_field, _, _ = _override_location(
                candidate_policy, field_path
            )
            candidate_container[candidate_field] = deepcopy(proposed)
            try:
                self._validate_effective_policy(candidate_policy)
            except ProfileRegistryError as exc:
                return (
                    {
                        "override_id": override["override_id"],
                        "field_path": field_path,
                        "outcome": "refused",
                        "comparison": resolved.comparison,
                        "reason": f"invalid effective policy: {exc}",
                    },
                    (container, field),
                )
        return (
            {
                "override_id": override["override_id"],
                "field_path": field_path,
                "outcome": resolved.outcome,
                "comparison": resolved.comparison,
                "reason": resolved.reason,
            },
            (container, field),
        )

    def _validate_profile(
        self, profile: dict[str, Any], *, actor: ActorContext
    ) -> None:
        _closed_fields(
            profile,
            required=_PROFILE_REQUIRED_FIELDS,
            optional=_PROFILE_OPTIONAL_FIELDS,
            label="governance profile",
        )
        if profile.get("operator_governance_profile_schema_version") != (
            PROFILE_SCHEMA_VERSION
        ):
            raise ProfileRegistryError("unsupported governance profile schema")
        if profile.get("governance_comparator_policy_version") != (
            GOVERNANCE_COMPARATOR_POLICY_VERSION
        ):
            raise ProfileRegistryError("governance comparator version mismatch")
        if profile.get("governance_comparator_policy_hash") != comparator_policy_hash():
            raise ProfileRegistryError("governance comparator hash mismatch")
        if profile.get("created_by") != actor.actor_id:
            raise ProfileRegistryError("profile created_by must match operator actor")
        _nonempty_string(profile.get("profile_id"), "profile_id")
        revision = _integer(profile.get("profile_revision"), "profile_revision")
        if revision < 1:
            raise ProfileRegistryError("profile_revision must be positive")
        if profile.get("constitution_hash") != SYSTEM_CONSTITUTION_HASH:
            raise ProfileRegistryError(
                "constitution_hash must match the system constitution"
            )
        if profile.get("constitution_version") != SYSTEM_CONSTITUTION_VERSION:
            raise ProfileRegistryError(
                "constitution_version must match the system constitution"
            )
        _timestamp(profile.get("created_at"), "created_at")
        if ("parent_profile_hash" in profile) != (
            "parent_profile_revision" in profile
        ):
            raise ProfileRegistryError("profile parent fields must appear together")
        if "parent_profile_hash" in profile:
            _hash(profile["parent_profile_hash"], "parent_profile_hash")
            parent_revision = _integer(
                profile["parent_profile_revision"], "parent_profile_revision"
            )
            if parent_revision < 1:
                raise ProfileRegistryError("parent_profile_revision must be positive")
        self._validate_effective_policy(profile)
        try:
            canonical_json(profile)
        except ValueError as exc:
            raise ProfileRegistryError(f"profile is not neutral canonical JSON: {exc}") from exc

    def _validate_effective_policy(self, policy: Mapping[str, Any]) -> None:
        defaults = policy.get("operator_defaults")
        if not isinstance(defaults, Mapping):
            raise ProfileRegistryError("operator_defaults must be an object")
        _closed_fields(
            defaults,
            required={
                "clarification_budget",
                "data_scope",
                "evidence_floor",
                "proposal_mode",
                "uncertainty_display",
                "unresolved_optional_policy",
            },
            optional=set(),
            label="operator_defaults",
        )
        budget = _integer(defaults.get("clarification_budget"), "clarification_budget")
        if not 0 <= budget <= 5:
            raise ProfileRegistryError("clarification_budget must be 0 through 5")
        data_scope = _nonempty_string(defaults.get("data_scope"), "data_scope")
        if data_scope not in self._data_scopes:
            raise ProfileRegistryError(
                "data_scope exceeds the constitutional remote-data boundary"
            )
        _enum(
            defaults.get("evidence_floor"),
            "evidence_floor",
            {"operator_attestation", "one_source", "corroborated"},
        )
        _enum(
            defaults.get("proposal_mode"),
            "proposal_mode",
            {"one_at_a_time", "grouped_low_risk"},
        )
        _enum(
            defaults.get("uncertainty_display"),
            "uncertainty_display",
            {"ranges", "bands", "narrative_with_status"},
        )
        _enum(
            defaults.get("unresolved_optional_policy"),
            "unresolved_optional_policy",
            {"hold", "explicitly_defer"},
        )

        risks = policy.get("risk_dimensions")
        if not isinstance(risks, list) or len(risks) != len(_RISK_DIMENSIONS):
            raise ProfileRegistryError(
                "risk_dimensions must contain exactly six rows"
            )
        dimensions: set[str] = set()
        for risk in risks:
            if not isinstance(risk, Mapping):
                raise ProfileRegistryError("risk dimension must be an object")
            _closed_fields(
                risk,
                required={
                    "default_response",
                    "dimension",
                    "evaluability_type",
                    "evidence_requirement",
                    "loss_posture",
                    "maximum_tolerated_severity",
                    "reversibility_requirement",
                },
                optional=set(),
                label="risk dimension",
            )
            dimension = _enum(
                risk.get("dimension"), "risk dimension", _RISK_DIMENSIONS
            )
            if dimension in dimensions:
                raise ProfileRegistryError("risk dimensions must be unique")
            dimensions.add(dimension)
            try:
                validate_maximum_tolerated_severity(
                    risk.get("maximum_tolerated_severity")
                )
            except GovernanceProfileError as exc:
                raise ProfileRegistryError(str(exc)) from exc
            _enum(
                risk.get("loss_posture"),
                "loss_posture",
                {"balanced", "downside_weighted", "ruin_averse"},
            )
            _enum(
                risk.get("evidence_requirement"),
                "evidence_requirement",
                {"standard", "elevated", "strict"},
            )
            _enum(
                risk.get("reversibility_requirement"),
                "reversibility_requirement",
                {"none", "preferred", "required"},
            )
            _enum(
                risk.get("evaluability_type"),
                "evaluability_type",
                _EVALUABILITY_TYPES,
            )
            _enum(
                risk.get("default_response"),
                "default_response",
                {"block", "still", "zeroback"},
            )
        if dimensions != _RISK_DIMENSIONS:
            raise ProfileRegistryError(
                "risk_dimensions must contain every system dimension exactly once"
            )

        constraints = policy.get("baseline_constraints")
        if not isinstance(constraints, list):
            raise ProfileRegistryError("baseline_constraints must be a list")
        constraint_ids: set[str] = set()
        for constraint in constraints:
            if not isinstance(constraint, Mapping):
                raise ProfileRegistryError("baseline constraint must be an object")
            _closed_fields(
                constraint,
                required={
                    "action_on_breach",
                    "applicability",
                    "constraint_id",
                    "evaluability_type",
                    "label",
                    "override_mode",
                    "rationale",
                    "source_refs",
                    "strength",
                },
                optional=set(),
                label="baseline constraint",
            )
            identifier = _nonempty_string(
                constraint.get("constraint_id"), "constraint_id"
            )
            if identifier in constraint_ids:
                raise ProfileRegistryError("constraint IDs must be unique")
            constraint_ids.add(identifier)
            try:
                validate_rule_override_mode(
                    strength=str(constraint.get("strength")),
                    override_mode=str(constraint.get("override_mode")),
                )
            except GovernanceProfileError as exc:
                raise ProfileRegistryError(str(exc)) from exc
            for field in ("label", "applicability", "rationale"):
                _nonempty_string(constraint.get(field), field)
            _enum(
                constraint.get("evaluability_type"),
                "evaluability_type",
                _EVALUABILITY_TYPES,
            )
            _enum(
                constraint.get("action_on_breach"),
                "action_on_breach",
                {"block", "still", "zeroback"},
            )
            _string_array(constraint.get("source_refs"), "source_refs")

        ruins = policy.get("ruin_criteria")
        if not isinstance(ruins, list) or not ruins:
            raise ProfileRegistryError("ruin_criteria must be a non-empty list")
        ruin_ids: set[str] = set()
        for ruin in ruins:
            if not isinstance(ruin, Mapping):
                raise ProfileRegistryError("ruin criterion must be an object")
            _closed_fields(
                ruin,
                required={
                    "actions_made_inadmissible",
                    "applicability",
                    "category",
                    "evaluability_type",
                    "override_mode",
                    "protected",
                    "rationale",
                    "response",
                    "ruin_id",
                    "source_refs",
                    "unwanted_outcome",
                    "waivable",
                },
                optional=set(),
                label="ruin criterion",
            )
            ruin_id = _nonempty_string(ruin.get("ruin_id"), "ruin_id")
            if ruin_id in ruin_ids:
                raise ProfileRegistryError("ruin IDs must be unique")
            ruin_ids.add(ruin_id)
            if ruin.get("protected") is not True:
                raise ProfileRegistryError("all ruin criteria must be protected")
            if ruin.get("waivable") is not False:
                raise ProfileRegistryError("all ruin criteria must be non-waivable")
            if ruin.get("override_mode") != "locked":
                raise ProfileRegistryError("all ruin criteria must be locked")
            for field in (
                "category",
                "unwanted_outcome",
                "applicability",
                "rationale",
            ):
                _nonempty_string(ruin.get(field), field)
            _enum(
                ruin.get("evaluability_type"),
                "evaluability_type",
                _EVALUABILITY_TYPES,
            )
            _enum(
                ruin.get("response"),
                "response",
                {"block", "still", "zeroback"},
            )
            _string_array(ruin.get("actions_made_inadmissible"), "actions")
            _string_array(ruin.get("source_refs"), "source_refs")
        _validate_system_constitution_floor(
            risks=risks,
            constraints=constraints,
            ruins=ruins,
        )

    def _validate_parent(
        self,
        profile: Mapping[str, Any],
        *,
        head: tuple[int, str] | None,
    ) -> None:
        if head is None:
            if "parent_profile_revision" in profile or "parent_profile_hash" in profile:
                raise ProfileRegistryError("first revision cannot declare a parent")
            return
        if profile.get("parent_profile_revision") != head[0]:
            raise ProfileRegistryError("parent_profile_revision does not match head")
        if profile.get("parent_profile_hash") != head[1]:
            raise ProfileRegistryError("parent_profile_hash does not match head")

    def _head(self, profile_id: str) -> tuple[int, str] | None:
        row = self._db.execute(
            """
            SELECT head_revision, head_hash FROM governance_profile_heads
            WHERE profile_id = ?
            """,
            (profile_id,),
        ).fetchone()
        return (int(row["head_revision"]), str(row["head_hash"])) if row else None

    def _projection_row(self, profile_id: str, revision: int) -> sqlite3.Row:
        row = self._db.execute(
            """
            SELECT operator_id, state FROM governance_profile_projection
            WHERE profile_id = ? AND profile_revision = ?
            """,
            (profile_id, revision),
        ).fetchone()
        if row is None:
            raise ProfileRegistryError("profile revision not found")
        return row

    def _append_lifecycle_event(
        self,
        *,
        profile_id: str,
        revision: int,
        operator_id: str,
        event_type: str,
        resulting_state: str,
        occurred_at: str,
        request_idempotency_key: str,
    ) -> int:
        event = {
            "profile_id": profile_id,
            "profile_revision": revision,
            "operator_id": operator_id,
            "event_type": event_type,
            "resulting_state": resulting_state,
            "occurred_at": occurred_at,
            "request_idempotency_key": request_idempotency_key,
        }
        cursor = self._db.execute(
            """
            INSERT INTO governance_profile_lifecycle_events (
                profile_id, profile_revision, operator_id, event_type,
                resulting_state, occurred_at, request_idempotency_key,
                event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                revision,
                operator_id,
                event_type,
                resulting_state,
                occurred_at,
                request_idempotency_key,
                canonical_hash(event),
            ),
        )
        return int(cursor.lastrowid)

    def _set_projection_state(
        self, profile_id: str, revision: int, state: str, sequence: int
    ) -> None:
        self._db.execute(
            """
            UPDATE governance_profile_projection
            SET state = ?, last_event_sequence = ?
            WHERE profile_id = ? AND profile_revision = ?
            """,
            (state, sequence, profile_id, revision),
        )

    def _idempotent_result(
        self, idempotency_key: str, intent_hash: str
    ) -> dict[str, Any] | None:
        _nonempty_string(idempotency_key, "idempotency_key")
        row = self._db.execute(
            """
            SELECT intent_hash, result_json FROM governance_profile_idempotency
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        if row["intent_hash"] != intent_hash:
            raise IdempotencyConflict("idempotency key reused with another intent")
        return json.loads(row["result_json"])

    def _record_idempotency(
        self, idempotency_key: str, intent_hash: str, result: Mapping[str, Any]
    ) -> None:
        self._db.execute(
            """
            INSERT INTO governance_profile_idempotency (
                idempotency_key, intent_hash, result_json
            ) VALUES (?, ?, ?)
            """,
            (idempotency_key, intent_hash, canonical_json(dict(result))),
        )

    def _store_snapshot_result(
        self, run_id: str, derivation_hash: str, result: Mapping[str, Any]
    ) -> None:
        self._db.execute(
            """
            INSERT INTO governance_session_snapshot_results (
                run_id, derivation_hash, result_json
            ) VALUES (?, ?, ?)
            """,
            (run_id, derivation_hash, canonical_json(dict(result))),
        )

    def _revision_result(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "profile_id": str(row["profile_id"]),
            "profile_revision": int(row["profile_revision"]),
            "profile_hash": str(row["profile_hash"]),
            "profile": json.loads(row["profile_json"]),
        }

    @contextmanager
    def _write_transaction(self) -> Iterator[None]:
        if self._db.in_transaction:
            raise ProfileRegistryError("registry requires an outer transaction boundary")
        self._db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._db.rollback()
            raise
        else:
            self._db.commit()

    def _initialize_schema(self) -> None:
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS governance_profile_revisions (
                profile_id TEXT NOT NULL,
                profile_revision INTEGER NOT NULL CHECK(profile_revision >= 1),
                operator_id TEXT NOT NULL,
                profile_hash TEXT NOT NULL UNIQUE,
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(profile_id, profile_revision)
            );

            CREATE TABLE IF NOT EXISTS governance_profile_heads (
                profile_id TEXT PRIMARY KEY,
                head_revision INTEGER NOT NULL,
                head_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS governance_profile_lifecycle_events (
                event_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id TEXT NOT NULL,
                profile_revision INTEGER NOT NULL,
                operator_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                resulting_state TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                request_idempotency_key TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                FOREIGN KEY(profile_id, profile_revision)
                    REFERENCES governance_profile_revisions(profile_id, profile_revision)
            );

            CREATE TABLE IF NOT EXISTS governance_profile_projection (
                profile_id TEXT NOT NULL,
                profile_revision INTEGER NOT NULL,
                operator_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK(
                    state IN ('draft', 'active', 'superseded', 'revoked')
                ),
                last_event_sequence INTEGER NOT NULL,
                PRIMARY KEY(profile_id, profile_revision),
                FOREIGN KEY(profile_id, profile_revision)
                    REFERENCES governance_profile_revisions(profile_id, profile_revision),
                FOREIGN KEY(last_event_sequence)
                    REFERENCES governance_profile_lifecycle_events(event_sequence)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS one_active_profile_per_operator
            ON governance_profile_projection(operator_id)
            WHERE state = 'active';

            CREATE TABLE IF NOT EXISTS governance_profile_idempotency (
                idempotency_key TEXT PRIMARY KEY,
                intent_hash TEXT NOT NULL,
                result_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS governance_session_snapshot_results (
                run_id TEXT PRIMARY KEY,
                derivation_hash TEXT NOT NULL,
                result_json TEXT NOT NULL
            );

            CREATE TRIGGER IF NOT EXISTS governance_profile_revision_no_update
            BEFORE UPDATE ON governance_profile_revisions
            BEGIN
                SELECT RAISE(ABORT, 'governance profile revisions are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS governance_profile_revision_no_delete
            BEFORE DELETE ON governance_profile_revisions
            BEGIN
                SELECT RAISE(ABORT, 'governance profile revisions are immutable');
            END;

            CREATE TRIGGER IF NOT EXISTS governance_profile_event_no_update
            BEFORE UPDATE ON governance_profile_lifecycle_events
            BEGIN
                SELECT RAISE(ABORT, 'governance profile lifecycle is append-only');
            END;

            CREATE TRIGGER IF NOT EXISTS governance_profile_event_no_delete
            BEFORE DELETE ON governance_profile_lifecycle_events
            BEGIN
                SELECT RAISE(ABORT, 'governance profile lifecycle is append-only');
            END;
            """
        )


def _override_location(
    policy: dict[str, Any], field_path: str
) -> tuple[dict[str, Any], str, str, str]:
    parts = field_path.split(".")
    if len(parts) == 1 and parts[0] in {
        "constitution_hash",
        "constitution_version",
    }:
        return policy, parts[0], "locked", parts[0]
    if len(parts) == 2 and parts[0] == "operator_defaults":
        defaults = policy["operator_defaults"]
        field = parts[1]
        if field not in defaults:
            raise ProfileRegistryError("unknown operator default override")
        if field in _REPLACEABLE_DEFAULTS:
            mode = "replaceable"
        elif field in _TIGHTEN_ONLY_DEFAULTS:
            mode = "tighten_only"
        else:
            mode = "locked"
        return defaults, field, mode, field

    if len(parts) == 3 and parts[0] == "risk_dimensions":
        risk = _row_by_id(policy["risk_dimensions"], "dimension", parts[1])
        field = parts[2]
        if field not in risk:
            raise ProfileRegistryError("unknown risk-dimension override")
        mode = "tighten_only" if field in _TIGHTEN_ONLY_RISK_FIELDS else "locked"
        return risk, field, mode, field

    if len(parts) == 3 and parts[0] == "baseline_constraints":
        constraint = _row_by_id(policy["baseline_constraints"], "constraint_id", parts[1])
        field = parts[2]
        if field not in constraint:
            raise ProfileRegistryError("unknown baseline-constraint override")
        mode = "locked" if constraint.get("strength") in {"hard", "ruin"} else str(
            constraint.get("override_mode", "locked")
        )
        return constraint, field, mode, field

    if len(parts) == 3 and parts[0] == "ruin_criteria":
        ruin = _row_by_id(policy["ruin_criteria"], "ruin_id", parts[1])
        field = parts[2]
        if field not in ruin:
            raise ProfileRegistryError("unknown ruin-criterion override")
        return ruin, field, "locked", field

    raise ProfileRegistryError("unsupported override field_path")


def _row_by_id(rows: Sequence[dict[str, Any]], field: str, value: str) -> dict[str, Any]:
    matches = [row for row in rows if row.get(field) == value]
    if len(matches) != 1:
        raise ProfileRegistryError(f"override target {value} is not uniquely defined")
    return matches[0]


def _override_outcome(decisions: Sequence[Mapping[str, Any]]) -> str:
    outcomes = {decision["outcome"] for decision in decisions}
    if "refused" in outcomes:
        return "refused"
    if "fork_required" in outcomes:
        return "fork_required"
    return "accepted"


def _validate_system_constitution_floor(
    *,
    risks: Sequence[Mapping[str, Any]],
    constraints: Sequence[Mapping[str, Any]],
    ruins: Sequence[Mapping[str, Any]],
) -> None:
    constraints_by_id = {row["constraint_id"]: dict(row) for row in constraints}
    for identifier, required in _SYSTEM_CONSTRAINTS_BY_ID.items():
        if constraints_by_id.get(identifier) != required:
            raise ProfileRegistryError(
                f"system baseline constraint {identifier} cannot be removed or changed"
            )
    ruins_by_id = {row["ruin_id"]: dict(row) for row in ruins}
    for identifier, required in _SYSTEM_RUINS_BY_ID.items():
        if ruins_by_id.get(identifier) != required:
            raise ProfileRegistryError(
                f"system ruin criterion {identifier} cannot be removed or changed"
            )
    risks_by_dimension = {row["dimension"]: dict(row) for row in risks}
    for dimension, baseline in _SYSTEM_RISKS_BY_DIMENSION.items():
        current = risks_by_dimension[dimension]
        for field in ("default_response", "evaluability_type"):
            if current[field] != baseline[field]:
                raise ProfileRegistryError(
                    f"system risk dimension {dimension}.{field} is locked"
                )
        if current["maximum_tolerated_severity"] > baseline[
            "maximum_tolerated_severity"
        ]:
            raise ProfileRegistryError(
                f"system risk dimension {dimension} cannot be relaxed"
            )
        for field, ranks in _RANKS.items():
            if ranks[current[field]] < ranks[baseline[field]]:
                raise ProfileRegistryError(
                    f"system risk dimension {dimension}.{field} cannot be relaxed"
                )


def _profile_source_annotations(
    profile: Mapping[str, Any], *, profile_hash: str
) -> list[dict[str, str]]:
    rows = [
        {
            "field_path": "constitution_hash",
            "source": "system_locked",
            "source_hash": SYSTEM_CONSTITUTION_HASH,
        },
        {
            "field_path": "constitution_version",
            "source": "system_locked",
            "source_hash": SYSTEM_CONSTITUTION_HASH,
        },
        {
            "field_path": "operator_defaults",
            "source": "operator_profile",
            "source_hash": profile_hash,
        },
    ]
    for constraint in profile["baseline_constraints"]:
        identifier = constraint["constraint_id"]
        system_owned = identifier in _SYSTEM_CONSTRAINTS_BY_ID
        rows.append(
            {
                "field_path": f"baseline_constraints.{identifier}",
                "source": "system_locked" if system_owned else "operator_profile",
                "source_hash": (
                    SYSTEM_CONSTITUTION_HASH if system_owned else profile_hash
                ),
            }
        )
    for risk in profile["risk_dimensions"]:
        dimension = risk["dimension"]
        baseline = _SYSTEM_RISKS_BY_DIMENSION[dimension]
        for field in (
            "default_response",
            "evaluability_type",
            "evidence_requirement",
            "loss_posture",
            "maximum_tolerated_severity",
            "reversibility_requirement",
        ):
            system_owned = risk[field] == baseline[field]
            rows.append(
                {
                    "field_path": f"risk_dimensions.{dimension}.{field}",
                    "source": (
                        "system_locked" if system_owned else "operator_profile"
                    ),
                    "source_hash": (
                        SYSTEM_CONSTITUTION_HASH if system_owned else profile_hash
                    ),
                }
            )
    for ruin in profile["ruin_criteria"]:
        identifier = ruin["ruin_id"]
        system_owned = identifier in _SYSTEM_RUINS_BY_ID
        rows.append(
            {
                "field_path": f"ruin_criteria.{identifier}",
                "source": "system_locked" if system_owned else "operator_profile",
                "source_hash": (
                    SYSTEM_CONSTITUTION_HASH if system_owned else profile_hash
                ),
            }
        )
    rows.sort(key=lambda row: row["field_path"])
    return rows


def _normalize_fork_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FORK_PROVENANCE_FIELDS:
        raise ProfileRegistryError("fork provenance fields are invalid")
    normalized = deepcopy(dict(value))
    _nonempty_string(normalized["fork_reason"], "fork_reason")
    _nonempty_string(normalized["forked_from_run_id"], "forked_from_run_id")
    _hash(normalized["parent_head_event_hash"], "parent_head_event_hash")
    _hash(
        normalized["policy_diff_artifact_hash"], "policy_diff_artifact_hash"
    )
    normalized["inherited_evidence_root_hashes"] = _string_array(
        normalized["inherited_evidence_root_hashes"],
        "inherited_evidence_root_hashes",
    )
    canonical_json(normalized)
    return normalized


def _require_operator(actor: ActorContext, capability: str) -> None:
    if not isinstance(actor, ActorContext) or actor.provenance_class != "operator":
        raise ProfileRegistryError("trusted operator ActorContext is required")
    try:
        require_capability(actor, capability)
    except PermissionError as exc:
        raise ProfileRegistryError(str(exc)) from exc


def _closed_fields(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    fields = set(value)
    if required - fields or fields - required - optional:
        raise ProfileRegistryError(f"{label} has invalid fields")


def _enum(value: Any, field: str, allowed: set[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ProfileRegistryError(f"{field} has an unsupported value")
    return value


def _hash(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    if not _HASH_RE.fullmatch(text):
        raise ProfileRegistryError(f"{field} must be a lowercase SHA-256 hash")
    return text


def _version(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    if not _VERSION_RE.fullmatch(text):
        raise ProfileRegistryError(f"{field} must be a complete neutral version")
    return text


def _timestamp(value: Any, field: str) -> str:
    text = _nonempty_string(value, field)
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ProfileRegistryError(f"{field} must be a UTC millisecond timestamp") from exc
    if len(text) != 24:
        raise ProfileRegistryError(f"{field} must use exactly three fractional digits")
    return text


def _string_array(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ProfileRegistryError(f"{field} must be a string array")
    if value != sorted(set(value)):
        raise ProfileRegistryError(f"{field} must be sorted and unique")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProfileRegistryError(f"{field} must be an integer")
    return value


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProfileRegistryError(f"{field} must be a non-empty string")
    return value


__all__ = [
    "ActorContext",
    "GovernanceProfileRegistry",
    "IdempotencyConflict",
    "ProfileHeadConflict",
    "ProfileRegistryError",
    "SYSTEM_CONSTITUTION_HASH",
    "SYSTEM_CONSTITUTION_VERSION",
]
