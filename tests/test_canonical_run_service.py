from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator

from nepsis_cgn.canonical_runs.service import (
    CanonicalRunService,
    CanonicalRunServiceError,
    ContextRefusal,
    GOVERNANCE_POLICY_DIFF_VERSION,
    OPERATOR_VISIBLE_PROPOSAL_VERSION,
)
from nepsis_cgn.canonical_runs.operator_disposition import (
    OPERATOR_DISPOSITION_POLICY_BINDING,
)
from nepsis_cgn.canonical_runs.actualization import (
    CANONICAL_ACTUALIZATION_POLICY_BINDING,
)
from nepsis_cgn.canonical_runs.store import AdmissionDecision, CanonicalRunStore
from nepsis_cgn.contracts.canonical_json import canonical_bytes, canonical_hash
from nepsis_cgn.contracts.canonical_run import ActorContext
from nepsis_cgn.verification.receipts import build_trust_anchor


CREATED_AT = "2026-07-12T16:00:00.000Z"
ACTION_AT = "2026-07-12T16:01:00.000Z"
PROFILE_HASH = hashlib.sha256(b"profile").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"snapshot").hexdigest()
EFFECTIVE_POLICY_HASH = hashlib.sha256(b"effective-policy").hexdigest()
POLICY_HASH = hashlib.sha256(b"system-policy").hexdigest()
PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
ROOT = Path(__file__).resolve().parents[1]


def context_state() -> dict[str, object]:
    return {
        "data_classification": "synthetic",
        "denominator_collapse_active": False,
        "evidence_root_hash": hashlib.sha256(b"evidence-root").hexdigest(),
        "frame_root_hash": hashlib.sha256(b"frame-root").hexdigest(),
        "observation_root_hash": hashlib.sha256(b"observation-root").hexdigest(),
        "population_root_hash": hashlib.sha256(b"population-root").hexdigest(),
        "relevant_artifact_revisions": [],
        "remote_inference_authorized": False,
        "unresolved_contradiction_hashes": [],
        "unresolved_red_hazard_hashes": [],
    }


def operator_actor(*capabilities: str) -> ActorContext:
    return ActorContext(
        actor_id="operator:local",
        provenance_class="operator",
        capability_id="cap-operator",
        capabilities=frozenset(capabilities),
    )


def model_actor() -> ActorContext:
    return ActorContext(
        actor_id="model:codex",
        provenance_class="model",
        capability_id="cap-model",
        capabilities=frozenset({"submit_model_candidate"}),
    )


def service_and_store() -> tuple[CanonicalRunService, CanonicalRunStore]:
    store = CanonicalRunStore.in_memory()
    anchor = build_trust_anchor(
        PRIVATE_KEY.public_key(), activated_at="2026-07-01T00:00:00.000Z"
    )
    service = CanonicalRunService(
        store=store,
        private_key=PRIVATE_KEY,
        trust_anchor=anchor,
    )
    packet = {
        "context_state": context_state(),
        "packet_schema_version": "nepsis.test_packet@0.1.0",
        "revision": 0,
    }
    result = service.create_run(
        actor=operator_actor("create_run"),
        run_id="run-001",
        owner_id="operator:local",
        created_at=CREATED_AT,
        idempotency_key="create-001",
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=SNAPSHOT_HASH,
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        system_policy_bindings=[
            {
                "policy_hash": POLICY_HASH,
                "policy_id": "canonical-run",
                "policy_version": "nepsis.canonical_run_policy@0.1.0",
            },
            OPERATOR_DISPOSITION_POLICY_BINDING,
            CANONICAL_ACTUALIZATION_POLICY_BINDING,
        ],
        initial_packet_projection=packet,
        initial_postcondition={
            "active_hold": False,
            "governance_status": "open",
            "packet_projection_hash": canonical_hash(packet),
            "phase": "intake",
        },
    )
    assert service.verify_receipt(result.receipt)
    return service, store


