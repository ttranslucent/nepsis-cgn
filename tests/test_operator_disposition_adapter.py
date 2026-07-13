from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from nepsis_cgn.canonical_runs.operator_disposition import (
    OPERATOR_DISPOSITION_ACTION_TYPE,
    OPERATOR_DISPOSITION_POLICY,
    OPERATOR_DISPOSITION_POLICY_BINDING,
    OPERATOR_DISPOSITION_POLICY_HASH,
    OPERATOR_DISPOSITION_VALIDATOR_BINDING,
    OperatorDispositionAdapterError,
    validate_operator_disposition,
)
from nepsis_cgn.canonical_runs.service import CanonicalRunServiceError
from nepsis_cgn.contracts.canonical_json import canonical_hash
from tests.test_canonical_run_service import (
    EFFECTIVE_POLICY_HASH,
    PROFILE_HASH,
    SNAPSHOT_HASH,
    candidate_inputs,
    model_actor,
    operator_actor,
    proposal,
    service_and_store,
    submit_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
DISPOSITION_AT = "2026-07-12T16:02:00.000Z"


def _record_disposition(
    service,
    store,
    *,
    disposition: str = "defer",
    proposal_hash: str | None = None,
    expected_head_sequence: int | None = None,
    expected_head_event_hash: str | None = None,
    idempotency_key: str = "disposition-001",
):
    snapshot = store.get_snapshot("run-001")
    exact_hash = proposal_hash or canonical_hash(proposal())
    confirmation = {
        "confirmed": True,
        "confirmed_at": DISPOSITION_AT,
        "consequence_acknowledged": True,
        "rationale": "Reviewed the exact displayed proposal and hazards.",
    }
    return service.submit_operator_action(
        actor=operator_actor("submit_operator_disposition"),
        capability="submit_operator_disposition",
        action_type=OPERATOR_DISPOSITION_ACTION_TYPE,
        payload={
            "disposition": disposition,
            "operator_visible_proposal_hash": exact_hash,
            "run_id": "run-001",
        },
        confirmation=confirmation,
        created_at=DISPOSITION_AT,
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        expected_head_event_hash=(
            snapshot["head_event_hash"]
            if expected_head_event_hash is None
            else expected_head_event_hash
        ),
        expected_head_sequence=(
            snapshot["head_sequence"]
            if expected_head_sequence is None
            else expected_head_sequence
        ),
        idempotency_key=idempotency_key,
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=SNAPSHOT_HASH,
        trusted_adapter_intent_id=f"adapter:{idempotency_key}",
        validator=validate_operator_disposition,
    )


def _pending_run():
    service, store = service_and_store()
    context, visible, external = candidate_inputs(service)
    candidate = submit_candidate(
        service,
        context=context,
        visible=visible,
        external=external,
    )
    return service, store, visible, candidate


@pytest.mark.parametrize(
    ("disposition", "terminal_status"),
    [("accept", "accepted"), ("reject", "rejected"), ("defer", "deferred")],
)
def test_exact_disposition_records_lifecycle_without_applying_requested_change(
    disposition: str, terminal_status: str
) -> None:
    service, store, visible, candidate = _pending_run()
    proposal_hash = canonical_hash(visible)
    after_candidate = store.get_snapshot("run-001")
    pending = after_candidate["packet_projection"]["operator_proposal_state"]

    assert candidate.receipt["outcome"] == "candidate_recorded"
    assert pending == {
        "adapter_version": "nepsis.operator_disposition_adapter@0.1.0",
        "candidate_created_at": "2026-07-12T16:01:00.000Z",
        "candidate_intent_hash": candidate.receipt["intent_hash"],
        "operator_proposal_state_schema_version": (
            "nepsis.operator_proposal_state@0.1.0"
        ),
        "operator_visible_proposal_hash": proposal_hash,
        "policy_hash": OPERATOR_DISPOSITION_POLICY_HASH,
        "policy_version": "nepsis.operator_disposition_policy@0.1.0",
        "status": "pending",
    }
    _validate_state_schema(pending)

    result = _record_disposition(
        service,
        store,
        disposition=disposition,
        proposal_hash=proposal_hash,
        expected_head_sequence=after_candidate["head_sequence"],
        expected_head_event_hash=after_candidate["head_event_hash"],
    )
    replay = _record_disposition(
        service,
        store,
        disposition=disposition,
        proposal_hash=proposal_hash,
        expected_head_sequence=after_candidate["head_sequence"],
        expected_head_event_hash=after_candidate["head_event_hash"],
    )
    exported = store.export_run("run-001")
    event = exported["events"][-1]
    terminal = exported["packet_projection"]["operator_proposal_state"]

    assert result.receipt["outcome"] == "committed"
    assert result.replayed is False
    assert replay.replayed is True
    assert replay.receipt == result.receipt
    assert event["event_type"] == "operator_proposal_disposition_recorded"
    assert event["provenance_class"] == "operator"
    assert event["caused_by_artifact_hashes"] == [proposal_hash]
    assert event["payload"]["validator_binding"] == (
        OPERATOR_DISPOSITION_VALIDATOR_BINDING
    )
    assert terminal["status"] == terminal_status
    assert terminal["operator_visible_proposal_hash"] == proposal_hash
    assert terminal["candidate_intent_hash"] == pending["candidate_intent_hash"]
    assert terminal["disposition_intent_hash"] == event["intent_hash"]
    assert terminal["operator_confirmation_hash"] == canonical_hash(
        event["payload"]["operator_confirmation"]
    )
    _validate_state_schema(terminal)

    intent_preimage = {
        "action": OPERATOR_DISPOSITION_ACTION_TYPE,
        "capability": "submit_operator_disposition",
        "operator_confirmation": event["payload"]["operator_confirmation"],
        "payload": event["payload"]["action_payload"],
    }
    assert event["intent_hash"] == canonical_hash(intent_preimage)
    before_without_state = {
        key: value
        for key, value in after_candidate["packet_projection"].items()
        if key != "operator_proposal_state"
    }
    after_without_state = {
        key: value
        for key, value in exported["packet_projection"].items()
        if key != "operator_proposal_state"
    }
    assert after_without_state == before_without_state
    assert "candidate" not in exported["packet_projection"]
    assert exported["postcondition"]["phase"] == (
        "proposal_review" if disposition == "accept" else "intake"
    )
    assert exported["postcondition"]["governance_status"] == (
        "proposal_accepted" if disposition == "accept" else "open"
    )
    assert exported["postcondition"]["active_hold"] is (
        disposition == "accept"
    )


def test_wrong_proposal_hash_is_audited_refusal_and_preserves_pending_state() -> None:
    service, store, _, _ = _pending_run()
    before = store.get_snapshot("run-001")
    existing_context_hash = next(
        row["artifact_hash"]
        for row in store.export_run("run-001")["artifacts"]
        if row["artifact_schema_version"] == "nepsis.context_manifest@0.1.0"
    )

    result = _record_disposition(
        service,
        store,
        proposal_hash=existing_context_hash,
        idempotency_key="wrong-proposal",
    )
    after = store.get_snapshot("run-001")

    assert result.receipt["outcome"] == "refused"
    assert result.receipt["reason_code"] == "operator_proposal_hash_mismatch"
    assert after["packet_projection"] == before["packet_projection"]
    assert store.export_run("run-001")["events"][-1]["event_type"] == (
        "validator_refusal_created"
    )


def test_missing_proposal_artifact_is_nonmutating_invalid_request() -> None:
    service, store, _, _ = _pending_run()
    before = store.export_run("run-001")

    result = _record_disposition(
        service,
        store,
        proposal_hash="f" * 64,
        idempotency_key="missing-proposal",
    )
    replay = _record_disposition(
        service,
        store,
        proposal_hash="f" * 64,
        idempotency_key="missing-proposal",
    )
    after = store.export_run("run-001")

    assert result.receipt["outcome"] == "invalid_request"
    assert result.receipt["advanced_head"] is False
    assert replay.replayed is True
    assert replay.receipt == result.receipt
    assert "referenced artifact is unavailable" in result.receipt["detail"]
    assert after["events"] == before["events"]
    assert after["packet_projection"] == before["packet_projection"]


def test_second_disposition_is_refused_and_cannot_change_terminal_state() -> None:
    service, store, visible, _ = _pending_run()
    proposal_hash = canonical_hash(visible)
    first = _record_disposition(service, store, proposal_hash=proposal_hash)
    after_first = store.get_snapshot("run-001")
    second = _record_disposition(
        service,
        store,
        disposition="accept",
        proposal_hash=proposal_hash,
        idempotency_key="second-disposition",
    )

    assert first.receipt["outcome"] == "committed"
    assert second.receipt["outcome"] == "refused"
    assert second.receipt["reason_code"] == "pending_operator_proposal_required"
    assert store.get_snapshot("run-001")["packet_projection"] == after_first[
        "packet_projection"
    ]


def test_pending_candidate_cannot_be_silently_replaced() -> None:
    service, store, _, _ = _pending_run()
    before = store.get_snapshot("run-001")
    context = dict(
        service.build_context_manifest(
            run_id="run-001",
            actor=operator_actor("read_snapshot"),
        ).artifact
    )
    replacement = proposal()
    replacement["proposal_text"] = "A different pending proposal."
    replacement_hash = canonical_hash(replacement)
    external = service.build_external_codex_ref(
        actor=model_actor(),
        run_id="run-001",
        adapter_version="adapter-0.1.0",
        created_at="2026-07-12T16:03:00.000Z",
        thread_id="thread-001",
        turn_id="turn-002",
        tool_call_id="tool-002",
        model_id="gpt-test",
        model_configuration_epoch="model-config-001",
        operator_visible_proposal_hash=replacement_hash,
    )
    refused = service.submit_model_candidate(
        actor=model_actor(),
        context_manifest=context,
        operator_visible_proposal=replacement,
        external_codex_ref=external,
        created_at="2026-07-12T16:03:00.000Z",
        idempotency_key="replacement-candidate",
        trusted_adapter_intent_id="adapter:replacement-candidate",
    )

    assert refused.receipt["outcome"] == "refused"
    assert refused.receipt["reason_code"] == "pending_operator_proposal_exists"
    assert store.get_snapshot("run-001")["packet_projection"] == before[
        "packet_projection"
    ]


def test_stale_disposition_does_not_append_or_change_projection() -> None:
    service, store, visible, candidate = _pending_run()
    proposal_hash = canonical_hash(visible)
    _record_disposition(service, store, proposal_hash=proposal_hash)
    before = store.export_run("run-001")

    stale = _record_disposition(
        service,
        store,
        proposal_hash=proposal_hash,
        expected_head_sequence=candidate.receipt["resulting_head_sequence"],
        expected_head_event_hash=candidate.receipt["resulting_head_event_hash"],
        idempotency_key="stale-disposition",
    )
    after = store.export_run("run-001")

    assert stale.receipt["outcome"] == "stale_head"
    assert stale.receipt["advanced_head"] is False
    assert after["events"] == before["events"]
    assert after["packet_projection"] == before["packet_projection"]


@pytest.mark.parametrize(
    "payload_change",
    [
        {"extra": True},
        {"operator_visible_proposal_hash": None},
        {"disposition": "apply"},
    ],
)
def test_malformed_disposition_is_rejected_before_append(
    payload_change: dict[str, object]
) -> None:
    service, store, visible, _ = _pending_run()
    proposal_hash = canonical_hash(visible)
    snapshot = store.get_snapshot("run-001")
    payload = {
        "disposition": "defer",
        "operator_visible_proposal_hash": proposal_hash,
        "run_id": "run-001",
        **payload_change,
    }
    if payload_change.get("operator_visible_proposal_hash") is None:
        payload.pop("operator_visible_proposal_hash")
    before = len(store.export_run("run-001")["events"])

    with pytest.raises(CanonicalRunServiceError):
        service.submit_operator_action(
            actor=operator_actor("submit_operator_disposition"),
            capability="submit_operator_disposition",
            action_type=OPERATOR_DISPOSITION_ACTION_TYPE,
            payload=payload,
            confirmation={
                "confirmed": True,
                "confirmed_at": DISPOSITION_AT,
                "consequence_acknowledged": True,
                "rationale": "Reviewed.",
            },
            created_at=DISPOSITION_AT,
            effective_policy_hash=EFFECTIVE_POLICY_HASH,
            expected_head_event_hash=snapshot["head_event_hash"],
            expected_head_sequence=snapshot["head_sequence"],
            idempotency_key="malformed",
            operator_governance_profile_hash=PROFILE_HASH,
            session_governance_snapshot_hash=SNAPSHOT_HASH,
            trusted_adapter_intent_id="adapter:malformed",
            validator=validate_operator_disposition,
        )
    assert len(store.export_run("run-001")["events"]) == before


def test_adapter_fails_closed_for_unbound_policy_and_malformed_state() -> None:
    service, store = service_and_store()
    snapshot = store.get_snapshot("run-001")
    snapshot["system_policy_bindings"] = []
    request = {
        "action_type": OPERATOR_DISPOSITION_ACTION_TYPE,
        "artifact_hashes": ["a" * 64],
        "capability": "submit_operator_disposition",
        "created_at": DISPOSITION_AT,
        "intent_hash": "b" * 64,
        "operator_confirmation": {
            "confirmed": True,
            "confirmed_at": DISPOSITION_AT,
            "consequence_acknowledged": True,
            "rationale": "Reviewed.",
        },
        "operator_visible_proposal_hash": "a" * 64,
        "payload": {
            "disposition": "defer",
            "operator_visible_proposal_hash": "a" * 64,
            "run_id": "run-001",
        },
    }
    unbound = validate_operator_disposition(request, snapshot)
    assert unbound.admitted is False
    assert unbound.reason_code == "operator_disposition_policy_unbound"

    snapshot["system_policy_bindings"] = [OPERATOR_DISPOSITION_POLICY_BINDING]
    snapshot["packet_projection"]["operator_proposal_state"] = {
        "operator_proposal_state_schema_version": (
            "nepsis.operator_proposal_state@0.1.0"
        ),
        "status": "pending",
    }
    with pytest.raises(OperatorDispositionAdapterError, match="fields are not closed"):
        validate_operator_disposition(request, snapshot)


def test_checked_in_policy_is_the_exact_hashed_adapter_policy() -> None:
    path = (
        ROOT
        / "interop"
        / "policies"
        / "nepsis.operator_disposition_policy@0.1.0.json"
    )
    checked_in = json.loads(path.read_text(encoding="utf-8"))
    assert checked_in == OPERATOR_DISPOSITION_POLICY
    assert canonical_hash(checked_in) == OPERATOR_DISPOSITION_POLICY_HASH


def test_run_creation_cannot_forge_a_pending_operator_proposal_state() -> None:
    service, store = service_and_store()
    snapshot = store.get_snapshot("run-001")
    forged_packet = {
        **snapshot["packet_projection"],
        "operator_proposal_state": {
            "operator_proposal_state_schema_version": (
                "nepsis.operator_proposal_state@0.1.0"
            ),
            "status": "pending",
        },
    }
    with pytest.raises(CanonicalRunServiceError, match="recorded model candidate"):
        service.create_run(
            actor=operator_actor("create_run"),
            run_id="run-forged-proposal",
            owner_id="operator:local",
            created_at="2026-07-12T16:04:00.000Z",
            idempotency_key="create-forged-proposal",
            operator_governance_profile_hash=PROFILE_HASH,
            session_governance_snapshot_hash=SNAPSHOT_HASH,
            effective_policy_hash=EFFECTIVE_POLICY_HASH,
            system_policy_bindings=[OPERATOR_DISPOSITION_POLICY_BINDING],
            initial_packet_projection=forged_packet,
            initial_postcondition={
                "active_hold": False,
                "governance_status": "open",
                "packet_projection_hash": canonical_hash(forged_packet),
                "phase": "intake",
            },
        )


def _validate_state_schema(state: dict[str, object]) -> None:
    path = (
        ROOT
        / "interop"
        / "schemas"
        / "nepsis.operator_proposal_state@0.1.0.schema.json"
    )
    Draft202012Validator(json.loads(path.read_text(encoding="utf-8"))).validate(
        state
    )
