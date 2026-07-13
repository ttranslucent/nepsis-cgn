from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from nepsis_cgn.canonical_runs.store import AdmissionDecision, ArtifactInput
from nepsis_cgn.contracts.canonical_json import canonical_hash
from nepsis_cgn.contracts.canonical_run import ActorContext
from nepsis_cgn.verification.canonical_run_export import (
    CanonicalRunExportVerificationError,
    verify_canonical_run_fork_pair,
    verify_protected_canonical_run_export,
)
from nepsis_cgn.verification.operator_proposal_lifecycle import (
    OperatorProposalLifecycleVerificationError,
    verify_operator_proposal_lifecycle,
)
from nepsis_cgn.canonical_runs.operator_disposition import (
    validate_operator_disposition,
)
from tests.test_canonical_run_service import (
    ACTION_AT,
    EFFECTIVE_POLICY_HASH,
    GOVERNANCE_POLICY_DIFF_VERSION,
    PROFILE_HASH,
    SNAPSHOT_HASH,
    candidate_inputs,
    service_and_store,
    submit_candidate,
    operator_actor,
)


MODULE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "nepsis_cgn"
    / "verification"
    / "canonical_run_export.py"
)
LIFECYCLE_MODULE = MODULE.with_name("operator_proposal_lifecycle.py")


def _export() -> dict:
    service, _ = service_and_store()
    context, visible, external = candidate_inputs(service)
    submit_candidate(
        service,
        context=context,
        visible=visible,
        external=external,
    )
    return dict(
        service.export_run(
            run_id="run-001",
            actor=ActorContext(
                actor_id="validator:detached-export",
                provenance_class="validator",
                capability_id="cap-export",
                capabilities=frozenset({"export_run"}),
            ),
        )
    )


def _disposed_export() -> dict:
    service, store = service_and_store()
    context, visible, external = candidate_inputs(service)
    candidate = submit_candidate(
        service,
        context=context,
        visible=visible,
        external=external,
    )
    proposal_hash = canonical_hash(visible)
    service.submit_operator_action(
        actor=operator_actor("submit_operator_disposition"),
        capability="submit_operator_disposition",
        action_type="record_operator_disposition",
        payload={
            "disposition": "defer",
            "operator_visible_proposal_hash": proposal_hash,
            "run_id": "run-001",
        },
        confirmation={
            "confirmed": True,
            "confirmed_at": "2026-07-12T16:02:00.000Z",
            "consequence_acknowledged": True,
            "rationale": "Reviewed exact pending proposal.",
        },
        created_at="2026-07-12T16:02:00.000Z",
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        expected_head_event_hash=candidate.receipt["resulting_head_event_hash"],
        expected_head_sequence=candidate.receipt["resulting_head_sequence"],
        idempotency_key="disposition-001",
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=SNAPSHOT_HASH,
        trusted_adapter_intent_id="adapter:disposition-001",
        validator=validate_operator_disposition,
    )
    return dict(
        service.export_run(
            run_id="run-001",
            actor=ActorContext(
                actor_id="validator:detached-export",
                provenance_class="validator",
                capability_id="cap-export",
                capabilities=frozenset({"export_run"}),
            ),
        )
    )


def _reroot(export: dict) -> None:
    unsigned = {
        key: deepcopy(value)
        for key, value in export.items()
        if key != "export_root_hash"
    }
    export["export_root_hash"] = canonical_hash(unsigned)


def _export_actor() -> ActorContext:
    return ActorContext(
        actor_id="validator:detached-export",
        provenance_class="validator",
        capability_id="cap-export",
        capabilities=frozenset({"export_run"}),
    )


