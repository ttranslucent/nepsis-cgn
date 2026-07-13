from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from nepsis_cgn.contracts.canonical_json import canonical_hash, canonical_json


OPERATOR_PROPOSAL_STATE_VERSION = "nepsis.operator_proposal_state@0.1.0"
OPERATOR_DISPOSITION_ADAPTER_VERSION = (
    "nepsis.operator_disposition_adapter@0.1.0"
)
OPERATOR_DISPOSITION_POLICY_VERSION = (
    "nepsis.operator_disposition_policy@0.1.0"
)
OPERATOR_DISPOSITION_EVENT_TYPE = "operator_proposal_disposition_recorded"
OPERATOR_DISPOSITION_ACTION_TYPE = "record_operator_disposition"
_POLICY = {
    "action_type": OPERATOR_DISPOSITION_ACTION_TYPE,
    "allowed_dispositions": ["accept", "defer", "reject"],
    "capability": "submit_operator_disposition",
    "confirmation_required": True,
    "operator_disposition_policy_schema_version": (
        OPERATOR_DISPOSITION_POLICY_VERSION
    ),
    "pending_cardinality": "one_exact_hash_bound_proposal",
    "requested_change_application": "prohibited",
}
OPERATOR_DISPOSITION_POLICY_HASH = canonical_hash(_POLICY)
_POLICY_BINDING = {
    "policy_hash": OPERATOR_DISPOSITION_POLICY_HASH,
    "policy_id": "operator_disposition",
    "policy_version": OPERATOR_DISPOSITION_POLICY_VERSION,
}
_VALIDATOR_BINDING = {
    "adapter_version": OPERATOR_DISPOSITION_ADAPTER_VERSION,
    "policy_hash": OPERATOR_DISPOSITION_POLICY_HASH,
    "policy_version": OPERATOR_DISPOSITION_POLICY_VERSION,
    "validator_id": f"validator:{OPERATOR_DISPOSITION_ADAPTER_VERSION}",
}
_PENDING_FIELDS = {
    "adapter_version",
    "candidate_created_at",
    "candidate_intent_hash",
    "operator_proposal_state_schema_version",
    "operator_visible_proposal_hash",
    "policy_hash",
    "policy_version",
    "status",
}
_DISPOSED_FIELDS = _PENDING_FIELDS | {
    "disposed_at",
    "disposition_intent_hash",
    "operator_confirmation_hash",
}
_STATUS_BY_DISPOSITION = {
    "accept": "accepted",
    "defer": "deferred",
    "reject": "rejected",
}


class OperatorProposalLifecycleVerificationError(ValueError):
    pass


