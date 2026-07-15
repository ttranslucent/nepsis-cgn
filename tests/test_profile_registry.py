from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading

import pytest
from jsonschema import Draft202012Validator, ValidationError

from nepsis_cgn.canonical_runs.profile_registry import (
    GovernanceProfileRegistry,
    IdempotencyConflict,
    ProfileHeadConflict,
    ProfileRegistryError,
    SYSTEM_CONSTITUTION_HASH,
    SYSTEM_CONSTITUTION_VERSION,
)
from nepsis_cgn.contracts.canonical_json import canonical_hash
from nepsis_cgn.contracts.canonical_run import ActorContext
from nepsis_cgn.contracts.governance_profile import (
    GOVERNANCE_COMPARATOR_POLICY_VERSION,
    comparator_policy_hash,
)


OPERATOR = ActorContext(
    actor_id="operator:trent",
    provenance_class="operator",
    capability_id="cap-profile-operator",
    capabilities=frozenset({"create_run", "revise_operator_profile"}),
)
CREATED_AT = "2026-07-12T12:00:00.000Z"
ACTIVATED_AT = "2026-07-12T12:01:00.000Z"
HASH = SYSTEM_CONSTITUTION_HASH
ROOT = Path(__file__).resolve().parents[1]


def _profile(revision: int = 1, *, parent: dict[str, object] | None = None) -> dict:
    value = {
        "operator_governance_profile_schema_version": (
            "nepsis.operator_governance_profile@0.1.0"
        ),
        "profile_id": "profile_local",
        "profile_revision": revision,
        "constitution_version": SYSTEM_CONSTITUTION_VERSION,
        "constitution_hash": HASH,
        "created_at": CREATED_AT,
        "created_by": OPERATOR.actor_id,
        "governance_comparator_policy_version": (
            GOVERNANCE_COMPARATOR_POLICY_VERSION
        ),
        "governance_comparator_policy_hash": comparator_policy_hash(),
        "operator_defaults": {
            "clarification_budget": 3,
            "unresolved_optional_policy": "hold",
            "evidence_floor": "one_source",
            "proposal_mode": "one_at_a_time",
            "uncertainty_display": "ranges",
            "data_scope": "operator_cleared_non_phi",
        },
        "baseline_constraints": [
            {
                "constraint_id": "audit_required",
                "label": "Audit required",
                "strength": "hard",
                "applicability": "All governed actions.",
                "evaluability_type": "deterministic_boolean",
                "action_on_breach": "block",
                "override_mode": "locked",
                "rationale": "Canonical history must remain reconstructable.",
                "source_refs": ["system_constitution"],
            }
        ],
        "risk_dimensions": [
            {
                "dimension": "human_harm",
                "maximum_tolerated_severity": 2,
                "loss_posture": "downside_weighted",
                "evidence_requirement": "elevated",
                "reversibility_requirement": "preferred",
                "evaluability_type": "ordinal_evidence",
                "default_response": "still",
            },
            {
                "dimension": "epistemic_integrity",
                "maximum_tolerated_severity": 3,
                "loss_posture": "balanced",
                "evidence_requirement": "standard",
                "reversibility_requirement": "none",
                "evaluability_type": "ordinal_evidence",
                "default_response": "block",
            },
            {
                "dimension": "data_security_privacy",
                "maximum_tolerated_severity": 2,
                "loss_posture": "downside_weighted",
                "evidence_requirement": "elevated",
                "reversibility_requirement": "required",
                "evaluability_type": "ordinal_evidence",
                "default_response": "block",
            },
            {
                "dimension": "legal_authority_commitment",
                "maximum_tolerated_severity": 2,
                "loss_posture": "ruin_averse",
                "evidence_requirement": "strict",
                "reversibility_requirement": "required",
                "evaluability_type": "operator_attestation",
                "default_response": "still",
            },
            {
                "dimension": "operational_recoverability",
                "maximum_tolerated_severity": 2,
                "loss_posture": "downside_weighted",
                "evidence_requirement": "elevated",
                "reversibility_requirement": "required",
                "evaluability_type": "deterministic_boolean",
                "default_response": "zeroback",
            },
            {
                "dimension": "resource_financial_loss",
                "maximum_tolerated_severity": 3,
                "loss_posture": "balanced",
                "evidence_requirement": "standard",
                "reversibility_requirement": "preferred",
                "evaluability_type": "ordinal_evidence",
                "default_response": "still",
            },
        ],
        "ruin_criteria": [
            {
                "ruin_id": "loss_of_audit",
                "category": "audit_loss",
                "unwanted_outcome": "Unable to determine what became true.",
                "applicability": "Canonical provenance is unavailable.",
                "evaluability_type": "deterministic_boolean",
                "protected": True,
                "waivable": False,
                "response": "block",
                "actions_made_inadmissible": ["decision_commit"],
                "override_mode": "locked",
                "rationale": "Audit loss invalidates the governed result.",
                "source_refs": ["system_constitution"],
            }
        ],
    }
    if parent:
        value.update(parent)
    return value