def _fork_exports(
    *, child_run_id: str = "run-002", inherit_evidence: bool = False
) -> tuple[dict, dict]:
    service, store = service_and_store()
    inherited_evidence_root_hashes: list[str] = []
    if inherit_evidence:
        evidence = ArtifactInput(
            artifact_schema_version="nepsis.test_evidence_root@0.1.0",
            roles=("evidence_root",),
            artifact={
                "evidence_root_schema_version": "nepsis.test_evidence_root@0.1.0",
                "summary": "Inspectable predecessor evidence.",
            },
        )
        snapshot = store.get_snapshot("run-001")
        confirmation = {
            "confirmed": True,
            "confirmed_at": ACTION_AT,
            "consequence_acknowledged": True,
            "rationale": "Record the refused attempt and retain its evidence root.",
        }
        payload = {"attempt": "retain-evidence-root"}
        intent_hash = canonical_hash(
            {
                "action": "release_still",
                "capability": "release_still",
                "operator_confirmation": confirmation,
                "payload": payload,
            }
        )
        store.append_action(
            actor=operator_actor("release_still"),
            request={
                "action_request_schema_version": "nepsis.action_request@0.1.0",
                "action_type": "release_still",
                "artifact_hashes": [evidence.artifact_hash],
                "capability": "release_still",
                "capability_id": "cap-operator",
                "created_at": ACTION_AT,
                "effective_policy_hash": snapshot["effective_policy_hash"],
                "expected_head_event_hash": snapshot["head_event_hash"],
                "expected_head_sequence": snapshot["head_sequence"],
                "idempotency_key": "retain-evidence-root",
                "intent_hash": intent_hash,
                "operator_confirmation": confirmation,
                "operator_governance_profile_hash": snapshot[
                    "operator_governance_profile_hash"
                ],
                "payload": payload,
                "payload_hash": canonical_hash(payload),
                "run_id": "run-001",
                "session_governance_snapshot_hash": snapshot[
                    "session_governance_snapshot_hash"
                ],
                "trusted_adapter_intent_id": "adapter:retain-evidence-root",
            },
            artifacts=(evidence,),
            validator=lambda _request, _snapshot: AdmissionDecision(
                admitted=False,
                reason_code="test_refusal",
                detail="Evidence-bearing attempt is intentionally refused.",
            ),
        )
        inherited_evidence_root_hashes.append(evidence.artifact_hash)
    parent = store.get_snapshot("run-001")
    reason = "The predecessor Codex thread is irrecoverable."
    policy_diff = {
        "changes": [],
        "child_run_id": child_run_id,
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
    provenance = {
        "fork_reason": reason,
        "forked_from_run_id": "run-001",
        "inherited_evidence_root_hashes": inherited_evidence_root_hashes,
        "parent_head_event_hash": parent["head_event_hash"],
        "policy_diff_artifact_hash": canonical_hash(policy_diff),
    }
    service.create_run(
        actor=operator_actor("create_run"),
        run_id=child_run_id,
        owner_id="operator:local",
        created_at=ACTION_AT,
        idempotency_key=f"create-{child_run_id}",
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=hashlib.sha256(
            f"snapshot:{child_run_id}".encode()
        ).hexdigest(),
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        system_policy_bindings=parent["system_policy_bindings"],
        initial_packet_projection=parent["packet_projection"],
        initial_postcondition=parent["postcondition"],
        fork_provenance=provenance,
        fork_policy_diff_artifact={
            "artifact": policy_diff,
            "artifact_schema_version": GOVERNANCE_POLICY_DIFF_VERSION,
            "roles": ["policy_diff"],
        },
    )
    return (
        dict(service.export_run(run_id="run-001", actor=_export_actor())),
        dict(service.export_run(run_id=child_run_id, actor=_export_actor())),
    )


def _rehash_event(event: dict) -> None:
    event["payload_hash"] = canonical_hash(event["payload"])
    envelope = {
        key: deepcopy(value)
        for key, value in event.items()
        if key not in {"event_hash", "payload"}
    }
    event["event_hash"] = canonical_hash(envelope)


def test_protected_export_verifies_without_store_or_service_imports() -> None:
    report = verify_protected_canonical_run_export(_export())

    assert report["valid"] is True
    assert report["adoption_eligible"] is False
    assert report["authenticity"] == "writer_signed_self_consistency"
    assert report["event_count"] == 2
    assert report["artifact_count"] == 3
    assert report["receipt_count"] == 2
    assert "signed_action_receipts" in report["verified_checks"]
    assert "domain_projection_semantics" in report["unverified_claims"]


def test_detached_verifier_reconstructs_operator_proposal_lifecycle() -> None:
    report = verify_protected_canonical_run_export(_disposed_export())

    assert report["valid"] is True
    assert report["proposal_lifecycle"] == {
        "candidate_count": 1,
        "disposition_count": 1,
        "observed": True,
    }
    assert "operator_proposal_disposition_lifecycle" in report["verified_checks"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("apply_requested_change", "changed non-lifecycle packet state"),
        ("drop_proposal_cause", "reference exactly the proposal artifact"),
        ("change_confirmation", "intent omits capability or confirmation"),
        ("change_terminal_status", "terminal state mismatch"),
        ("change_validator_binding", "validator binding mismatch"),
    ],
)
def test_lifecycle_semantic_tamper_fails_independently(
    mutation: str, message: str
) -> None:
    export = _disposed_export()
    events = deepcopy(export["events"])
    disposition = events[-1]
    final_packet = deepcopy(export["packet_projection"])
    if mutation == "apply_requested_change":
        disposition["payload"]["packet_projection"]["candidate"] = "option_a"
        final_packet["candidate"] = "option_a"
    elif mutation == "drop_proposal_cause":
        disposition["caused_by_artifact_hashes"] = []
    elif mutation == "change_confirmation":
        disposition["payload"]["operator_confirmation"]["rationale"] = "Changed."
    elif mutation == "change_terminal_status":
        disposition["payload"]["packet_projection"]["operator_proposal_state"][
            "status"
        ] = "accepted"
        final_packet["operator_proposal_state"]["status"] = "accepted"
    else:
        disposition["payload"]["validator_binding"]["policy_hash"] = "0" * 64
    artifacts = {row["artifact_hash"]: row for row in export["artifacts"]}

    with pytest.raises(OperatorProposalLifecycleVerificationError, match=message):
        verify_operator_proposal_lifecycle(
            events=events,
            artifacts=artifacts,
            final_packet_projection=final_packet,
            system_policy_bindings=export["run"]["system_policy_bindings"],
        )


