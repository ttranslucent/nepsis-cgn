from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from nepsis_cgn.canonical_runs.store import (
    AdmissionDecision,
    ArtifactInput,
    CanonicalRunStoreError,
    CanonicalRunStore,
    IdempotencyConflict,
    InvalidRequest,
    RunNotFound,
)
from nepsis_cgn.contracts.canonical_json import canonical_hash, canonical_json
from nepsis_cgn.contracts.canonical_run import (
    ActorContext,
    CANONICAL_RUN_GENESIS_HASH,
    verify_event_chain,
)


CREATED_AT = "2026-07-12T16:00:00.000Z"
ACTION_AT = "2026-07-12T16:01:00.000Z"
PROFILE_HASH = hashlib.sha256(b"profile").hexdigest()
SNAPSHOT_HASH = hashlib.sha256(b"snapshot").hexdigest()
EFFECTIVE_POLICY_HASH = hashlib.sha256(b"effective-policy").hexdigest()
POLICY_HASH = hashlib.sha256(b"system-policy").hexdigest()
CONTEXT_HASH = hashlib.sha256(b"context-manifest").hexdigest()
EXTERNAL_REF_HASH = hashlib.sha256(b"external-codex-ref").hexdigest()
PROPOSAL_HASH = hashlib.sha256(b"operator-visible-proposal").hexdigest()
CHILD_SNAPSHOT_HASH = hashlib.sha256(b"child-snapshot").hexdigest()


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


def initial_packet() -> dict[str, object]:
    return {
        "packet_schema_version": "nepsis.test_packet@0.1.0",
        "revision": 0,
    }


def postcondition(packet: dict[str, object], *, phase: str = "intake") -> dict[str, object]:
    return {
        "active_hold": False,
        "governance_status": "open",
        "packet_projection_hash": canonical_hash(packet),
        "phase": phase,
    }


def create(store: CanonicalRunStore, *, run_id: str = "run-001") -> dict[str, object]:
    packet = initial_packet()
    result = store.create_run(
        run_id=run_id,
        owner_id="operator:local",
        created_at=CREATED_AT,
        actor=operator_actor("create_run"),
        capability_id="cap-operator",
        idempotency_key=f"create-{run_id}",
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=SNAPSHOT_HASH,
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        system_policy_bindings=(
            {
                "policy_hash": POLICY_HASH,
                "policy_id": "canonical-run",
                "policy_version": "nepsis.canonical_run_policy@0.1.0",
            },
        ),
        initial_packet_projection=packet,
        initial_postcondition=postcondition(packet),
    )
    return dict(result.record)


def proposal_artifact(text: str = "consider option a") -> ArtifactInput:
    return ArtifactInput(
        artifact_schema_version="nepsis.operator_visible_proposal@0.1.0",
        roles=("operator_visible_proposal",),
        artifact={
            "operator_visible_proposal_schema_version": (
                "nepsis.operator_visible_proposal@0.1.0"
            ),
            "proposal": text,
        },
    )


def fork_inputs(
    store: CanonicalRunStore,
    *,
    inherited_evidence_root_hashes: list[str] | None = None,
) -> tuple[dict[str, object], ArtifactInput]:
    snapshot = store.get_snapshot("run-001")
    reason = "The bound Codex thread is irrecoverable."
    artifact = ArtifactInput(
        artifact_schema_version="nepsis.governance_policy_diff@0.1.0",
        roles=("policy_diff",),
        artifact={
            "changes": [],
            "child_run_id": "run-002",
            "fork_reason": reason,
            "from_effective_policy_hash": EFFECTIVE_POLICY_HASH,
            "governance_policy_diff_schema_version": (
                "nepsis.governance_policy_diff@0.1.0"
            ),
            "operator_confirmation": {
                "confirmed": True,
                "confirmed_at": ACTION_AT,
                "consequence_acknowledged": True,
                "rationale": "Freeze the predecessor and create a new run.",
            },
            "parent_run_id": "run-001",
            "to_effective_policy_hash": EFFECTIVE_POLICY_HASH,
        },
    )
    provenance = {
        "fork_reason": reason,
        "forked_from_run_id": "run-001",
        "inherited_evidence_root_hashes": (
            inherited_evidence_root_hashes or []
        ),
        "parent_head_event_hash": snapshot["head_event_hash"],
        "policy_diff_artifact_hash": artifact.artifact_hash,
    }
    return provenance, artifact