@pytest.fixture
def registry() -> GovernanceProfileRegistry:
    connection = sqlite3.connect(":memory:")
    return GovernanceProfileRegistry(connection)


def _create_and_activate(
    registry: GovernanceProfileRegistry,
) -> tuple[dict, dict]:
    profile = _profile()
    created = registry.create_revision(
        profile,
        actor=OPERATOR,
        expected_head_revision=0,
        idempotency_key="create_1",
    )
    activated = registry.activate(
        "profile_local",
        1,
        actor=OPERATOR,
        expected_head_revision=1,
        idempotency_key="activate_1",
        occurred_at=ACTIVATED_AT,
    )
    return created, activated


def test_create_is_append_only_cas_guarded_and_idempotent(
    registry: GovernanceProfileRegistry,
) -> None:
    profile = _profile()
    first = registry.create_revision(
        profile,
        actor=OPERATOR,
        expected_head_revision=0,
        idempotency_key="create_1",
    )
    replay = registry.create_revision(
        profile,
        actor=OPERATOR,
        expected_head_revision=0,
        idempotency_key="create_1",
    )
    assert replay == first
    _validate_schema("nepsis.operator_governance_profile@0.1.0", profile)

    with pytest.raises(IdempotencyConflict):
        registry.create_revision(
            {**profile, "created_at": "2026-07-12T12:00:00.001Z"},
            actor=OPERATOR,
            expected_head_revision=0,
            idempotency_key="create_1",
        )

    with pytest.raises(ProfileHeadConflict):
        registry.create_revision(
            {**profile, "profile_revision": 2},
            actor=OPERATOR,
            expected_head_revision=0,
            idempotency_key="create_stale",
        )

    connection = registry._db
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE governance_profile_revisions SET created_at = ?",
            ("2026-07-12T12:00:00.002Z",),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM governance_profile_lifecycle_events")


def test_profile_contract_rules_fail_closed(registry: GovernanceProfileRegistry) -> None:
    widened_scope = _profile()
    widened_scope["operator_defaults"]["data_scope"] = (
        "allow_phi_direct_identifiers_and_secrets"
    )
    with pytest.raises(ProfileRegistryError, match="constitutional remote-data"):
        registry.create_revision(
            widened_scope,
            actor=OPERATOR,
            expected_head_revision=0,
            idempotency_key="widened_scope",
        )
    with pytest.raises(ValidationError):
        _validate_schema(
            "nepsis.operator_governance_profile@0.1.0", widened_scope
        )

    too_few_dimensions = _profile()
    too_few_dimensions["risk_dimensions"] = too_few_dimensions["risk_dimensions"][:4]
    with pytest.raises(ProfileRegistryError, match="exactly six"):
        registry.create_revision(
            too_few_dimensions,
            actor=OPERATOR,
            expected_head_revision=0,
            idempotency_key="too_few_dimensions",
        )

    forged_constitution = _profile()
    forged_constitution["constitution_hash"] = "a" * 64
    with pytest.raises(ProfileRegistryError, match="system constitution"):
        registry.create_revision(
            forged_constitution,
            actor=OPERATOR,
            expected_head_revision=0,
            idempotency_key="forged_constitution",
        )

    missing_system_constraint = _profile()
    missing_system_constraint["baseline_constraints"] = []
    with pytest.raises(ProfileRegistryError, match="cannot be removed"):
        registry.create_revision(
            missing_system_constraint,
            actor=OPERATOR,
            expected_head_revision=0,
            idempotency_key="missing_system_constraint",
        )

    duplicate_dimension = _profile()
    duplicate_dimension["risk_dimensions"][1]["dimension"] = "human_harm"
    with pytest.raises(ProfileRegistryError, match="unique"):
        registry.create_revision(
            duplicate_dimension,
            actor=OPERATOR,
            expected_head_revision=0,
            idempotency_key="duplicate_dimension",
        )

    severity_four = _profile()
    severity_four["risk_dimensions"][0]["maximum_tolerated_severity"] = 4
    with pytest.raises(ProfileRegistryError, match="0 through 3"):
        registry.create_revision(
            severity_four,
            actor=OPERATOR,
            expected_head_revision=0,
            idempotency_key="severity_four",
        )

    unlocked_hard = _profile()
    unlocked_hard["baseline_constraints"][0]["override_mode"] = "tighten_only"
    with pytest.raises(ProfileRegistryError, match="hard constraints must be locked"):
        registry.create_revision(
            unlocked_hard,
            actor=OPERATOR,
            expected_head_revision=0,
            idempotency_key="unlocked_hard",
        )

    for field, value, message in (
        ("protected", False, "protected"),
        ("waivable", True, "non-waivable"),
        ("override_mode", "replaceable", "locked"),
    ):
        invalid_ruin = _profile()
        invalid_ruin["ruin_criteria"][0][field] = value
        with pytest.raises(ProfileRegistryError, match=message):
            registry.create_revision(
                invalid_ruin,
                actor=OPERATOR,
                expected_head_revision=0,
                idempotency_key=f"invalid_ruin_{field}",
            )