def test_export_root_tamper_fails_closed() -> None:
    export = _export()
    export["packet_projection"]["revision"] = 99

    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="export root hash mismatch",
    ):
        verify_protected_canonical_run_export(export)


def test_rerooted_packet_tamper_fails_projection_binding() -> None:
    export = _export()
    export["packet_projection"]["revision"] = 99
    _reroot(export)

    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="packet projection hash mismatch",
    ):
        verify_protected_canonical_run_export(export)


def test_rerooted_receipt_signature_and_outcome_substitution_fail() -> None:
    signed = _export()
    signed["action_receipts"][1]["outcome"] = "committed"
    _reroot(signed)
    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="signature mismatch",
    ):
        verify_protected_canonical_run_export(signed)

    substituted = _export()
    substituted["outcomes"][1]["request_hash"] = "0" * 64
    _reroot(substituted)
    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="receipt/outcome identity mismatch",
    ):
        verify_protected_canonical_run_export(substituted)


def test_rerooted_missing_referenced_artifact_fails() -> None:
    export = _export()
    export["artifacts"].pop()
    _reroot(export)

    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="unavailable artifact",
    ):
        verify_protected_canonical_run_export(export)


def test_child_fork_export_verifies_with_explicit_external_predecessor_limit() -> None:
    _, child = _fork_exports()

    report = verify_protected_canonical_run_export(child)

    assert report["valid"] is True
    assert child["run"]["status"] == "active"
    assert child["events"][0]["caused_by_event_hashes"]
    assert "external_fork_predecessor_event" in report["unverified_claims"]


def test_parent_fork_export_replays_read_only_and_requires_fork_receipt() -> None:
    parent, _ = _fork_exports()

    report = verify_protected_canonical_run_export(parent)

    assert report["valid"] is True
    assert parent["run"]["status"] == "read_only"
    assert parent["events"][-1]["event_type"] == "run_forked"
    assert parent["action_receipts"][-1]["capability"] == "fork_run"
    assert report["receipt_count"] == report["event_count"] == 2

    missing_fork_receipt = deepcopy(parent)
    missing_fork_receipt["outcomes"].pop()
    missing_fork_receipt["action_receipts"].pop()
    _reroot(missing_fork_receipt)
    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="every canonical event requires exactly one advancing receipt",
    ):
        verify_protected_canonical_run_export(missing_fork_receipt)