def create_fork(
    store: CanonicalRunStore,
    *,
    inherited_evidence_root_hashes: list[str] | None = None,
    fork_provenance: dict[str, object] | None = None,
    fork_artifact: ArtifactInput | None = None,
):
    packet = store.get_snapshot("run-001")["packet_projection"]
    if fork_provenance is None or fork_artifact is None:
        provenance, artifact = fork_inputs(
            store,
            inherited_evidence_root_hashes=inherited_evidence_root_hashes,
        )
    else:
        provenance, artifact = fork_provenance, fork_artifact
    result = store.create_run(
        run_id="run-002",
        owner_id="operator:local",
        created_at=ACTION_AT,
        actor=operator_actor("create_run"),
        capability_id="cap-operator",
        idempotency_key="create-run-002",
        operator_governance_profile_hash=PROFILE_HASH,
        session_governance_snapshot_hash=CHILD_SNAPSHOT_HASH,
        effective_policy_hash=EFFECTIVE_POLICY_HASH,
        system_policy_bindings=(
            {
                "policy_hash": POLICY_HASH,
                "policy_id": "canonical-run",
                "policy_version": "nepsis.canonical_run_policy@0.1.0",
            },
        ),
        initial_packet_projection=packet,
        initial_postcondition=postcondition(packet),
        fork_provenance=provenance,
        fork_policy_diff_artifact=artifact,
    )
    return result, provenance, artifact


def model_request(
    store: CanonicalRunStore,
    *,
    artifact: ArtifactInput | None = None,
    idempotency_key: str = "model-001",
    payload: dict[str, object] | None = None,
    expected_head_sequence: int | None = None,
    expected_head_event_hash: str | None = None,
) -> dict[str, object]:
    snapshot = store.get_snapshot("run-001")
    body = payload or {"candidate": "option_a"}
    return {
        "action_request_schema_version": "nepsis.action_request@0.1.0",
        "action_type": "record_candidate",
        "artifact_hashes": [] if artifact is None else [artifact.artifact_hash],
        "capability": "submit_model_candidate",
        "capability_id": "cap-model",
        "context_manifest_hash": CONTEXT_HASH,
        "created_at": ACTION_AT,
        "effective_policy_hash": EFFECTIVE_POLICY_HASH,
        "expected_head_event_hash": (
            snapshot["head_event_hash"]
            if expected_head_event_hash is None
            else expected_head_event_hash
        ),
        "expected_head_sequence": (
            snapshot["head_sequence"]
            if expected_head_sequence is None
            else expected_head_sequence
        ),
        "external_codex_ref_hash": EXTERNAL_REF_HASH,
        "idempotency_key": idempotency_key,
        "intent_hash": canonical_hash(
            {"action": "record_candidate", "payload": body}
        ),
        "operator_governance_profile_hash": PROFILE_HASH,
        "operator_visible_proposal_hash": PROPOSAL_HASH,
        "payload": body,
        "payload_hash": canonical_hash(body),
        "run_id": "run-001",
        "session_governance_snapshot_hash": SNAPSHOT_HASH,
        "trusted_adapter_intent_id": f"intent-{idempotency_key}",
    }