def fork_parent_run(
    service: CanonicalRunService, store: CanonicalRunStore
) -> None:
    parent = store.get_snapshot("run-001")
    reason = "The predecessor Codex thread is irrecoverable."
    policy_diff = {
        "changes": [],
        "child_run_id": "run-002",
        "fork_reason": reason,
        "from_effective_policy_hash": EFFECTIVE_POLICY_HASH,
        "governance_policy_diff_schema_version": GOVERNANCE_POLICY_DIFF_VERSION,
        "operator_confirmation": {
            "confirmed": True,
            "confirmed_at": ACTION_AT,
            "consequence_acknowledged": True,
            "rationale": "Freeze the predecessor and create a distinct successor.",
        },
        "parent_run_id": "run-001",
        "to_effective_policy_hash": EFFECTIVE_POLICY_HASH,
    }
    artifact_envelope = {
        "artifact": policy_diff,
        "artifact_schema_version": GOVERNANCE_POLICY_DIFF_VERSION,
        "roles": ["policy_diff"],
    }
    provenance = {
        "fork_reason": reason,
        "forked_from_run_id": "run-001",
        "inherited_evidence_root_hashes": [],
        "parent_head_event_hash": parent["head_event_hash"],
        "policy_diff_artifact_hash": canonical_hash(policy_diff),
    }
    result = service.create_run(
        actor=operator_actor("create_run"),
        run_id="run-002",
        owner_id="operator:local",
        created_at=ACTION_AT,
        idempotency_key="create-002",
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=hashlib.sha256(
            b"snapshot-child"
        ).hexdigest(),
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        system_policy_bindings=[
            {
                "policy_hash": POLICY_HASH,
                "policy_id": "canonical-run",
                "policy_version": "nepsis.canonical_run_policy@0.1.0",
            },
            OPERATOR_DISPOSITION_POLICY_BINDING,
        ],
        initial_packet_projection=parent["packet_projection"],
        initial_postcondition=parent["postcondition"],
        fork_provenance=provenance,
        fork_policy_diff_artifact=artifact_envelope,
    )
    assert service.verify_receipt(result.receipt)


def test_active_writer_refuses_a_revoked_receipt_anchor() -> None:
    anchor = build_trust_anchor(
        PRIVATE_KEY.public_key(),
        activated_at="2026-07-01T00:00:00.000Z",
        revoked_at="2026-07-11T00:00:00.000Z",
    )

    with pytest.raises(CanonicalRunServiceError, match="revoked trust anchor"):
        CanonicalRunService(
            store=CanonicalRunStore.in_memory(),
            private_key=PRIVATE_KEY,
            trust_anchor=anchor,
        )