def test_fork_pair_verifies_cross_run_lineage_and_checkpoint() -> None:
    parent, child = _fork_exports()

    report = verify_canonical_run_fork_pair(
        parent_export=parent,
        child_export=child,
    )

    assert report["valid"] is True
    assert report["parent_run_id"] == "run-001"
    assert report["child_run_id"] == "run-002"
    assert "terminal_predecessor_to_successor_lineage" in report["verified_checks"]
    assert "external_fork_predecessor_event" not in report["unverified_claims"]


def test_fork_pair_verifies_inherited_evidence_root_identity() -> None:
    parent, child = _fork_exports(inherit_evidence=True)
    inherited = child["run"]["fork_provenance"][
        "inherited_evidence_root_hashes"
    ]

    report = verify_canonical_run_fork_pair(
        parent_export=parent,
        child_export=child,
    )

    assert len(inherited) == 1
    assert inherited[0] in {row["artifact_hash"] for row in parent["artifacts"]}
    assert inherited[0] in {row["artifact_hash"] for row in child["artifacts"]}
    assert "inherited_evidence_root_identity" in report["verified_checks"]


def test_pair_rejects_rerooted_inherited_evidence_role_substitution() -> None:
    parent, child = _fork_exports(inherit_evidence=True)
    inherited_hash = child["run"]["fork_provenance"][
        "inherited_evidence_root_hashes"
    ][0]
    inherited_row = next(
        row for row in child["artifacts"] if row["artifact_hash"] == inherited_hash
    )
    inherited_row["roles"] = ["substituted_role"]
    _reroot(child)
    assert verify_protected_canonical_run_export(child)["valid"] is True

    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="inherited evidence roots do not match",
    ):
        verify_canonical_run_fork_pair(
            parent_export=parent,
            child_export=child,
        )


def test_rerooted_fork_status_laundering_fails_replay() -> None:
    parent, _ = _fork_exports()
    parent["run"]["status"] = "active"
    _reroot(parent)

    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="run status does not match event replay",
    ):
        verify_protected_canonical_run_export(parent)


def test_rerooted_nonterminal_fork_transition_fails_closed() -> None:
    parent, _ = _fork_exports()
    terminal = parent["events"][-1]
    terminal["payload"]["resulting_status"] = "active"
    _rehash_event(terminal)
    parent["run"]["head_event_hash"] = terminal["event_hash"]
    _reroot(parent)

    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="terminal read-only transition",
    ):
        verify_protected_canonical_run_export(parent)


def test_rerooted_child_without_exact_external_cause_fails_closed() -> None:
    _, child = _fork_exports()
    genesis = child["events"][0]
    genesis["caused_by_event_hashes"] = []
    _rehash_event(genesis)
    child["run"]["head_event_hash"] = genesis["event_hash"]
    _reroot(child)

    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="exactly one external predecessor event",
    ):
        verify_protected_canonical_run_export(child)


def test_individually_valid_exports_from_different_forks_do_not_form_a_pair() -> None:
    parent, _ = _fork_exports(child_run_id="run-002")
    _, unrelated_child = _fork_exports(child_run_id="run-003")
    assert verify_protected_canonical_run_export(parent)["valid"] is True
    assert verify_protected_canonical_run_export(unrelated_child)["valid"] is True

    with pytest.raises(
        CanonicalRunExportVerificationError,
        match="exact terminal predecessor transition",
    ):
        verify_canonical_run_fork_pair(
            parent_export=parent,
            child_export=unrelated_child,
        )


def test_verifier_has_no_writer_store_or_service_import() -> None:
    for module in (MODULE, LIFECYCLE_MODULE):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }

        assert "nepsis_cgn.canonical_runs.store" not in imports
        assert "nepsis_cgn.canonical_runs.service" not in imports
        assert all(not name.startswith("nepsismc") for name in imports)
