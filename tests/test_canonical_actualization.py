from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from nepsis_cgn.canonical_runs.actualization import (
    CANONICAL_ACTUALIZATION_POLICY,
    CANONICAL_ACTUALIZATION_POLICY_HASH,
    PERFORM_ZEROBACK_ACTION_TYPE,
    RELEASE_STILL_ACTION_TYPE,
    REQUEST_DECISION_COMMIT_ACTION_TYPE,
    validate_decision_commit,
    validate_release_still,
    validate_zeroback,
)
from nepsis_cgn.canonical_runs.operator_disposition import (
    OPERATOR_DISPOSITION_ACTION_TYPE,
    validate_operator_disposition,
)
from nepsis_cgn.canonical_runs.service import (
    CanonicalRunService,
    CanonicalRunServiceError,
    OPERATOR_VISIBLE_PROPOSAL_VERSION,
)
from nepsis_cgn.contracts.canonical_json import canonical_hash
from nepsis_cgn.verification.canonical_actualization import (
    CanonicalActualizationVerificationError,
    verify_canonical_actualization,
)
from nepsis_cgn.verification.canonical_run_export import (
    CanonicalRunExportVerificationError,
    verify_protected_canonical_run_export,
)
from nepsis_cgn.verification.receipts import sign_action_receipt
from tests.test_canonical_run_service import (
    ACTION_AT,
    EFFECTIVE_POLICY_HASH,
    PRIVATE_KEY,
    PROFILE_HASH,
    SNAPSHOT_HASH,
    model_actor,
    operator_actor,
    service_and_store,
)


ROOT = Path(__file__).resolve().parents[1]
DISPOSITION_AT = "2026-07-12T16:02:00.000Z"
RELEASE_AT = "2026-07-12T16:03:00.000Z"
COMMIT_AT = "2026-07-12T16:04:00.000Z"
ZEROBACK_AT = "2026-07-12T16:05:00.000Z"


def _confirmation(created_at: str, rationale: str) -> dict[str, object]:
    return {
        "confirmed": True,
        "confirmed_at": created_at,
        "consequence_acknowledged": True,
        "rationale": rationale,
    }


def _candidate(
    service: CanonicalRunService,
) -> tuple[dict[str, object], str]:
    context = dict(
        service.build_context_manifest(
            run_id="run-001",
            actor=operator_actor("read_snapshot"),
        ).artifact
    )
    change = {
        "base_event_hash": context["run_head_event_hash"],
        "model_proposed_tier": "T2",
        "operation_type": "replace",
        "proposed_value": "Keep the decision reversible.",
        "target_path": "analysis.current_summary",
    }
    proposal = {
        "alternatives_summary": "Retain the current summary.",
        "evidence_refs": [context["manifest_id"]],
        "hazards_summary": "No unresolved RED hazard is present in the fixture.",
        "operator_visible_proposal_schema_version": (
            OPERATOR_VISIBLE_PROPOSAL_VERSION
        ),
        "proposal_text": "Replace the current analysis summary.",
        "rationale_text": "The replacement remains reversible.",
        "requested_change": change,
    }
    proposal_hash = canonical_hash(proposal)
    external = service.build_external_codex_ref(
        actor=model_actor(),
        run_id="run-001",
        adapter_version="adapter-0.1.0",
        created_at=ACTION_AT,
        thread_id="thread-001",
        turn_id="turn-001",
        tool_call_id="tool-001",
        model_id="gpt-test",
        model_configuration_epoch="model-config-001",
        operator_visible_proposal_hash=proposal_hash,
    )
    service.submit_model_candidate(
        actor=model_actor(),
        context_manifest=context,
        operator_visible_proposal=proposal,
        external_codex_ref=external,
        created_at=ACTION_AT,
        idempotency_key="candidate-actualization-001",
        trusted_adapter_intent_id="adapter:candidate-actualization-001",
    )
    return change, proposal_hash


