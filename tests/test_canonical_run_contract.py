from __future__ import annotations

from copy import deepcopy

import pytest

from nepsis_cgn.contracts.canonical_run import (
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