def test_service_fork_requires_confirmed_policy_diff_and_signs_child_genesis() -> None:
    service, store = service_and_store()
    parent = store.get_snapshot("run-001")
    reason = "The predecessor Codex thread is irrecoverable."
    policy_diff = {
        "changes": [],
        "child_run_id": "run-002",
        "fork_reason": reason,
        "from_effective_policy_hash": EFFECTIVE_POLICY_HASH,
        "governance_policy_diff_schema_version": GOVERNANCE_POLICY_DIFF_VERSION,
        "operator_confirmation": {
            "confirmed": True,
            "confirmed_at": ACTION_AT,
            "consequence_acknowledged": True,
            "rationale": "Freeze the predecessor and create a distinct successor.",
        },
        "parent_run_id": "run-001",
        "to_effective_policy_hash": EFFECTIVE_POLICY_HASH,
    }
    artifact_envelope = {
        "artifact": policy_diff,
        "artifact_schema_version": GOVERNANCE_POLICY_DIFF_VERSION,
        "roles": ["policy_diff"],
    }
    provenance = {
        "fork_reason": reason,
        "forked_from_run_id": "run-001",
        "inherited_evidence_root_hashes": [],
        "parent_head_event_hash": parent["head_event_hash"],
        "policy_diff_artifact_hash": canonical_hash(policy_diff),
    }

    result = service.create_run(
        actor=operator_actor("create_run"),
        run_id="run-002",
        owner_id="operator:local",
        created_at=ACTION_AT,
        idempotency_key="create-002",
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=hashlib.sha256(
            b"snapshot-child"
        ).hexdigest(),
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        system_policy_bindings=[
            {
                "policy_hash": POLICY_HASH,
                "policy_id": "canonical-run",
                "policy_version": "nepsis.canonical_run_policy@0.1.0",
            },
            OPERATOR_DISPOSITION_POLICY_BINDING,
        ],
        initial_packet_projection=parent["packet_projection"],
        initial_postcondition=parent["postcondition"],
        fork_provenance=provenance,
        fork_policy_diff_artifact=artifact_envelope,
    )

    assert service.verify_receipt(result.receipt)
    assert result.receipt["artifact_hashes"] == [canonical_hash(policy_diff)]
    assert store.get_snapshot("run-001")["status"] == "read_only"
    assert store.get_snapshot("run-002")["fork_provenance"] == provenance
    parent_export = service.export_run(
        run_id="run-001", actor=operator_actor("export_run")
    )
    parent_receipt = parent_export["action_receipts"][-1]
    assert parent_receipt["capability"] == "fork_run"
    assert parent_receipt["event_hash"] == parent_export["events"][-1]["event_hash"]
    assert service.verify_receipt(parent_receipt)

    malformed = deepcopy(artifact_envelope)
    malformed["artifact"]["operator_confirmation"]["confirmed"] = False
    with pytest.raises(CanonicalRunServiceError, match="affirmative"):
        service.create_run(
            actor=operator_actor("create_run"),
            run_id="run-002",
            owner_id="operator:local",
            created_at=ACTION_AT,
            idempotency_key="create-002",
            operator_governance_profile_hash=PROFILE_HASH,
            session_governance_snapshot_hash=hashlib.sha256(
                b"snapshot-child"
            ).hexdigest(),
            effective_policy_hash=EFFECTIVE_POLICY_HASH,
            system_policy_bindings=[
                {
                    "policy_hash": POLICY_HASH,
                    "policy_id": "canonical-run",
                    "policy_version": "nepsis.canonical_run_policy@0.1.0",
                },
                OPERATOR_DISPOSITION_POLICY_BINDING,
            ],
            initial_packet_projection=parent["packet_projection"],
            initial_postcondition=parent["postcondition"],
            fork_provenance=provenance,
            fork_policy_diff_artifact=malformed,
        )


def proposal() -> dict[str, object]:
    return {
        "alternatives_summary": "Option B remains available.",
        "evidence_refs": [],
        "hazards_summary": "Hazard A remains unresolved.",
        "operator_visible_proposal_schema_version": OPERATOR_VISIBLE_PROPOSAL_VERSION,
        "proposal_text": "Consider option A.",
        "rationale_text": "Option A remains reversible.",
        "requested_change": {"candidate": "option_a"},
    }


def candidate_inputs(
    service: CanonicalRunService,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    context = dict(
        service.build_context_manifest(
            run_id="run-001",
            actor=ActorContext(
                actor_id="model:codex",
                provenance_class="model",
                capability_id="cap-model-read",
                capabilities=frozenset({"read_snapshot"}),
            ),
        ).artifact
    )
    visible = proposal()
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
        operator_visible_proposal_hash=canonical_hash(visible),
    )
    return context, visible, external


def submit_candidate(
    service: CanonicalRunService,
    *,
    context: dict[str, object],
    visible: dict[str, object],
    external: dict[str, object],
):
    return service.submit_model_candidate(
        actor=model_actor(),
        context_manifest=context,
        operator_visible_proposal=visible,
        external_codex_ref=external,
        created_at=ACTION_AT,
        idempotency_key="candidate-001",
        trusted_adapter_intent_id="adapter-intent-001",
    )