def _operator_action(
    service: CanonicalRunService,
    store,
    *,
    capability: str,
    action_type: str,
    payload: dict[str, object],
    created_at: str,
    idempotency_key: str,
    validator,
):
    snapshot = store.get_snapshot("run-001")
    return service.submit_operator_action(
        actor=operator_actor(capability),
        capability=capability,
        action_type=action_type,
        payload=payload,
        confirmation=_confirmation(created_at, f"Confirm {action_type}."),
        created_at=created_at,
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        expected_head_event_hash=snapshot["head_event_hash"],
        expected_head_sequence=snapshot["head_sequence"],
        idempotency_key=idempotency_key,
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=SNAPSHOT_HASH,
        trusted_adapter_intent_id=f"adapter:{idempotency_key}",
        validator=validator,
    )


def _accept(
    service: CanonicalRunService, store, proposal_hash: str
):
    return _operator_action(
        service,
        store,
        capability="submit_operator_disposition",
        action_type=OPERATOR_DISPOSITION_ACTION_TYPE,
        payload={
            "disposition": "accept",
            "operator_visible_proposal_hash": proposal_hash,
            "run_id": "run-001",
        },
        created_at=DISPOSITION_AT,
        idempotency_key="accept-actualization-001",
        validator=validate_operator_disposition,
    )


def _verify_actualization_export(exported: dict[str, object]) -> dict[str, object]:
    artifacts = {
        row["artifact_hash"]: row for row in exported["artifacts"]
    }
    return verify_canonical_actualization(
        events=exported["events"],
        artifacts=artifacts,
        final_packet_projection=exported["packet_projection"],
        final_postcondition=exported["postcondition"],
        system_policy_bindings=exported["run"]["system_policy_bindings"],
    )


def _actualized_protected_export() -> dict[str, object]:
    service, store = service_and_store()
    change, proposal_hash = _candidate(service)
    _accept(service, store, proposal_hash)
    _operator_action(
        service,
        store,
        capability="release_still",
        action_type=RELEASE_STILL_ACTION_TYPE,
        payload={
            "operator_visible_proposal_hash": proposal_hash,
            "run_id": "run-001",
        },
        created_at=RELEASE_AT,
        idempotency_key="release-protected-export-001",
        validator=validate_release_still,
    )
    _operator_action(
        service,
        store,
        capability="request_decision_commit",
        action_type=REQUEST_DECISION_COMMIT_ACTION_TYPE,
        payload={
            "operator_visible_proposal_hash": proposal_hash,
            "requested_change": change,
            "run_id": "run-001",
        },
        created_at=COMMIT_AT,
        idempotency_key="commit-protected-export-001",
        validator=validate_decision_commit,
    )
    return dict(
        service.export_run(
            run_id="run-001", actor=operator_actor("export_run")
        )
    )


def _resign_rerooted_terminal_export(exported: dict[str, object]) -> None:
    event = exported["events"][-1]
    event["payload_hash"] = canonical_hash(event["payload"])
    event_envelope = {
        key: deepcopy(value)
        for key, value in event.items()
        if key not in {"event_hash", "payload"}
    }
    event["event_hash"] = canonical_hash(event_envelope)
    exported["run"]["head_event_hash"] = event["event_hash"]

    outcome = exported["outcomes"][-1]
    outcome["event_hash"] = event["event_hash"]
    outcome["resulting_head_event_hash"] = event["event_hash"]
    outcome_record = {
        key: deepcopy(value)
        for key, value in outcome.items()
        if key != "outcome_id"
    }
    outcome["outcome_id"] = canonical_hash(
        {
            "outcome_record": outcome_record,
            "schema": "canonical_run_store_outcome@0.1.0",
        }
    )

    prior_receipt = exported["action_receipts"][-1]
    unsigned_receipt = deepcopy(outcome_record)
    unsigned_receipt.update(
        {
            "action_receipt_schema_version": prior_receipt[
                "action_receipt_schema_version"
            ],
            "receipt_id": f"receipt:{canonical_hash(outcome)}",
            "signed_at": prior_receipt["signed_at"],
            "validator_policy_hash": prior_receipt["validator_policy_hash"],
            "validator_policy_version": prior_receipt[
                "validator_policy_version"
            ],
            "verification_level": prior_receipt["verification_level"],
        }
    )
    exported["action_receipts"][-1] = sign_action_receipt(
        unsigned_receipt,
        private_key=PRIVATE_KEY,
        trust_anchor=exported["receipt_trust_anchor"],
        signing_at=prior_receipt["signed_at"],
    )
    unsigned_export = {
        key: deepcopy(value)
        for key, value in exported.items()
        if key != "export_root_hash"
    }
    exported["export_root_hash"] = canonical_hash(unsigned_export)