def operator_request(
    store: CanonicalRunStore,
    *,
    idempotency_key: str = "operator-001",
) -> dict[str, object]:
    snapshot = store.get_snapshot("run-001")
    payload = {"candidate_id": "candidate-001", "disposition": "accept"}
    confirmation = {
        "confirmed": True,
        "confirmed_at": ACTION_AT,
        "consequence_acknowledged": True,
        "rationale": "operator reviewed candidate",
    }
    return {
        "action_request_schema_version": "nepsis.action_request@0.1.0",
        "action_type": "accept_candidate",
        "artifact_hashes": [],
        "capability": "submit_operator_disposition",
        "capability_id": "cap-operator",
        "created_at": ACTION_AT,
        "effective_policy_hash": EFFECTIVE_POLICY_HASH,
        "expected_head_event_hash": snapshot["head_event_hash"],
        "expected_head_sequence": snapshot["head_sequence"],
        "idempotency_key": idempotency_key,
        "intent_hash": canonical_hash(
            {
                "action": "accept_candidate",
                "capability": "submit_operator_disposition",
                "operator_confirmation": confirmation,
                "payload": payload,
            }
        ),
        "operator_confirmation": confirmation,
        "operator_governance_profile_hash": PROFILE_HASH,
        "operator_visible_proposal_hash": PROPOSAL_HASH,
        "payload": payload,
        "payload_hash": canonical_hash(payload),
        "run_id": "run-001",
        "session_governance_snapshot_hash": SNAPSHOT_HASH,
        "trusted_adapter_intent_id": f"intent-{idempotency_key}",
    }


def allow_candidate(
    request: dict[str, object], snapshot: dict[str, object]
) -> AdmissionDecision:
    assert request["run_id"] == snapshot["run_id"]
    return AdmissionDecision.accept(event_type="model_candidate_recorded")


def test_create_run_pins_governance_and_appends_genesis() -> None:
    store = CanonicalRunStore.in_memory()
    outcome = create(store)

    exported = store.export_run("run-001")
    run = exported["run"]
    assert outcome["outcome"] == "committed"
    assert run["head_sequence"] == 0
    assert run["head_event_hash"] == outcome["event_hash"]
    assert run["operator_governance_profile_hash"] == PROFILE_HASH
    assert run["session_governance_snapshot_hash"] == SNAPSHOT_HASH
    assert exported["effective_policy_hash"] == EFFECTIVE_POLICY_HASH
    assert exported["events"][0]["prev_event_hash"] == CANONICAL_RUN_GENESIS_HASH
    assert exported["events"][0]["event_type"] == "run_created"
    verify_event_chain(exported["events"])


def test_create_replay_is_idempotent_and_conflicting_create_is_refused() -> None:
    store = CanonicalRunStore.in_memory()
    original = create(store)
    replay = create(store)
    assert replay == original
    assert len(store.export_run("run-001")["events"]) == 1

    packet = initial_packet()
    with pytest.raises(IdempotencyConflict):
        store.create_run(
            run_id="run-001",
            owner_id="different-owner",
            created_at=CREATED_AT,
            actor=operator_actor("create_run"),
            capability_id="cap-operator",
            idempotency_key="create-run-001",
            operator_governance_profile_hash=PROFILE_HASH,
            session_governance_snapshot_hash=SNAPSHOT_HASH,
            effective_policy_hash=EFFECTIVE_POLICY_HASH,
            system_policy_bindings=(
                {
                    "policy_hash": POLICY_HASH,
                    "policy_id": "canonical-run",
                    "policy_version": "nepsis.canonical_run_policy@0.1.0",
                },
            ),
            initial_packet_projection=packet,
            initial_postcondition=postcondition(packet),
        )