def test_create_and_candidate_replay_issue_byte_identical_signed_receipts() -> None:
    service, store = service_and_store()
    context, visible, external = candidate_inputs(service)

    first = submit_candidate(
        service, context=context, visible=visible, external=external
    )
    replay = submit_candidate(
        service, context=context, visible=visible, external=external
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert canonical_bytes(dict(first.receipt)) == canonical_bytes(dict(replay.receipt))
    assert "replayed" not in first.receipt
    assert "replayed" not in replay.receipt
    assert service.verify_receipt(first.receipt)
    assert first.receipt["outcome"] == "candidate_recorded"
    exported = store.export_run("run-001")
    assert len(exported["events"]) == 2
    by_schema = {
        row["artifact_schema_version"]: row for row in exported["artifacts"]
    }
    assert set(by_schema) == {
        "nepsis.context_manifest@0.1.0",
        "nepsis.external_codex_ref@0.1.0",
        "nepsis.operator_visible_proposal@0.1.0",
    }
    assert by_schema["nepsis.context_manifest@0.1.0"]["artifact"] == context
    assert by_schema["nepsis.operator_visible_proposal@0.1.0"]["artifact"] == visible
    assert by_schema["nepsis.external_codex_ref@0.1.0"]["artifact"] == external
    assert external["thread_id"] == "thread-001"
    assert external["turn_id"] == "turn-001"
    assert external["tool_call_id"] == "tool-001"
    assert external["capability"] == "submit_model_candidate"
    assert external["operator_visible_proposal_hash"] == canonical_hash(visible)
    _validate_schema("nepsis.context_manifest@0.1.0", context)
    _validate_schema("nepsis.operator_visible_proposal@0.1.0", visible)
    _validate_schema("nepsis.external_codex_ref@0.1.0", external)
    _validate_schema("nepsis.action_receipt@0.1.0", dict(first.receipt))


def test_protected_export_binds_every_persisted_outcome_to_signed_receipt() -> None:
    service, _ = service_and_store()
    context, visible, external = candidate_inputs(service)
    submit_candidate(
        service,
        context=context,
        visible=visible,
        external=external,
    )

    exported = dict(
        service.export_run(
            run_id="run-001",
            actor=operator_actor("export_run"),
        )
    )
    root = exported.pop("export_root_hash")

    assert root == canonical_hash(exported)
    assert exported["protected_export_schema_version"] == (
        "nepsis.canonical_run_protected_export@0.1.0"
    )
    assert len(exported["outcomes"]) == len(exported["action_receipts"]) == 2
    assert all(service.verify_receipt(row) for row in exported["action_receipts"])
    assert [row["request_hash"] for row in exported["action_receipts"]] == [
        row["request_hash"] for row in exported["outcomes"]
    ]
    assert exported["receipt_trust_anchor"]["key_id"] == exported[
        "action_receipts"
    ][0]["signature"]["key_id"]


def test_create_replay_is_byte_identical_and_replay_is_delivery_metadata() -> None:
    store = CanonicalRunStore.in_memory()
    service = CanonicalRunService(
        store=store,
        private_key=PRIVATE_KEY,
        trust_anchor=build_trust_anchor(
            PRIVATE_KEY.public_key(), activated_at="2026-07-01T00:00:00.000Z"
        ),
    )
    kwargs = {
        "actor": operator_actor("create_run"),
        "run_id": "run-create-replay",
        "owner_id": "operator:local",
        "created_at": CREATED_AT,
        "idempotency_key": "create-replay",
        "operator_governance_profile_hash": PROFILE_HASH,
        "session_governance_snapshot_hash": SNAPSHOT_HASH,
        "effective_policy_hash": EFFECTIVE_POLICY_HASH,
        "system_policy_bindings": [
            {
                "policy_hash": POLICY_HASH,
                "policy_id": "canonical-run",
                "policy_version": "nepsis.canonical_run_policy@0.1.0",
            }
        ],
        "initial_packet_projection": {"revision": 0},
        "initial_postcondition": {
            "active_hold": False,
            "governance_status": "open",
            "packet_projection_hash": canonical_hash({"revision": 0}),
            "phase": "intake",
        },
    }
    first = service.create_run(**kwargs)
    replay = service.create_run(**kwargs)
    assert first.replayed is False
    assert replay.replayed is True
    assert canonical_bytes(dict(first.receipt)) == canonical_bytes(dict(replay.receipt))
    assert "replayed" not in replay.receipt


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_head_event_hash", "0" * 64),
        ("packet_projection_hash", "1" * 64),
        ("operator_governance_profile_hash", "2" * 64),
        ("session_governance_snapshot_hash", "3" * 64),
        ("effective_policy_hash", "4" * 64),
        ("generator", {"actor_id": "model:codex"}),
    ],
)
def test_stale_or_model_authored_context_is_refused_without_event(
    field: str, value: object
) -> None:
    service, store = service_and_store()
    context, visible, external = candidate_inputs(service)
    context[field] = value
    before = len(store.export_run("run-001")["events"])

    with pytest.raises(CanonicalRunServiceError):
        submit_candidate(
            service, context=context, visible=visible, external=external
        )

    assert len(store.export_run("run-001")["events"]) == before