def test_validator_applies_exact_accepted_proposal_only_after_still_release() -> None:
    service, store = service_and_store()
    change, proposal_hash = _candidate(service)
    candidate_snapshot = store.get_snapshot("run-001")
    assert candidate_snapshot["postcondition"] == {
        "active_hold": True,
        "governance_status": "proposal_pending",
        "packet_projection_hash": canonical_hash(
            candidate_snapshot["packet_projection"]
        ),
        "phase": "proposal_review",
    }
    _accept(service, store, proposal_hash)

    premature = _operator_action(
        service,
        store,
        capability="request_decision_commit",
        action_type=REQUEST_DECISION_COMMIT_ACTION_TYPE,
        payload={
            "operator_visible_proposal_hash": proposal_hash,
            "requested_change": change,
            "run_id": "run-001",
        },
        created_at=RELEASE_AT,
        idempotency_key="premature-commit",
        validator=validate_decision_commit,
    )
    assert premature.receipt["outcome"] == "refused"
    assert premature.receipt["reason_code"] == "still_release_required"

    released = _operator_action(
        service,
        store,
        capability="release_still",
        action_type=RELEASE_STILL_ACTION_TYPE,
        payload={
            "operator_visible_proposal_hash": proposal_hash,
            "run_id": "run-001",
        },
        created_at=COMMIT_AT,
        idempotency_key="release-actualization-001",
        validator=validate_release_still,
    )
    assert released.receipt["outcome"] == "committed"

    committed = _operator_action(
        service,
        store,
        capability="request_decision_commit",
        action_type=REQUEST_DECISION_COMMIT_ACTION_TYPE,
        payload={
            "operator_visible_proposal_hash": proposal_hash,
            "requested_change": change,
            "run_id": "run-001",
        },
        created_at=ZEROBACK_AT,
        idempotency_key="commit-actualization-001",
        validator=validate_decision_commit,
    )
    exported = store.export_run("run-001")
    application = exported["packet_projection"]["operator_proposal_application"]
    assert committed.receipt["outcome"] == "committed"
    assert exported["events"][-1]["event_type"] == "decision_committed"
    assert exported["events"][-1]["provenance_class"] == "validator"
    field = exported["packet_projection"]["fields"][application["field_id"]]
    assert field == {
        "target_path": "analysis.current_summary",
        "value": "Keep the decision reversible.",
    }
    assert application["operator_visible_proposal_hash"] == proposal_hash
    assert application["requested_change_hash"] == canonical_hash(change)
    application_schema = json.loads(
        (
            ROOT
            / "interop"
            / "schemas"
            / "nepsis.proposal_application@0.1.0.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(application_schema).validate(application)
    assert exported["postcondition"]["phase"] == "committed"
    report = _verify_actualization_export(exported)
    assert report["decision_committed"] == 1
    assert report["still_released"] == 1
    protected_report = verify_protected_canonical_run_export(
        service.export_run(
            run_id="run-001", actor=operator_actor("export_run")
        )
    )
    assert "canonical_actualization_lifecycle" in protected_report[
        "verified_checks"
    ]

    tampered = deepcopy(exported)
    tampered["events"][-1]["payload"]["packet_projection"]["fields"][
        application["field_id"]
    ]["value"] = "Tampered after validator application."
    tampered["packet_projection"] = deepcopy(
        tampered["events"][-1]["payload"]["packet_projection"]
    )
    with pytest.raises(
        CanonicalActualizationVerificationError,
        match="proposal application projection mismatch",
    ):
        _verify_actualization_export(tampered)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            "substitute_requester",
            "validator event requester does not match its receipt actor",
        ),
        (
            "substitute_receipt_authority",
            "decision commit receipt must be operator-authored",
        ),
        (
            "substitute_event_authority",
            "decision commit event must be validator-authored",
        ),
    ],
)
def test_protected_export_rejects_resigned_commit_identity_substitution(
    mutation: str, message: str
) -> None:
    exported = _actualized_protected_export()
    event = exported["events"][-1]
    outcome = exported["outcomes"][-1]
    if mutation == "substitute_requester":
        event["payload"]["requested_by_actor_id"] = "operator:substituted"
    elif mutation == "substitute_receipt_authority":
        outcome["actor_id"] = "model:substituted"
        outcome["provenance_class"] = "model"
        event["payload"]["requested_by_actor_id"] = "model:substituted"
    else:
        event["actor_id"] = "operator:substituted"
        event["provenance_class"] = "operator"
    _resign_rerooted_terminal_export(exported)

    with pytest.raises(CanonicalRunExportVerificationError, match=message):
        verify_protected_canonical_run_export(exported)