def test_registry_rejects_runtime_data_scope_widening() -> None:
    with pytest.raises(ProfileRegistryError, match="constitutional remote-data"):
        GovernanceProfileRegistry.in_memory(
            data_scopes={
                "operator_cleared_non_phi": frozenset(
                    {"operator_cleared_non_phi"}
                ),
                "allow_phi_direct_identifiers_and_secrets": frozenset(
                    {"phi", "direct_identifiers", "secrets"}
                ),
            }
        )


def test_activation_is_idempotent_and_keeps_one_active_revision(
    registry: GovernanceProfileRegistry,
) -> None:
    created, first_activation = _create_and_activate(registry)
    assert registry.active_profile(operator_id=OPERATOR.actor_id)[
        "profile_revision"
    ] == 1
    assert registry.activate(
        "profile_local",
        1,
        actor=OPERATOR,
        expected_head_revision=1,
        idempotency_key="activate_1",
        occurred_at=ACTIVATED_AT,
    ) == first_activation

    second_profile = _profile(
        2,
        parent={
            "parent_profile_revision": 1,
            "parent_profile_hash": created["profile_hash"],
        },
    )
    second_profile["created_at"] = "2026-07-12T12:02:00.000Z"
    registry.create_revision(
        second_profile,
        actor=OPERATOR,
        expected_head_revision=1,
        idempotency_key="create_2",
    )
    registry.activate(
        "profile_local",
        2,
        actor=OPERATOR,
        expected_head_revision=2,
        idempotency_key="activate_2",
        occurred_at="2026-07-12T12:03:00.000Z",
    )

    assert registry.lifecycle_state("profile_local", 1) == "superseded"
    assert registry.lifecycle_state("profile_local", 2) == "active"
    assert registry.active_profile(operator_id=OPERATOR.actor_id)[
        "profile_revision"
    ] == 2