def test_fork_atomically_freezes_parent_and_binds_distinct_successor() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    parent_before = store.get_snapshot("run-001")

    result, provenance, artifact = create_fork(store)
    parent = store.export_run("run-001")
    child = store.export_run("run-002")

    assert result.outcome == "committed"
    assert result.record["artifact_hashes"] == [artifact.artifact_hash]
    assert parent["run"]["status"] == "read_only"
    assert parent["run"]["head_sequence"] == parent_before["head_sequence"] + 1
    assert parent["events"][-1]["event_type"] == "run_forked"
    assert parent["events"][-1]["prev_event_hash"] == provenance[
        "parent_head_event_hash"
    ]
    assert parent["events"][-1]["payload"]["successor_run_id"] == "run-002"
    assert child["run"]["status"] == "active"
    assert child["run"]["fork_provenance"] == provenance
    assert child["events"][0]["caused_by_event_hashes"] == [
        parent["run"]["head_event_hash"]
    ]
    assert child["events"][0]["caused_by_artifact_hashes"] == [
        artifact.artifact_hash
    ]
    assert {row["artifact_hash"] for row in parent["artifacts"]} == {
        artifact.artifact_hash
    }
    assert {row["artifact_hash"] for row in child["artifacts"]} == {
        artifact.artifact_hash
    }
    parent_fork_outcome = parent["outcomes"][-1]
    assert parent_fork_outcome["capability"] == "fork_run"
    assert parent_fork_outcome["event_hash"] == parent["events"][-1]["event_hash"]
    assert parent_fork_outcome["prior_head_event_hash"] == provenance[
        "parent_head_event_hash"
    ]
    assert parent_fork_outcome["resulting_head_event_hash"] == parent["run"][
        "head_event_hash"
    ]
    assert parent_fork_outcome["artifact_hashes"] == [artifact.artifact_hash]

    parent_event_count = len(parent["events"])
    parent_outcome_count = len(parent["outcomes"])
    refused = store.append_action(
        actor=model_actor(),
        request=model_request(store, idempotency_key="after-fork"),
        validator=allow_candidate,
    )
    assert refused.outcome == "invalid_request"
    assert refused.record["reason_code"] == "run_not_active"
    assert len(store.export_run("run-001")["events"]) == parent_event_count
    assert len(store.export_run("run-001")["outcomes"]) == parent_outcome_count

    replay, _, _ = create_fork(
        store, fork_provenance=provenance, fork_artifact=artifact
    )
    assert replay.replayed is True
    assert len(store.export_run("run-001")["events"]) == parent_event_count


def test_failed_fork_rolls_back_predecessor_freeze() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    before = store.export_run("run-001")

    with pytest.raises(InvalidRequest, match="inherited evidence root"):
        create_fork(store, inherited_evidence_root_hashes=["f" * 64])

    after = store.export_run("run-001")
    assert after == before
    with pytest.raises(RunNotFound):
        store.get_snapshot("run-002")


def test_fork_provenance_is_immutable_and_cross_run_lineage_is_verified() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    create_fork(store)

    with pytest.raises(sqlite3.IntegrityError, match="fork provenance is immutable"):
        store._connection.execute(
            "UPDATE canonical_runs SET fork_provenance_json = ? WHERE run_id = ?",
            (canonical_json({"forged": True}), "run-002"),
        )

    store._connection.execute("DROP TRIGGER canonical_run_events_no_update")
    child_event = store.export_run("run-002")["events"][0]
    child_event["caused_by_event_hashes"] = ["0" * 64]
    store._connection.execute(
        "UPDATE canonical_run_events SET event_json = ? WHERE run_id = ? AND sequence = 0",
        (canonical_json(child_event), "run-002"),
    )
    with pytest.raises(CanonicalRunStoreError):
        store.get_snapshot("run-002")


def test_append_atomically_persists_event_artifact_projection_head_and_outcome() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    artifact = proposal_artifact()
    request = model_request(store, artifact=artifact)

    result = store.append_action(
        actor=model_actor(),
        request=request,
        artifacts=(artifact,),
        validator=allow_candidate,
    )

    exported = store.export_run("run-001")
    assert result.outcome == "candidate_recorded"
    assert exported["run"]["head_sequence"] == 1
    assert exported["run"]["head_event_hash"] == result.event_hash
    assert len(exported["events"]) == 2
    assert exported["artifacts"][0]["artifact_hash"] == artifact.artifact_hash
    assert exported["outcomes"][-1] == result.record
    verify_event_chain(exported["events"])


def test_same_request_replays_same_outcome_and_changed_request_conflicts() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    request = model_request(store)
    original = store.append_action(
        actor=model_actor(), request=request, validator=allow_candidate
    )
    replay = store.append_action(
        actor=model_actor(), request=request, validator=allow_candidate
    )

    assert replay.replayed is True
    assert replay.record == original.record
    assert len(store.export_run("run-001")["events"]) == 2

    changed = deepcopy(request)
    changed["payload"] = {"candidate": "option_b"}
    changed["payload_hash"] = canonical_hash(changed["payload"])
    changed["intent_hash"] = canonical_hash(
        {"action": changed["action_type"], "payload": changed["payload"]}
    )
    with pytest.raises(IdempotencyConflict):
        store.append_action(
            actor=model_actor(), request=changed, validator=allow_candidate
        )


