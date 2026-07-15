from __future__ import annotations

from copy import deepcopy

import pytest

from nepsis_cgn.canonical_runs.store import CanonicalRunStore
from nepsis_cgn.contracts.canonical_run import (
    CANONICAL_EVENT_APPEND_ACTOR_ID,
    CANONICAL_EVENT_APPEND_CAPABILITY,
    CANONICAL_EVENT_APPEND_CAPABILITY_ID,
    CANONICAL_RUN_GENESIS_HASH,
    ActorContext,
    CanonicalRunContractError,
    CapabilityRefusal,
    build_event,
    require_capability,
    verify_event_chain,
)


OPERATOR = ActorContext(
    actor_id="operator:local",
    provenance_class="operator",
    capability_id="cap_operator_001",
    capabilities=frozenset({"create_run", "submit_operator_disposition"}),
)
MODEL = ActorContext(
    actor_id="model:codex",
    provenance_class="model",
    capability_id="cap_model_001",
    capabilities=frozenset({"read_snapshot", "submit_model_candidate"}),
)
TIMESTAMP = "2026-07-12T19:00:00.000Z"


def _event(*, sequence: int, previous: str, actor: ActorContext = OPERATOR) -> dict:
    return build_event(
        run_id="run_001",
        sequence=sequence,
        event_type="run_created" if sequence == 0 else "candidate_dispositioned",
        created_at=TIMESTAMP,
        actor_context=actor,
        prev_event_hash=previous,
        payload={"value": sequence},
    )


def test_builds_and_verifies_stable_run_event_chain() -> None:
    first = _event(sequence=0, previous=CANONICAL_RUN_GENESIS_HASH)
    second = _event(sequence=1, previous=first["event_hash"])
    verify_event_chain([first, second])
    assert _event(sequence=0, previous=CANONICAL_RUN_GENESIS_HASH) == first


@pytest.mark.parametrize("field", ["payload", "prev_event_hash", "event_hash"])
def test_chain_refuses_tampering(field: str) -> None:
    first = _event(sequence=0, previous=CANONICAL_RUN_GENESIS_HASH)
    second = _event(sequence=1, previous=first["event_hash"])
    changed = deepcopy(second)
    if field == "payload":
        changed["payload"]["value"] = 99
    else:
        changed[field] = "0" * 64
    with pytest.raises(CanonicalRunContractError):
        verify_event_chain([first, changed])


def test_actor_context_refuses_prefix_or_capability_elevation() -> None:
    with pytest.raises(CanonicalRunContractError):
        ActorContext(
            actor_id="model:codex",
            provenance_class="operator",
            capability_id="forged",
            capabilities=frozenset({"create_run"}),
        )
    with pytest.raises(CanonicalRunContractError):
        ActorContext(
            actor_id="model:codex",
            provenance_class="model",
            capability_id="forged",
            capabilities=frozenset({"request_decision_commit"}),
        )


def test_capability_check_uses_trusted_context() -> None:
    require_capability(MODEL, "submit_model_candidate")
    with pytest.raises(CapabilityRefusal):
        require_capability(MODEL, "submit_operator_disposition")


@pytest.mark.parametrize(
    (
        "actor_id",
        "provenance_class",
        "capability_id",
        "baseline_capabilities",
        "legitimate_capability",
    ),
    [
        (
            "model:codex-app-server",
            "model",
            "capability:model:codex-app-server",
            frozenset({"read_snapshot", "submit_model_candidate"}),
            "submit_model_candidate",
        ),
        (
            "system:nepsismc-host",
            "system",
            "capability:system:nepsismc-host",
            frozenset({"read_snapshot"}),
            "read_snapshot",
        ),
        (
            "validator:detached-local",
            "validator",
            "capability:validator:detached-local",
            frozenset({"export_run", "read_snapshot", "verify_run"}),
            "verify_run",
        ),
        (
            "validator:mc-import-pilot",
            "validator",
            "cap-import-pilot",
            frozenset({"import_sealed_bundle"}),
            "import_sealed_bundle",
        ),
    ],
    ids=("codex", "mc", "shadow", "import"),
)
def test_codex_mc_shadow_and_import_cannot_acquire_canonical_event_append(
    actor_id: str,
    provenance_class: str,
    capability_id: str,
    baseline_capabilities: frozenset[str],
    legitimate_capability: str,
) -> None:
    legitimate_actor = ActorContext(
        actor_id=actor_id,
        provenance_class=provenance_class,
        capability_id=capability_id,
        capabilities=baseline_capabilities,
    )
    require_capability(legitimate_actor, legitimate_capability)

    with pytest.raises(
        CanonicalRunContractError, match=r"canonical_event\.append is reserved"
    ):
        ActorContext(
            actor_id=actor_id,
            provenance_class=provenance_class,
            capability_id=capability_id,
            capabilities=baseline_capabilities
            | frozenset({CANONICAL_EVENT_APPEND_CAPABILITY}),
        )


def test_internal_canonical_store_alone_acquires_canonical_event_append() -> None:
    actor = CanonicalRunStore._validator_actor()

    assert actor.actor_id == CANONICAL_EVENT_APPEND_ACTOR_ID
    assert actor.capability_id == CANONICAL_EVENT_APPEND_CAPABILITY_ID
    assert actor.capabilities == frozenset({CANONICAL_EVENT_APPEND_CAPABILITY})
    require_capability(actor, CANONICAL_EVENT_APPEND_CAPABILITY)

    with pytest.raises(
        CanonicalRunContractError, match=r"canonical_event\.append is reserved"
    ):
        ActorContext(
            actor_id=CANONICAL_EVENT_APPEND_ACTOR_ID,
            provenance_class="validator",
            capability_id="forged",
            capabilities=frozenset({CANONICAL_EVENT_APPEND_CAPABILITY}),
        )
    with pytest.raises(
        CanonicalRunContractError, match=r"canonical_event\.append is reserved"
    ):
        ActorContext(
            actor_id=CANONICAL_EVENT_APPEND_ACTOR_ID,
            provenance_class="validator",
            capability_id=CANONICAL_EVENT_APPEND_CAPABILITY_ID,
            capabilities=frozenset(
                {CANONICAL_EVENT_APPEND_CAPABILITY, "verify_run"}
            ),
        )
