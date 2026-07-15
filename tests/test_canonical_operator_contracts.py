from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nepsis_cgn.contracts.canonical_json import canonical_hash
from nepsis_cgn.contracts.governance_profile import comparator_policy_hash
from nepsis_cgn.verification.receipts import build_trust_anchor


ROOT = Path(__file__).resolve().parents[1]
INTEROP = ROOT / "interop"
HASH = "a" * 64
OTHER_HASH = "b" * 64
TIMESTAMP = "2026-07-12T12:00:00.000Z"


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _schema(name: str) -> dict:
    return _load(INTEROP / "schemas" / name)


def test_manifest_pins_every_declared_asset() -> None:
    manifest = _load(INTEROP / "contract-manifest.json")
    assert manifest["contract_manifest_version"] == (
        "nepsis.interop_contract_manifest@0.1.0"
    )
    assert manifest["canonical_json_version"] == "nepsis.canonical_json@0.1.0"
    declared_schema_paths = {
        asset["path"] for asset in manifest["assets"] if asset["role"] == "schema"
    }
    actual_schema_paths = {
        str(path.relative_to(INTEROP))
        for path in (INTEROP / "schemas").glob("*.schema.json")
    }
    assert declared_schema_paths == actual_schema_paths
    for asset in manifest["assets"]:
        path = INTEROP / asset["path"]
        assert path.is_file(), asset["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == asset["sha256"]


def test_all_neutral_schemas_are_valid_draft_2020_12() -> None:
    for path in sorted((INTEROP / "schemas").glob("*.schema.json")):
        schema = _load(path)
        jsonschema.Draft202012Validator.check_schema(schema)


def test_mirrored_mc_golden_conforms_to_neutral_bundle_schema() -> None:
    bundle = _load(INTEROP / "golden" / "nepsis.interop_bundle@0.2.0.json")
    schema = _schema("nepsis.interop_bundle@0.2.0.schema.json")
    jsonschema.Draft202012Validator(schema).validate(bundle)


def test_context_manifest_requires_cgn_bound_snapshot_roots() -> None:
    schema = _schema("nepsis.context_manifest@0.1.0.schema.json")
    manifest = {
        "active_hold": False,
        "context_manifest_schema_version": "nepsis.context_manifest@0.1.0",
        "data_classification": "synthetic",
        "denominator_collapse_active": False,
        "effective_policy_hash": HASH,
        "evidence_root_hash": HASH,
        "frame_root_hash": HASH,
        "generated_at": TIMESTAMP,
        "generator": {
            "actor_id": "validator:nepsis_cgn",
            "authority": "nepsis_cgn",
            "generator_version": "nepsis.context_manifest_generator@0.1.0",
            "provenance_class": "validator",
        },
        "manifest_id": "manifest_001",
        "observation_root_hash": HASH,
        "operator_governance_profile_hash": HASH,
        "packet_projection_hash": HASH,
        "population_root_hash": HASH,
        "relevant_artifact_revisions": [
            {
                "artifact_hash": HASH,
                "artifact_schema_version": "nepsis.frame@0.1.0",
                "revision": 1,
                "role": "active_frame",
            }
        ],
        "remote_inference_authorized": True,
        "run_head_event_hash": OTHER_HASH,
        "run_head_sequence": 4,
        "run_id": "run_001",
        "session_governance_snapshot_hash": HASH,
        "unresolved_contradiction_hashes": [],
        "unresolved_red_hazard_hashes": [],
    }
    jsonschema.validate(manifest, schema)
    for field in (
        "run_head_event_hash",
        "packet_projection_hash",
        "operator_governance_profile_hash",
        "effective_policy_hash",
    ):
        incomplete = deepcopy(manifest)
        incomplete.pop(field)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(incomplete, schema)


def test_model_action_binds_context_origin_and_exact_visible_proposal() -> None:
    schema = _schema("nepsis.action_request@0.1.0.schema.json")
    request = {
        "action_request_schema_version": "nepsis.action_request@0.1.0",
        "action_type": "model_candidate_submitted",
        "artifact_hashes": [HASH],
        "capability": "submit_model_candidate",
        "capability_id": "capability_model_001",
        "context_manifest_hash": HASH,
        "created_at": TIMESTAMP,
        "effective_policy_hash": HASH,
        "expected_head_event_hash": HASH,
        "expected_head_sequence": 2,
        "external_codex_ref_hash": HASH,
        "idempotency_key": "candidate_001",
        "intent_hash": HASH,
        "operator_governance_profile_hash": HASH,
        "operator_visible_proposal_hash": HASH,
        "payload": {"target_path": "frame.constraints_hard"},
        "payload_hash": HASH,
        "run_id": "run_001",
        "session_governance_snapshot_hash": HASH,
        "trusted_adapter_intent_id": "adapter_intent_001",
    }
    jsonschema.validate(request, schema)
    for field in (
        "context_manifest_hash",
        "external_codex_ref_hash",
        "operator_visible_proposal_hash",
    ):
        incomplete = deepcopy(request)
        incomplete.pop(field)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(incomplete, schema)

    forged_actor = {**request, "actor": "operator"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(forged_actor, schema)


def test_operator_disposition_request_requires_confirmation_and_proposal_hash() -> None:
    schema = _schema("nepsis.action_request@0.1.0.schema.json")
    request = {
        "action_request_schema_version": "nepsis.action_request@0.1.0",
        "action_type": "record_operator_disposition",
        "artifact_hashes": [HASH],
        "capability": "submit_operator_disposition",
        "capability_id": "capability_operator_001",
        "created_at": TIMESTAMP,
        "effective_policy_hash": HASH,
        "expected_head_event_hash": HASH,
        "expected_head_sequence": 2,
        "idempotency_key": "disposition_001",
        "intent_hash": HASH,
        "operator_confirmation": {
            "confirmed": True,
            "confirmed_at": TIMESTAMP,
            "consequence_acknowledged": True,
            "rationale": "Reviewed the exact pending proposal.",
        },
        "operator_governance_profile_hash": HASH,
        "operator_visible_proposal_hash": HASH,
        "payload": {
            "disposition": "defer",
            "operator_visible_proposal_hash": HASH,
            "run_id": "run_001",
        },
        "payload_hash": HASH,
        "run_id": "run_001",
        "session_governance_snapshot_hash": HASH,
        "trusted_adapter_intent_id": "adapter_intent_001",
    }
    jsonschema.validate(request, schema)
    for field in ("operator_confirmation", "operator_visible_proposal_hash"):
        incomplete = deepcopy(request)
        incomplete.pop(field)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(incomplete, schema)


def test_action_receipt_has_closed_outcomes_and_no_canonical_replay_state() -> None:
    schema = _schema("nepsis.action_receipt@0.1.0.schema.json")
    receipt = {
        "action_receipt_schema_version": "nepsis.action_receipt@0.1.0",
        "actor_id": "model:codex",
        "advanced_head": True,
        "artifact_hashes": [HASH],
        "capability": "submit_model_candidate",
        "capability_id": "capability_model_001",
        "context_manifest_hash": HASH,
        "effective_policy_hash": HASH,
        "event_hash": OTHER_HASH,
        "expected_head_event_hash": HASH,
        "expected_head_sequence": 1,
        "idempotency_key": "candidate_001",
        "intent_hash": HASH,
        "issued_at": TIMESTAMP,
        "outcome": "candidate_recorded",
        "packet_projection_hash": HASH,
        "policy_bindings": [
            {
                "policy_hash": HASH,
                "policy_id": "run_validator",
                "policy_version": "nepsis.run_validator@0.1.0",
            }
        ],
        "postcondition": {
            "active_hold": False,
            "governance_status": "candidate_pending",
            "packet_projection_hash": HASH,
            "phase": "red_review",
        },
        "postcondition_hash": HASH,
        "prior_head_event_hash": HASH,
        "prior_head_sequence": 1,
        "receipt_id": "receipt_001",
        "request_hash": HASH,
        "resulting_head_event_hash": OTHER_HASH,
        "resulting_head_sequence": 2,
        "run_id": "run_001",
        "operator_governance_profile_hash": HASH,
        "provenance_class": "model",
        "session_governance_snapshot_hash": HASH,
        "signature": {
            "algorithm": "ed25519",
            "key_id": "ed25519:test",
            "value": "c" * 86,
        },
        "signed_at": TIMESTAMP,
        "trusted_adapter_intent_id": "adapter_intent_001",
        "validator_policy_hash": HASH,
        "validator_policy_version": "nepsis.run_validator@0.1.0",
        "verification_level": "writer_post_commit_reread",
    }
    jsonschema.validate(receipt, schema)

    duplicate = {**receipt, "outcome": "duplicate"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(duplicate, schema)
    replayed = {**receipt, "replayed": True}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(replayed, schema)


def _governance_profile() -> dict:
    dimensions = [
        "human_harm",
        "data_security_privacy",
        "legal_authority_commitment",
        "operational_recoverability",
        "epistemic_integrity",
    ]
    return {
        "baseline_constraints": [
            {
                "action_on_breach": "block",
                "applicability": "Always applicable to canonical authority.",
                "constraint_id": "single_writer",
                "evaluability_type": "deterministic_boolean",
                "label": "Exactly one canonical writer",
                "override_mode": "locked",
                "rationale": "Dual writers destroy audit meaning.",
                "source_refs": ["canonical_operator_run_contract"],
                "strength": "hard",
            }
        ],
        "constitution_hash": HASH,
        "constitution_version": "nepsis.system_constitution@0.1.0",
        "created_at": TIMESTAMP,
        "created_by": "operator:local",
        "governance_comparator_policy_hash": comparator_policy_hash(),
        "governance_comparator_policy_version": (
            "nepsis.governance_comparator_policy@0.1.0"
        ),
        "operator_defaults": {
            "clarification_budget": 3,
            "data_scope": "operator_cleared_non_phi",
            "evidence_floor": "one_source",
            "proposal_mode": "one_at_a_time",
            "uncertainty_display": "ranges",
            "unresolved_optional_policy": "hold",
        },
        "operator_governance_profile_schema_version": (
            "nepsis.operator_governance_profile@0.1.0"
        ),
        "profile_id": "profile_local",
        "profile_revision": 1,
        "risk_dimensions": [
            {
                "default_response": "still",
                "dimension": dimension,
                "evaluability_type": "ordinal_evidence",
                "evidence_requirement": "elevated",
                "loss_posture": "downside_weighted",
                "maximum_tolerated_severity": 2,
                "reversibility_requirement": "preferred",
            }
            for dimension in dimensions
        ],
        "ruin_criteria": [
            {
                "actions_made_inadmissible": ["decision_commit"],
                "applicability": "Canonical provenance is unavailable.",
                "category": "audit_loss",
                "evaluability_type": "deterministic_boolean",
                "override_mode": "locked",
                "protected": True,
                "rationale": "Truth cannot be reconstructed after audit loss.",
                "response": "block",
                "ruin_id": "loss_of_audit_provenance",
                "source_refs": ["system_constitution"],
                "unwanted_outcome": "Unable to determine what became true.",
                "waivable": False,
            }
        ],
    }


def test_profile_schema_refuses_mutable_lifecycle_and_ruin_relaxation() -> None:
    schema = _schema("nepsis.operator_governance_profile@0.1.0.schema.json")
    profile = _governance_profile()
    jsonschema.validate(profile, schema)

    mutable_status = {**profile, "status": "active"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(mutable_status, schema)

    severity_four = deepcopy(profile)
    severity_four["risk_dimensions"][0]["maximum_tolerated_severity"] = 4
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(severity_four, schema)

    waivable = deepcopy(profile)
    waivable["ruin_criteria"][0]["waivable"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(waivable, schema)


def test_session_snapshot_pins_profile_effective_policy_and_sources() -> None:
    schema = _schema("nepsis.session_governance_snapshot@0.1.0.schema.json")
    profile = _governance_profile()
    profile_hash = canonical_hash(profile)
    effective_policy = {
        "data_scope": "operator_cleared_non_phi",
        "maximum_tolerated_severity": 2,
    }
    snapshot = {
        "constitution_hash": HASH,
        "constitution_version": "nepsis.system_constitution@0.1.0",
        "created_at": TIMESTAMP,
        "created_by": "validator:nepsis_cgn",
        "effective_policy": effective_policy,
        "effective_policy_hash": canonical_hash(effective_policy),
        "governance_comparator_policy_hash": comparator_policy_hash(),
        "governance_comparator_policy_version": (
            "nepsis.governance_comparator_policy@0.1.0"
        ),
        "operator_governance_profile_hash": profile_hash,
        "profile_id": "profile_local",
        "profile_revision": 1,
        "run_id": "run_001",
        "session_governance_snapshot_schema_version": (
            "nepsis.session_governance_snapshot@0.1.0"
        ),
        "snapshot_id": "snapshot_run_001",
        "source_annotations": [
            {
                "field_path": "maximum_tolerated_severity",
                "source": "operator_profile",
                "source_hash": profile_hash,
            }
        ],
        "validated_overrides": [],
    }
    jsonschema.validate(snapshot, schema)


def test_receipt_trust_anchor_conforms_to_neutral_schema() -> None:
    schema = _schema("nepsis.action_receipt_trust_anchor@0.1.0.schema.json")
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    anchor = build_trust_anchor(key.public_key(), activated_at=TIMESTAMP)
    jsonschema.validate(anchor, schema)


def test_target_contract_keeps_public_mvp_outside_private_ledger() -> None:
    contract = (ROOT / "docs" / "canonical-operator-run-contract.md").read_text(
        encoding="utf-8"
    )
    assert "public deterministic `/mvp` path remains model-free and unchanged" in contract
    assert "store canonical data under serverless `/tmp`" in contract
    assert "There is no bidirectional audit-chain synchronization" in contract