def test_concurrent_activation_of_one_head_has_exactly_one_winner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "profiles.sqlite"
    left = GovernanceProfileRegistry.open(path)
    created = left.create_revision(
        _profile(),
        actor=OPERATOR,
        expected_head_revision=0,
        idempotency_key="create-concurrent",
    )
    assert created["profile_revision"] == 1
    right = GovernanceProfileRegistry.open(path)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def activate(registry: GovernanceProfileRegistry, key: str) -> None:
        barrier.wait()
        try:
            registry.activate(
                "profile_local",
                1,
                actor=OPERATOR,
                expected_head_revision=1,
                idempotency_key=key,
                occurred_at=ACTIVATED_AT,
            )
        except ProfileRegistryError:
            outcomes.append("refused")
        else:
            outcomes.append("activated")

    threads = [
        threading.Thread(target=activate, args=(left, "activate-left")),
        threading.Thread(target=activate, args=(right, "activate-right")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert sorted(outcomes) == ["activated", "refused"]
    assert left.active_profile(operator_id=OPERATOR.actor_id)["profile_revision"] == 1
    left.close()
    right.close()


def test_revoke_is_cas_guarded_and_idempotent(
    registry: GovernanceProfileRegistry,
) -> None:
    _create_and_activate(registry)
    revoked = registry.revoke(
        "profile_local",
        1,
        actor=OPERATOR,
        expected_head_revision=1,
        idempotency_key="revoke_1",
        occurred_at="2026-07-12T12:04:00.000Z",
    )
    assert revoked["state"] == "revoked"
    assert registry.active_profile(operator_id=OPERATOR.actor_id) is None
    assert registry.revoke(
        "profile_local",
        1,
        actor=OPERATOR,
        expected_head_revision=1,
        idempotency_key="revoke_1",
        occurred_at="2026-07-12T12:04:00.000Z",
    ) == revoked


def test_pre_genesis_tightening_and_replaceable_override_are_pinned(
    registry: GovernanceProfileRegistry,
) -> None:
    _create_and_activate(registry)
    result = registry.build_session_snapshot(
        "profile_local",
        run_id="run_001",
        overrides=[
            {
                "override_id": "tighten_harm",
                "field_path": (
                    "risk_dimensions.human_harm.maximum_tolerated_severity"
                ),
                "proposed_value": 1,
                "rationale": "This run requires a lower tolerance.",
            },
            {
                "override_id": "replace_budget",
                "field_path": "operator_defaults.clarification_budget",
                "proposed_value": 2,
                "rationale": "Bound the pre-genesis interview.",
            },
        ],
        created_at="2026-07-12T12:05:00.000Z",
        actor=OPERATOR,
    )

    assert result["outcome"] == "accepted"
    snapshot = result["snapshot"]
    assert snapshot["effective_policy"]["operator_defaults"][
        "clarification_budget"
    ] == 2
    harm = next(
        item
        for item in snapshot["effective_policy"]["risk_dimensions"]
        if item["dimension"] == "human_harm"
    )
    assert harm["maximum_tolerated_severity"] == 1
    assert [row["outcome"] for row in result["override_decisions"]] == [
        "accepted",
        "accepted",
    ]
    assert snapshot["effective_policy_hash"] == canonical_hash(
        snapshot["effective_policy"]
    )
    _validate_schema("nepsis.session_governance_snapshot@0.1.0", snapshot)


def test_protected_relaxation_is_refused_and_active_replaceable_requires_fork(
    registry: GovernanceProfileRegistry,
) -> None:
    _create_and_activate(registry)
    relaxation = registry.build_session_snapshot(
        "profile_local",
        run_id="run_relax",
        overrides=[
            {
                "override_id": "weaken_harm",
                "field_path": (
                    "risk_dimensions.human_harm.maximum_tolerated_severity"
                ),
                "proposed_value": 3,
                "rationale": "Attempted relaxation.",
            }
        ],
        created_at="2026-07-12T12:05:00.000Z",
        actor=OPERATOR,
    )
    assert relaxation["outcome"] == "refused"
    assert relaxation["override_decisions"][0]["comparison"] == "weaker"

    constitution_change = registry.build_session_snapshot(
        "profile_local",
        run_id="run_constitution",
        overrides=[
            {
                "override_id": "replace_constitution",
                "field_path": "constitution_hash",
                "proposed_value": "b" * 64,
                "rationale": "Attempted constitutional change.",
            }
        ],
        created_at="2026-07-12T12:05:00.000Z",
        actor=OPERATOR,
    )
    assert constitution_change["outcome"] == "refused"

    invalid_budget = registry.build_session_snapshot(
        "profile_local",
        run_id="run_invalid_budget",
        overrides=[
            {
                "override_id": "invalid_budget",
                "field_path": "operator_defaults.clarification_budget",
                "proposed_value": 99,
                "rationale": "Attempted out-of-range replacement.",
            }
        ],
        created_at="2026-07-12T12:05:00.000Z",
        actor=OPERATOR,
    )
    assert invalid_budget["outcome"] == "refused"

    ruin_change = registry.build_session_snapshot(
        "profile_local",
        run_id="run_ruin",
        overrides=[
            {
                "override_id": "waive_ruin",
                "field_path": "ruin_criteria.loss_of_audit.waivable",
                "proposed_value": True,
                "rationale": "Attempted waiver.",
            }
        ],
        created_at="2026-07-12T12:05:00.000Z",
        actor=OPERATOR,
    )
    assert ruin_change["outcome"] == "refused"

    active_replacement = registry.build_session_snapshot(
        "profile_local",
        run_id="run_fork",
        overrides=[
            {
                "override_id": "change_budget",
                "field_path": "operator_defaults.clarification_budget",
                "proposed_value": 1,
                "rationale": "Requested after genesis.",
            }
        ],
        created_at="2026-07-12T12:05:00.000Z",
        actor=OPERATOR,
        session_started=True,
    )
    assert active_replacement["outcome"] == "fork_required"


def test_later_profile_revision_does_not_mutate_persisted_snapshot(
    registry: GovernanceProfileRegistry,
) -> None:
    created, _ = _create_and_activate(registry)
    first = registry.build_session_snapshot(
        "profile_local",
        run_id="run_pinned",
        overrides=[],
        created_at="2026-07-12T12:05:00.000Z",
        actor=OPERATOR,
    )
    pinned_hash = first["snapshot_hash"]

    second_profile = _profile(
        2,
        parent={
            "parent_profile_revision": 1,
            "parent_profile_hash": created["profile_hash"],
        },
    )
    second_profile["created_at"] = "2026-07-12T12:06:00.000Z"
    second_profile["operator_defaults"]["clarification_budget"] = 1
    registry.create_revision(
        second_profile,
        actor=OPERATOR,
        expected_head_revision=1,
        idempotency_key="create_2",
    )
    registry.activate(
        "profile_local",
        2,
        actor=OPERATOR,
        expected_head_revision=2,
        idempotency_key="activate_2",
        occurred_at="2026-07-12T12:07:00.000Z",
    )

    replay = registry.build_session_snapshot(
        "profile_local",
        run_id="run_pinned",
        overrides=[],
        created_at="2026-07-12T12:05:00.000Z",
        actor=OPERATOR,
    )
    assert replay == first
    assert replay["snapshot_hash"] == pinned_hash
    assert replay["snapshot"]["profile_revision"] == 1
    assert replay["snapshot"]["effective_policy"]["operator_defaults"][
        "clarification_budget"
    ] == 3


def test_fork_provenance_is_canonical_and_session_pinned(
    registry: GovernanceProfileRegistry,
) -> None:
    _create_and_activate(registry)
    provenance = {
        "fork_reason": "Irrecoverable predecessor thread.",
        "forked_from_run_id": "run_parent",
        "inherited_evidence_root_hashes": ["1" * 64, "2" * 64],
        "parent_head_event_hash": "3" * 64,
        "policy_diff_artifact_hash": "4" * 64,
    }
    result = registry.build_session_snapshot(
        "profile_local",
        run_id="run_child",
        overrides=[],
        created_at="2026-07-12T12:08:00.000Z",
        actor=OPERATOR,
        fork_provenance=provenance,
    )

    assert result["outcome"] == "accepted"
    assert result["snapshot"]["fork_provenance"] == provenance
    assert result["snapshot_hash"] == canonical_hash(result["snapshot"])
    _validate_schema(
        "nepsis.session_governance_snapshot@0.1.0", result["snapshot"]
    )

    with pytest.raises(ProfileRegistryError, match="sorted and unique"):
        registry.build_session_snapshot(
            "profile_local",
            run_id="run_bad_fork",
            overrides=[],
            created_at="2026-07-12T12:08:00.000Z",
            actor=OPERATOR,
            fork_provenance={
                **provenance,
                "inherited_evidence_root_hashes": ["2" * 64, "1" * 64],
            },
        )


def test_snapshot_derivation_is_deterministic_across_registries() -> None:
    left = GovernanceProfileRegistry(sqlite3.connect(":memory:"))
    right = GovernanceProfileRegistry(sqlite3.connect(":memory:"))
    _create_and_activate(left)
    _create_and_activate(right)

    inputs = {
        "run_id": "run_deterministic",
        "overrides": [],
        "created_at": "2026-07-12T12:08:00.000Z",
        "actor": OPERATOR,
    }
    left_result = left.build_session_snapshot("profile_local", **inputs)
    right_result = right.build_session_snapshot("profile_local", **inputs)

    assert left_result == right_result
    assert left_result["snapshot_hash"] == canonical_hash(left_result["snapshot"])


def _validate_schema(schema_version: str, value: dict) -> None:
    path = ROOT / "interop" / "schemas" / f"{schema_version}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value)