def test_stale_head_returns_nonmutating_stable_outcome() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    stale = model_request(
        store,
        expected_head_sequence=0,
        expected_head_event_hash=hashlib.sha256(b"wrong-head").hexdigest(),
    )

    first = store.append_action(
        actor=model_actor(), request=stale, validator=allow_candidate
    )
    replay = store.append_action(
        actor=model_actor(), request=stale, validator=allow_candidate
    )

    assert first.outcome == "stale_head"
    assert first.record == replay.record
    assert replay.replayed is True
    exported = store.export_run("run-001")
    assert exported["run"]["head_sequence"] == 0
    assert len(exported["events"]) == 1
    assert exported["artifacts"] == []


@pytest.mark.parametrize("failure", ["payload_hash", "capability_id"])
def test_malformed_or_unauthorized_request_appends_nothing(failure: str) -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    request = model_request(store)
    if failure == "payload_hash":
        request["payload_hash"] = hashlib.sha256(b"wrong").hexdigest()
    else:
        request["capability_id"] = "client-forged-capability"

    result = store.append_action(
        actor=model_actor(), request=request, validator=allow_candidate
    )

    assert result.outcome == "invalid_request"
    exported = store.export_run("run-001")
    assert len(exported["events"]) == 1
    assert exported["artifacts"] == []


def test_structurally_admitted_governance_refusal_appends_exactly_once() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    before = store.get_snapshot("run-001")
    request = operator_request(store)

    def refuse(
        request: dict[str, object], snapshot: dict[str, object]
    ) -> AdmissionDecision:
        return AdmissionDecision.refuse(
            reason_code="active_red_blocker",
            detail="RED blocker must resolve before disposition",
        )

    first = store.append_action(
        actor=operator_actor("submit_operator_disposition"),
        request=request,
        validator=refuse,
    )
    replay = store.append_action(
        actor=operator_actor("submit_operator_disposition"),
        request=request,
        validator=refuse,
    )

    exported = store.export_run("run-001")
    assert first.outcome == "refused"
    assert replay.record == first.record
    assert len(exported["events"]) == 2
    refusal = exported["events"][-1]
    assert refusal["event_type"] == "validator_refusal_created"
    assert refusal["provenance_class"] == "validator"
    assert exported["run"]["packet_projection_hash"] == before["postcondition"][
        "packet_projection_hash"
    ]
    verify_event_chain(exported["events"])


def test_transaction_rolls_back_all_rows_when_projection_write_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    artifact = proposal_artifact()
    request = model_request(store, artifact=artifact)

    def fail_projection(**kwargs: object) -> None:
        raise RuntimeError("injected projection failure")

    monkeypatch.setattr(store, "_write_projection", fail_projection)
    with pytest.raises(RuntimeError, match="injected projection failure"):
        store.append_action(
            actor=model_actor(),
            request=request,
            artifacts=(artifact,),
            validator=allow_candidate,
        )

    exported = store.export_run("run-001")
    assert exported["run"]["head_sequence"] == 0
    assert len(exported["events"]) == 1
    assert exported["artifacts"] == []
    assert len(exported["outcomes"]) == 1