def test_selectively_omitted_context_is_refused_without_event() -> None:
    service, store = service_and_store()
    context, visible, external = candidate_inputs(service)
    context.pop("frame_root_hash")
    before = len(store.export_run("run-001")["events"])
    with pytest.raises(CanonicalRunServiceError):
        submit_candidate(
            service, context=context, visible=visible, external=external
        )
    assert len(store.export_run("run-001")["events"]) == before


@pytest.mark.parametrize(
    "field",
    ["thread_id", "turn_id", "tool_call_id", "capability", "operator_visible_proposal_hash"],
)
def test_external_codex_ref_requires_exact_origin_and_proposal_binding(
    field: str,
) -> None:
    service, store = service_and_store()
    context, visible, external = candidate_inputs(service)
    external.pop(field)
    before = len(store.export_run("run-001")["events"])
    with pytest.raises(CanonicalRunServiceError):
        submit_candidate(
            service, context=context, visible=visible, external=external
        )
    assert len(store.export_run("run-001")["events"]) == before


def test_proposal_tamper_after_adapter_stamp_is_refused_without_event() -> None:
    service, store = service_and_store()
    context, visible, external = candidate_inputs(service)
    visible["proposal_text"] = "Changed after adapter stamp."
    before = len(store.export_run("run-001")["events"])
    with pytest.raises(CanonicalRunServiceError, match="proposal_hash"):
        submit_candidate(
            service, context=context, visible=visible, external=external
        )
    assert len(store.export_run("run-001")["events"]) == before


def test_old_manifest_after_operator_advance_is_stale_and_appends_no_candidate() -> None:
    service, store = service_and_store()
    context, visible, external = candidate_inputs(service)
    confirmation = {
        "confirmed": True,
        "confirmed_at": ACTION_AT,
        "consequence_acknowledged": True,
        "rationale": "Operator reviewed the scoped change.",
    }
    replacement_frame = hashlib.sha256(b"replacement-frame-stale").hexdigest()
    service.submit_operator_action(
        actor=operator_actor("perform_zeroback"),
        capability="perform_zeroback",
        action_type="perform_zeroback",
        payload={
            "run_id": "run-001",
            "replacement_frame_root_hash": replacement_frame,
        },
        confirmation=confirmation,
        created_at=ACTION_AT,
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        expected_head_event_hash=store.get_snapshot("run-001")["head_event_hash"],
        expected_head_sequence=0,
        idempotency_key="operator-001",
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=SNAPSHOT_HASH,
        trusted_adapter_intent_id="operator-intent-001",
        validator=lambda request, snapshot: AdmissionDecision.accept(),
    )
    before = len(store.export_run("run-001")["events"])
    with pytest.raises(ContextRefusal):
        submit_candidate(
            service, context=context, visible=visible, external=external
        )
    assert len(store.export_run("run-001")["events"]) == before


def test_operator_action_requires_trusted_actor_and_exact_confirmation() -> None:
    service, store = service_and_store()
    before = len(store.export_run("run-001")["events"])
    valid_confirmation = {
        "confirmed": True,
        "confirmed_at": ACTION_AT,
        "consequence_acknowledged": True,
        "rationale": "Operator reviewed the scoped change.",
    }
    kwargs = {
        "capability": "release_still",
        "action_type": "test_confirmation",
        "payload": {"run_id": "run-001", "disposition": "defer"},
        "confirmation": valid_confirmation,
        "created_at": ACTION_AT,
        "effective_policy_hash": EFFECTIVE_POLICY_HASH,
        "expected_head_event_hash": store.get_snapshot("run-001")[
            "head_event_hash"
        ],
        "expected_head_sequence": 0,
        "idempotency_key": "operator-001",
        "operator_governance_profile_hash": PROFILE_HASH,
        "session_governance_snapshot_hash": SNAPSHOT_HASH,
        "trusted_adapter_intent_id": "operator-intent-001",
        "validator": lambda request, snapshot: AdmissionDecision.accept(),
    }
    with pytest.raises(CanonicalRunServiceError, match="ActorContext"):
        service.submit_operator_action(actor={"actor_id": "operator:forged"}, **kwargs)
    with pytest.raises(CanonicalRunServiceError, match="operator ActorContext"):
        service.submit_operator_action(actor=model_actor(), **kwargs)

    broken = deepcopy(valid_confirmation)
    broken["confirmed"] = False
    with pytest.raises(CanonicalRunServiceError, match="affirmative"):
        service.submit_operator_action(
            actor=operator_actor("release_still"),
            **{**kwargs, "confirmation": broken},
        )
    assert len(store.export_run("run-001")["events"]) == before