def verify_operator_proposal_lifecycle(
    *,
    events: list[dict[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    final_packet_projection: Mapping[str, Any],
    system_policy_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reconstruct the proposal lifecycle without importing writer code."""

    if not events or events[0].get("event_type") != "run_created":
        raise OperatorProposalLifecycleVerificationError(
            "proposal lifecycle requires a run_created genesis"
        )
    genesis_payload = _mapping(events[0].get("payload"), "run_created payload")
    projection = _mapping(
        genesis_payload.get("initial_packet_projection"),
        "initial packet projection",
    )
    if "operator_proposal_state" in projection:
        raise OperatorProposalLifecycleVerificationError(
            "operator proposal state cannot originate at run creation"
        )
    postcondition = _mapping(
        genesis_payload.get("initial_postcondition"), "initial postcondition"
    )
    observed = False
    candidate_count = 0
    disposition_count = 0

    for event in events[1:]:
        event_type = event.get("event_type")
        payload = _mapping(event.get("payload"), "event payload")
        if event_type == "validator_refusal_created":
            continue
        next_projection_raw = payload.get("packet_projection")
        next_postcondition_raw = payload.get("postcondition")
        if next_projection_raw is None or next_postcondition_raw is None:
            continue
        next_projection = _mapping(next_projection_raw, "event packet projection")
        next_postcondition = _mapping(next_postcondition_raw, "event postcondition")
        if event_type == "model_candidate_recorded":
            observed = True
            candidate_count += 1
            _verify_policy_binding(system_policy_bindings)
            _verify_candidate_transition(
                event=event,
                event_payload=payload,
                prior_projection=projection,
                prior_postcondition=postcondition,
                resulting_projection=next_projection,
                resulting_postcondition=next_postcondition,
                artifacts=artifacts,
            )
        elif event_type == OPERATOR_DISPOSITION_EVENT_TYPE:
            observed = True
            disposition_count += 1
            _verify_policy_binding(system_policy_bindings)
            _verify_disposition_transition(
                event=event,
                event_payload=payload,
                prior_projection=projection,
                prior_postcondition=postcondition,
                resulting_projection=next_projection,
                resulting_postcondition=next_postcondition,
                artifacts=artifacts,
            )
        elif next_projection.get("operator_proposal_state") != projection.get(
            "operator_proposal_state"
        ):
            raise OperatorProposalLifecycleVerificationError(
                "operator proposal state changed outside its closed lifecycle events"
            )
        projection = next_projection
        postcondition = next_postcondition

    if projection != dict(final_packet_projection):
        raise OperatorProposalLifecycleVerificationError(
            "event projection reconstruction does not match final packet"
        )
    if disposition_count > candidate_count:
        raise OperatorProposalLifecycleVerificationError(
            "proposal dispositions exceed recorded candidates"
        )
    final_state = final_packet_projection.get("operator_proposal_state")
    if final_state is not None:
        _validate_state(final_state)
    return {
        "candidate_count": candidate_count,
        "disposition_count": disposition_count,
        "observed": observed,
    }


def _verify_candidate_transition(
    *,
    event: Mapping[str, Any],
    event_payload: Mapping[str, Any],
    prior_projection: Mapping[str, Any],
    prior_postcondition: Mapping[str, Any],
    resulting_projection: Mapping[str, Any],
    resulting_postcondition: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    if event.get("provenance_class") != "model" or not str(
        event.get("actor_id", "")
    ).startswith("model:"):
        raise OperatorProposalLifecycleVerificationError(
            "model candidate event provenance mismatch"
        )
    if event_payload.get("capability") != "submit_model_candidate":
        raise OperatorProposalLifecycleVerificationError(
            "model candidate capability mismatch"
        )
    if event_payload.get("validator_binding") != _VALIDATOR_BINDING:
        raise OperatorProposalLifecycleVerificationError(
            "model candidate validator binding mismatch"
        )
    action_payload = _mapping(
        event_payload.get("action_payload"), "model candidate action payload"
    )
    if set(action_payload) != {
        "context_manifest_hash",
        "external_codex_ref_hash",
        "model_candidate_schema_version",
        "normalized_change",
        "operator_visible_proposal_hash",
        "proposal_id",
    }:
        raise OperatorProposalLifecycleVerificationError(
            "model candidate payload fields mismatch"
        )
    expected_intent = canonical_hash(
        {"action": "record_model_candidate", "payload": action_payload}
    )
    if event.get("intent_hash") != expected_intent:
        raise OperatorProposalLifecycleVerificationError(
            "model candidate intent hash mismatch"
        )
    proposal_hash = _hash(
        action_payload.get("operator_visible_proposal_hash"),
        "operator_visible_proposal_hash",
    )
    proposal_row = _verify_artifact(
        proposal_hash,
        artifacts,
        schema_version="nepsis.operator_visible_proposal@0.1.0",
        role="operator_visible_proposal",
    )
    proposal_artifact = _mapping(
        proposal_row.get("artifact"), "operator-visible proposal artifact"
    )
    if action_payload.get("model_candidate_schema_version") != (
        "nepsis.model_candidate@0.1.0"
    ):
        raise OperatorProposalLifecycleVerificationError(
            "model candidate schema version mismatch"
        )
    if action_payload.get("proposal_id") != f"proposal:{proposal_hash}":
        raise OperatorProposalLifecycleVerificationError(
            "model candidate proposal identity mismatch"
        )
    normalized_change = _mapping(
        action_payload.get("normalized_change"), "normalized requested change"
    )
    requested_change = _mapping(
        proposal_artifact.get("requested_change"), "proposal requested change"
    )
    if canonical_json(normalized_change) != canonical_json(requested_change):
        raise OperatorProposalLifecycleVerificationError(
            "model candidate normalized change does not match proposal artifact"
        )
    context_hash = _hash(
        action_payload.get("context_manifest_hash"), "context_manifest_hash"
    )
    external_hash = _hash(
        action_payload.get("external_codex_ref_hash"),
        "external_codex_ref_hash",
    )
    if event.get("context_manifest_hash") != context_hash:
        raise OperatorProposalLifecycleVerificationError(
            "model candidate event context binding mismatch"
        )
    context_row = _verify_artifact(
        context_hash,
        artifacts,
        schema_version="nepsis.context_manifest@0.1.0",
        role="context_manifest",
    )
    external_row = _verify_artifact(
        external_hash,
        artifacts,
        schema_version="nepsis.external_codex_ref@0.1.0",
        role="external_codex_ref",
    )
    for row in (proposal_row, context_row, external_row):
        if row.get("created_sequence") != event.get("sequence"):
            raise OperatorProposalLifecycleVerificationError(
                "model candidate artifact creation sequence mismatch"
            )
    external_artifact = _mapping(
        external_row.get("artifact"), "external Codex reference artifact"
    )
    if external_artifact.get("operator_visible_proposal_hash") != proposal_hash:
        raise OperatorProposalLifecycleVerificationError(
            "external Codex reference proposal binding mismatch"
        )
    causes = event.get("caused_by_artifact_hashes")
    required = {proposal_hash, context_hash, external_hash}
    if not isinstance(causes, list) or set(causes) != required:
        raise OperatorProposalLifecycleVerificationError(
            "model candidate artifact causes mismatch"
        )
    prior_state = prior_projection.get("operator_proposal_state")
    if prior_state is not None and _validate_state(prior_state)["status"] == "pending":
        raise OperatorProposalLifecycleVerificationError(
            "model candidate replaced an undisposed pending proposal"
        )
    state = _validate_state(resulting_projection.get("operator_proposal_state"))
    expected_state = {
        "adapter_version": OPERATOR_DISPOSITION_ADAPTER_VERSION,
        "candidate_created_at": event.get("created_at"),
        "candidate_intent_hash": expected_intent,
        "operator_proposal_state_schema_version": OPERATOR_PROPOSAL_STATE_VERSION,
        "operator_visible_proposal_hash": proposal_hash,
        "policy_hash": OPERATOR_DISPOSITION_POLICY_HASH,
        "policy_version": OPERATOR_DISPOSITION_POLICY_VERSION,
        "status": "pending",
    }
    if state != expected_state:
        raise OperatorProposalLifecycleVerificationError(
            "model candidate pending state mismatch"
        )
    _verify_only_state_changed(prior_projection, resulting_projection)
    _verify_postcondition_transition(
        resulting_postcondition,
        resulting_projection,
        active_hold=True,
        governance_status="proposal_pending",
        phase="proposal_review",
    )


def _verify_disposition_transition(
    *,
    event: Mapping[str, Any],
    event_payload: Mapping[str, Any],
    prior_projection: Mapping[str, Any],
    prior_postcondition: Mapping[str, Any],
    resulting_projection: Mapping[str, Any],
    resulting_postcondition: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    if event.get("provenance_class") != "operator" or not str(
        event.get("actor_id", "")
    ).startswith("operator:"):
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition event provenance mismatch"
        )
    if event_payload.get("capability") != "submit_operator_disposition":
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition capability mismatch"
        )
    if event_payload.get("validator_binding") != _VALIDATOR_BINDING:
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition validator binding mismatch"
        )
    action_payload = _mapping(
        event_payload.get("action_payload"), "operator disposition action payload"
    )
    if set(action_payload) != {
        "disposition",
        "operator_visible_proposal_hash",
        "run_id",
    }:
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition payload fields mismatch"
        )
    if action_payload.get("run_id") != event.get("run_id"):
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition run_id mismatch"
        )
    disposition = action_payload.get("disposition")
    if disposition not in _STATUS_BY_DISPOSITION:
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition value is unsupported"
        )
    confirmation = _mapping(
        event_payload.get("operator_confirmation"), "operator confirmation"
    )
    if set(confirmation) != {
        "confirmed",
        "confirmed_at",
        "consequence_acknowledged",
        "rationale",
    } or confirmation.get("confirmed") is not True or confirmation.get(
        "consequence_acknowledged"
    ) is not True:
        raise OperatorProposalLifecycleVerificationError(
            "operator confirmation is not exact and affirmative"
        )
    if confirmation.get("confirmed_at") != event.get("created_at"):
        raise OperatorProposalLifecycleVerificationError(
            "operator confirmation timestamp mismatch"
        )
    if not isinstance(confirmation.get("rationale"), str) or not confirmation[
        "rationale"
    ]:
        raise OperatorProposalLifecycleVerificationError(
            "operator confirmation rationale is required"
        )
    expected_intent = canonical_hash(
        {
            "action": OPERATOR_DISPOSITION_ACTION_TYPE,
            "capability": "submit_operator_disposition",
            "operator_confirmation": confirmation,
            "payload": action_payload,
        }
    )
    if event.get("intent_hash") != expected_intent:
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition intent omits capability or confirmation"
        )
    proposal_hash = _hash(
        action_payload.get("operator_visible_proposal_hash"),
        "operator_visible_proposal_hash",
    )
    if event.get("caused_by_artifact_hashes") != [proposal_hash]:
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition must reference exactly the proposal artifact"
        )
    proposal_row = _verify_artifact(
        proposal_hash,
        artifacts,
        schema_version="nepsis.operator_visible_proposal@0.1.0",
        role="operator_visible_proposal",
    )
    if not isinstance(proposal_row.get("created_sequence"), int) or proposal_row[
        "created_sequence"
    ] >= event.get("sequence", -1):
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition proposal artifact was not recorded previously"
        )
    prior_state = _validate_state(prior_projection.get("operator_proposal_state"))
    if prior_state["status"] != "pending":
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition requires a pending proposal"
        )
    if prior_state["operator_visible_proposal_hash"] != proposal_hash:
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition proposal hash mismatch"
        )
    resulting_state = _validate_state(
        resulting_projection.get("operator_proposal_state")
    )
    expected_state = {
        **prior_state,
        "disposed_at": event.get("created_at"),
        "disposition_intent_hash": expected_intent,
        "operator_confirmation_hash": canonical_hash(confirmation),
        "status": _STATUS_BY_DISPOSITION[str(disposition)],
    }
    if resulting_state != expected_state:
        raise OperatorProposalLifecycleVerificationError(
            "operator disposition terminal state mismatch"
        )
    _verify_only_state_changed(prior_projection, resulting_projection)
    _verify_postcondition_transition(
        resulting_postcondition,
        resulting_projection,
        active_hold=disposition == "accept",
        governance_status=(
            "proposal_accepted" if disposition == "accept" else "open"
        ),
        phase="proposal_review" if disposition == "accept" else "intake",
    )


def _verify_only_state_changed(
    prior: Mapping[str, Any], resulting: Mapping[str, Any]
) -> None:
    prior_without = {
        key: deepcopy(value)
        for key, value in prior.items()
        if key != "operator_proposal_state"
    }
    resulting_without = {
        key: deepcopy(value)
        for key, value in resulting.items()
        if key != "operator_proposal_state"
    }
    if canonical_json(prior_without) != canonical_json(resulting_without):
        raise OperatorProposalLifecycleVerificationError(
            "proposal lifecycle applied or changed non-lifecycle packet state"
        )


def _verify_postcondition_transition(
    resulting: Mapping[str, Any],
    packet: Mapping[str, Any],
    *,
    active_hold: bool,
    governance_status: str,
    phase: str,
) -> None:
    if set(resulting) != {
        "active_hold",
        "governance_status",
        "packet_projection_hash",
        "phase",
    }:
        raise OperatorProposalLifecycleVerificationError(
            "proposal lifecycle postcondition fields mismatch"
        )
    expected = {
        "active_hold": active_hold,
        "governance_status": governance_status,
        "phase": phase,
    }
    for field, value in expected.items():
        if resulting.get(field) != value:
            raise OperatorProposalLifecycleVerificationError(
                f"proposal lifecycle {field} mismatch"
            )
    if resulting.get("packet_projection_hash") != canonical_hash(dict(packet)):
        raise OperatorProposalLifecycleVerificationError(
            "proposal lifecycle postcondition packet hash mismatch"
        )


def _verify_policy_binding(bindings: list[dict[str, Any]]) -> None:
    matches = [
        row
        for row in bindings
        if isinstance(row, dict) and row.get("policy_id") == "operator_disposition"
    ]
    if matches != [_POLICY_BINDING]:
        raise OperatorProposalLifecycleVerificationError(
            "run does not pin the exact operator disposition policy"
        )


def _verify_artifact(
    artifact_hash: str,
    artifacts: Mapping[str, Mapping[str, Any]],
    *,
    schema_version: str,
    role: str,
) -> Mapping[str, Any]:
    row = artifacts.get(artifact_hash)
    if not isinstance(row, Mapping):
        raise OperatorProposalLifecycleVerificationError(
            "proposal lifecycle references a missing artifact"
        )
    if row.get("artifact_schema_version") != schema_version or row.get("roles") != [
        role
    ]:
        raise OperatorProposalLifecycleVerificationError(
            "proposal lifecycle artifact role or schema mismatch"
        )
    return row


def _validate_state(value: Any) -> dict[str, Any]:
    state = _mapping(value, "operator proposal state")
    status = state.get("status")
    fields = _PENDING_FIELDS if status == "pending" else _DISPOSED_FIELDS
    if status not in {"pending", "accepted", "deferred", "rejected"}:
        raise OperatorProposalLifecycleVerificationError(
            "operator proposal state status mismatch"
        )
    if set(state) != fields:
        raise OperatorProposalLifecycleVerificationError(
            "operator proposal state fields mismatch"
        )
    expected = {
        "adapter_version": OPERATOR_DISPOSITION_ADAPTER_VERSION,
        "operator_proposal_state_schema_version": OPERATOR_PROPOSAL_STATE_VERSION,
        "policy_hash": OPERATOR_DISPOSITION_POLICY_HASH,
        "policy_version": OPERATOR_DISPOSITION_POLICY_VERSION,
    }
    if any(state.get(field) != value for field, value in expected.items()):
        raise OperatorProposalLifecycleVerificationError(
            "operator proposal state policy or version mismatch"
        )
    _hash(state.get("candidate_intent_hash"), "candidate_intent_hash")
    _hash(
        state.get("operator_visible_proposal_hash"),
        "operator_visible_proposal_hash",
    )
    if status != "pending":
        _hash(state.get("disposition_intent_hash"), "disposition_intent_hash")
        _hash(
            state.get("operator_confirmation_hash"),
            "operator_confirmation_hash",
        )
    canonical_json(state)
    return state


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperatorProposalLifecycleVerificationError(
            f"{label} must be an object"
        )
    return deepcopy(dict(value))


def _hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise OperatorProposalLifecycleVerificationError(
            f"{field} must be a lowercase SHA-256 hash"
        )
    return value


__all__ = [
    "OperatorProposalLifecycleVerificationError",
    "verify_operator_proposal_lifecycle",
]