def test_commit_rejects_requested_change_substitution_before_append() -> None:
    service, store = service_and_store()
    change, proposal_hash = _candidate(service)
    _accept(service, store, proposal_hash)
    _operator_action(
        service,
        store,
        capability="release_still",
        action_type=RELEASE_STILL_ACTION_TYPE,
        payload={
            "operator_visible_proposal_hash": proposal_hash,
            "run_id": "run-001",
        },
        created_at=RELEASE_AT,
        idempotency_key="release-substitution-001",
        validator=validate_release_still,
    )
    tampered = deepcopy(change)
    tampered["proposed_value"] = "Substituted after acceptance."
    before = len(store.export_run("run-001")["events"])

    with pytest.raises(CanonicalRunServiceError, match="proposal artifact"):
        _operator_action(
            service,
            store,
            capability="request_decision_commit",
            action_type=REQUEST_DECISION_COMMIT_ACTION_TYPE,
            payload={
                "operator_visible_proposal_hash": proposal_hash,
                "requested_change": tampered,
                "run_id": "run-001",
            },
            created_at=COMMIT_AT,
            idempotency_key="substituted-commit",
            validator=validate_decision_commit,
        )
    assert len(store.export_run("run-001")["events"]) == before


def test_zeroback_reframes_but_preserves_evidence_and_protected_blockers() -> None:
    service, store = service_and_store()
    before = store.get_snapshot("run-001")
    context_before = before["packet_projection"]["context_state"]
    replacement = hashlib.sha256(b"replacement-frame").hexdigest()

    result = _operator_action(
        service,
        store,
        capability="perform_zeroback",
        action_type=PERFORM_ZEROBACK_ACTION_TYPE,
        payload={
            "replacement_frame_root_hash": replacement,
            "run_id": "run-001",
        },
        created_at=ZEROBACK_AT,
        idempotency_key="zeroback-001",
        validator=validate_zeroback,
    )
    after = store.get_snapshot("run-001")
    context_after = after["packet_projection"]["context_state"]
    zeroback = after["packet_projection"]["zeroback_state"]

    assert result.receipt["outcome"] == "committed"
    assert context_after["frame_root_hash"] == replacement
    for field in (
        "evidence_root_hash",
        "observation_root_hash",
        "population_root_hash",
        "unresolved_contradiction_hashes",
        "unresolved_red_hazard_hashes",
    ):
        assert context_after[field] == context_before[field]
    assert zeroback["prior_frame_root_hash"] == context_before["frame_root_hash"]
    zeroback_schema = json.loads(
        (
            ROOT
            / "interop"
            / "schemas"
            / "nepsis.zeroback_state@0.1.0.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(zeroback_schema).validate(zeroback)
    assert after["postcondition"]["active_hold"] is True
    assert after["postcondition"]["phase"] == "zeroback"
    report = _verify_actualization_export(store.export_run("run-001"))
    assert report["zeroback_performed"] == 1


def test_checked_in_actualization_policy_matches_hashed_runtime_policy() -> None:
    path = (
        ROOT
        / "interop"
        / "policies"
        / "nepsis.canonical_actualization_policy@0.1.0.json"
    )
    checked_in = json.loads(path.read_text(encoding="utf-8"))
    assert checked_in == CANONICAL_ACTUALIZATION_POLICY
    assert canonical_hash(checked_in) == CANONICAL_ACTUALIZATION_POLICY_HASH