def test_operator_action_enforces_client_pinned_head_and_replays_exactly() -> None:
    service, store = service_and_store()
    snapshot = store.get_snapshot("run-001")
    confirmation = {
        "confirmed": True,
        "confirmed_at": ACTION_AT,
        "consequence_acknowledged": True,
        "rationale": "Operator reviewed the exact pinned head.",
    }
    kwargs = {
        "actor": operator_actor("perform_zeroback"),
        "capability": "perform_zeroback",
        "action_type": "perform_zeroback",
        "payload": {
            "run_id": "run-001",
            "replacement_frame_root_hash": hashlib.sha256(
                b"replacement-frame-pinned"
            ).hexdigest(),
        },
        "confirmation": confirmation,
        "created_at": ACTION_AT,
        "effective_policy_hash": EFFECTIVE_POLICY_HASH,
        "expected_head_event_hash": snapshot["head_event_hash"],
        "expected_head_sequence": snapshot["head_sequence"],
        "idempotency_key": "operator-pinned-001",
        "operator_governance_profile_hash": PROFILE_HASH,
        "session_governance_snapshot_hash": SNAPSHOT_HASH,
        "trusted_adapter_intent_id": "operator-pinned-intent-001",
        "validator": lambda request, locked: AdmissionDecision.accept(),
    }

    first = service.submit_operator_action(**kwargs)
    replay = service.submit_operator_action(**kwargs)
    stale = service.submit_operator_action(
        **{
            **kwargs,
            "idempotency_key": "operator-pinned-stale",
            "trusted_adapter_intent_id": "operator-pinned-intent-stale",
        }
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert first.receipt == replay.receipt
    assert stale.receipt["outcome"] == "stale_head"
    assert stale.receipt["advanced_head"] is False
    assert len(store.export_run("run-001")["events"]) == 2


def test_post_fork_action_refuses_before_receipt_signing_without_mutation() -> None:
    service, store = service_and_store()
    fork_parent_run(service, store)
    parent = store.get_snapshot("run-001")
    before = store.export_run("run-001")
    validator_called = False

    def validator(
        request: dict[str, object], snapshot: dict[str, object]
    ) -> AdmissionDecision:
        nonlocal validator_called
        validator_called = True
        return AdmissionDecision.accept()

    with pytest.raises(
        CanonicalRunServiceError,
        match="canonical run is read-only and cannot accept new actions",
    ):
        service.submit_operator_action(
            actor=operator_actor("perform_zeroback"),
            capability="perform_zeroback",
            action_type="perform_zeroback",
            payload={
                "run_id": "run-001",
                "replacement_frame_root_hash": hashlib.sha256(
                    b"replacement-frame-after-fork"
                ).hexdigest(),
            },
            confirmation={
                "confirmed": True,
                "confirmed_at": ACTION_AT,
                "consequence_acknowledged": True,
                "rationale": "Exercise the frozen predecessor refusal path.",
            },
            created_at=ACTION_AT,
            effective_policy_hash=EFFECTIVE_POLICY_HASH,
            expected_head_event_hash=parent["head_event_hash"],
            expected_head_sequence=parent["head_sequence"],
            idempotency_key="operator-after-fork",
            operator_governance_profile_hash=PROFILE_HASH,
            session_governance_snapshot_hash=SNAPSHOT_HASH,
            trusted_adapter_intent_id="operator-after-fork-intent",
            validator=validator,
        )

    assert validator_called is False
    assert store.export_run("run-001") == before
    assert (
        store.get_outcome(
            run_id="run-001",
            actor_id="operator:local",
            idempotency_key="operator-after-fork",
        )
        is None
    )


def _validate_schema(schema_version: str, value: dict[str, object]) -> None:
    path = ROOT / "interop" / "schemas" / f"{schema_version}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(value)