def test_append_only_and_immutable_triggers_block_direct_mutation(tmp_path: Path) -> None:
    db_path = tmp_path / "canonical-runs.db"
    store = CanonicalRunStore.open(db_path)
    create(store)
    artifact = proposal_artifact()
    request = model_request(store, artifact=artifact)
    store.append_action(
        actor=model_actor(),
        request=request,
        artifacts=(artifact,),
        validator=allow_candidate,
    )

    raw = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        raw.execute(
            "UPDATE canonical_run_events SET event_hash = ? WHERE run_id = ?",
            ("0" * 64, "run-001"),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        raw.execute(
            "DELETE FROM canonical_run_artifacts WHERE run_id = ?",
            ("run-001",),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        raw.execute("DELETE FROM canonical_runs WHERE run_id = ?", ("run-001",))
    raw.close()
    store.close()


def test_decision_commit_event_is_validator_authored() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    request = operator_request(store, idempotency_key="commit-001")
    request["action_type"] = "commit_decision"
    request["capability"] = "request_decision_commit"
    request.pop("operator_visible_proposal_hash")
    request["intent_hash"] = canonical_hash(
        {
            "action": request["action_type"],
            "capability": request["capability"],
            "operator_confirmation": request["operator_confirmation"],
            "payload": request["payload"],
        }
    )

    result = store.append_action(
        actor=operator_actor("request_decision_commit"),
        request=request,
        validator=lambda request, snapshot: AdmissionDecision.accept(),
    )

    event = store.export_run("run-001")["events"][-1]
    assert result.outcome == "committed"
    assert event["event_type"] == "decision_committed"
    assert event["provenance_class"] == "validator"
    assert event["payload"]["requested_by_actor_id"] == "operator:local"


def test_expected_head_cas_allows_only_one_writer(tmp_path: Path) -> None:
    db_path = tmp_path / "canonical-runs.db"
    writer_a = CanonicalRunStore.open(db_path)
    create(writer_a)
    writer_b = CanonicalRunStore.open(db_path)
    request_a = model_request(writer_a, idempotency_key="writer-a")
    request_b = model_request(writer_b, idempotency_key="writer-b")

    accepted = writer_a.append_action(
        actor=model_actor(), request=request_a, validator=allow_candidate
    )
    stale = writer_b.append_action(
        actor=model_actor(), request=request_b, validator=allow_candidate
    )

    assert accepted.outcome == "candidate_recorded"
    assert stale.outcome == "stale_head"
    assert len(writer_a.export_run("run-001")["events"]) == 2
    writer_b.close()
    writer_a.close()


def test_restart_preserves_identifiers_and_reconstructable_export(tmp_path: Path) -> None:
    db_path = tmp_path / "canonical-runs.db"
    store = CanonicalRunStore.open(db_path)
    create(store)
    artifact = proposal_artifact()
    request = model_request(store, artifact=artifact)
    result = store.append_action(
        actor=model_actor(),
        request=request,
        artifacts=(artifact,),
        validator=allow_candidate,
    )
    before = store.export_run_bytes("run-001")
    before_event_hash = result.event_hash
    store.close()

    restarted = CanonicalRunStore.open(db_path)
    after = restarted.export_run_bytes("run-001")
    exported = json.loads(after)
    assert after == before
    assert exported["events"][-1]["event_hash"] == before_event_hash
    assert canonical_hash(exported["packet_projection"]) == exported["run"][
        "packet_projection_hash"
    ]
    assert {row["artifact_hash"] for row in exported["artifacts"]} == set(
        exported["events"][-1]["caused_by_artifact_hashes"]
    )
    verify_event_chain(exported["events"])
    restarted.close()


def test_snapshot_refuses_projection_laundering_even_when_mutable_hashes_agree() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    forged_packet = {"revision": 999}
    forged_hash = canonical_hash(forged_packet)
    store._connection.execute(
        """
        UPDATE canonical_run_projections
        SET packet_projection_json = ?, packet_projection_hash = ?
        WHERE run_id = 'run-001'
        """,
        (canonical_json(forged_packet), forged_hash),
    )
    store._connection.execute(
        "UPDATE canonical_runs SET packet_projection_hash = ? WHERE run_id = 'run-001'",
        (forged_hash,),
    )

    with pytest.raises(
        CanonicalRunStoreError, match="does not match event replay"
    ):
        store.get_snapshot("run-001")
    with pytest.raises(
        CanonicalRunStoreError, match="does not match event replay"
    ):
        store.export_run("run-001")


def test_snapshot_refuses_event_row_columns_that_disagree_with_event_bytes() -> None:
    store = CanonicalRunStore.in_memory()
    create(store)
    store._connection.execute("DROP TRIGGER canonical_run_events_no_update")
    store._connection.execute(
        """
        UPDATE canonical_run_events SET event_hash = ?
        WHERE run_id = 'run-001' AND sequence = 0
        """,
        ("f" * 64,),
    )

    with pytest.raises(CanonicalRunStoreError, match="canonical bytes"):
        store.get_snapshot("run-001")
