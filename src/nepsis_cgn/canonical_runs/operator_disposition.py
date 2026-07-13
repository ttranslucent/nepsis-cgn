from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from nepsis_cgn.canonical_runs.store import AdmissionDecision
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

OPERATOR_DISPOSITION_POLICY = {
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
OPERATOR_DISPOSITION_POLICY_HASH = canonical_hash(OPERATOR_DISPOSITION_POLICY)
OPERATOR_DISPOSITION_POLICY_BINDING = {
    "policy_hash": OPERATOR_DISPOSITION_POLICY_HASH,
    "policy_id": "operator_disposition",
    "policy_version": OPERATOR_DISPOSITION_POLICY_VERSION,
}
OPERATOR_DISPOSITION_VALIDATOR_BINDING = {
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
_TERMINAL_STATUS = {
    "accept": "accepted",
    "defer": "deferred",
    "reject": "rejected",
}


class OperatorDispositionAdapterError(RuntimeError):
    """The proposal lifecycle projection is malformed or cannot be trusted."""


def validate_model_candidate_transition(
    request: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> AdmissionDecision:
    """Record one exact pending proposal without applying its requested change."""

    binding_error = _policy_binding_error(snapshot)
    if binding_error:
        return _refuse("operator_disposition_policy_unbound", binding_error)
    if request.get("capability") != "submit_model_candidate":
        raise OperatorDispositionAdapterError(
            "candidate transition requires submit_model_candidate"
        )
    payload = _mapping(request.get("payload"), "model candidate payload")
    expected_payload_fields = {
        "context_manifest_hash",
        "external_codex_ref_hash",
        "model_candidate_schema_version",
        "normalized_change",
        "operator_visible_proposal_hash",
        "proposal_id",
    }
    if set(payload) != expected_payload_fields:
        raise OperatorDispositionAdapterError(
            "model candidate payload fields are not closed"
        )
    proposal_hash = _hash(
        request.get("operator_visible_proposal_hash"),
        "operator_visible_proposal_hash",
    )
    if payload.get("operator_visible_proposal_hash") != proposal_hash:
        raise OperatorDispositionAdapterError(
            "candidate payload proposal hash does not match request binding"
        )

    packet = _mapping(snapshot.get("packet_projection"), "packet projection")
    prior_postcondition = _mapping(snapshot.get("postcondition"), "postcondition")
    if prior_postcondition.get("phase") == "committed":
        return _refuse(
            "zeroback_required_after_commit",
            "a committed run requires ZeroBack before another proposal",
        )
    current = packet.get("operator_proposal_state")
    if current is not None:
        state = validate_operator_proposal_state(current)
        if state["status"] == "pending":
            return _refuse(
                "pending_operator_proposal_exists",
                "an exact pending proposal must be disposed before replacement",
            )

    pending = {
        "adapter_version": OPERATOR_DISPOSITION_ADAPTER_VERSION,
        "candidate_created_at": _text(request.get("created_at"), "created_at"),
        "candidate_intent_hash": _hash(
            request.get("intent_hash"), "candidate_intent_hash"
        ),
        "operator_proposal_state_schema_version": OPERATOR_PROPOSAL_STATE_VERSION,
        "operator_visible_proposal_hash": proposal_hash,
        "policy_hash": OPERATOR_DISPOSITION_POLICY_HASH,
        "policy_version": OPERATOR_DISPOSITION_POLICY_VERSION,
        "status": "pending",
    }
    resulting_packet = deepcopy(packet)
    resulting_packet["operator_proposal_state"] = pending
    return AdmissionDecision.accept(
        event_type="model_candidate_recorded",
        packet_projection=resulting_packet,
        postcondition=_proposal_review_postcondition(resulting_packet),
        validator_binding=OPERATOR_DISPOSITION_VALIDATOR_BINDING,
    )


def validate_operator_disposition(
    request: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> AdmissionDecision:
    """Record accept/reject/defer of the pending proposal; apply no change."""

    binding_error = _policy_binding_error(snapshot)
    if binding_error:
        return _refuse("operator_disposition_policy_unbound", binding_error)
    if request.get("capability") != "submit_operator_disposition":
        raise OperatorDispositionAdapterError(
            "disposition requires submit_operator_disposition"
        )
    if request.get("action_type") != OPERATOR_DISPOSITION_ACTION_TYPE:
        raise OperatorDispositionAdapterError(
            "unsupported operator disposition action type"
        )
    payload = _mapping(request.get("payload"), "operator disposition payload")
    if set(payload) != {
        "disposition",
        "operator_visible_proposal_hash",
        "run_id",
    }:
        raise OperatorDispositionAdapterError(
            "operator disposition payload fields are not closed"
        )
    disposition = payload.get("disposition")
    if disposition not in _TERMINAL_STATUS:
        raise OperatorDispositionAdapterError(
            "operator disposition must be accept, defer, or reject"
        )
    proposal_hash = _hash(
        payload.get("operator_visible_proposal_hash"),
        "operator_visible_proposal_hash",
    )
    if request.get("operator_visible_proposal_hash") != proposal_hash:
        raise OperatorDispositionAdapterError(
            "disposition proposal hash does not match request binding"
        )
    if request.get("artifact_hashes") != [proposal_hash]:
        raise OperatorDispositionAdapterError(
            "disposition must causally reference exactly its proposal artifact"
        )

    packet = _mapping(snapshot.get("packet_projection"), "packet projection")
    current_raw = packet.get("operator_proposal_state")
    if current_raw is None:
        return _refuse(
            "pending_operator_proposal_required",
            "operator disposition requires one pending proposal",
        )
    current = validate_operator_proposal_state(current_raw)
    if current["status"] != "pending":
        return _refuse(
            "pending_operator_proposal_required",
            "the proposal was already disposed",
        )
    if current["operator_visible_proposal_hash"] != proposal_hash:
        return _refuse(
            "operator_proposal_hash_mismatch",
            "the disposition does not address the exact pending proposal",
        )

    confirmation = _mapping(
        request.get("operator_confirmation"), "operator confirmation"
    )
    terminal = {
        **current,
        "disposed_at": _text(request.get("created_at"), "created_at"),
        "disposition_intent_hash": _hash(
            request.get("intent_hash"), "disposition_intent_hash"
        ),
        "operator_confirmation_hash": canonical_hash(confirmation),
        "status": _TERMINAL_STATUS[str(disposition)],
    }
    validate_operator_proposal_state(terminal)
    resulting_packet = deepcopy(packet)
    resulting_packet["operator_proposal_state"] = terminal
    return AdmissionDecision.accept(
        event_type=OPERATOR_DISPOSITION_EVENT_TYPE,
        packet_projection=resulting_packet,
        postcondition=_disposition_postcondition(
            snapshot,
            resulting_packet,
            disposition=str(disposition),
        ),
        validator_binding=OPERATOR_DISPOSITION_VALIDATOR_BINDING,
    )


def validate_operator_proposal_state(value: Any) -> dict[str, Any]:
    state = _mapping(value, "operator proposal state")
    if state.get("operator_proposal_state_schema_version") != (
        OPERATOR_PROPOSAL_STATE_VERSION
    ):
        raise OperatorDispositionAdapterError(
            "operator proposal state version is unsupported"
        )
    status = state.get("status")
    expected_fields = _PENDING_FIELDS if status == "pending" else _DISPOSED_FIELDS
    if status not in {"pending", "accepted", "deferred", "rejected"}:
        raise OperatorDispositionAdapterError(
            "operator proposal state status is unsupported"
        )
    if set(state) != expected_fields:
        raise OperatorDispositionAdapterError(
            "operator proposal state fields are not closed"
        )
    if state.get("adapter_version") != OPERATOR_DISPOSITION_ADAPTER_VERSION:
        raise OperatorDispositionAdapterError(
            "operator proposal state adapter version mismatch"
        )
    if state.get("policy_hash") != OPERATOR_DISPOSITION_POLICY_HASH:
        raise OperatorDispositionAdapterError(
            "operator proposal state policy hash mismatch"
        )
    if state.get("policy_version") != OPERATOR_DISPOSITION_POLICY_VERSION:
        raise OperatorDispositionAdapterError(
            "operator proposal state policy version mismatch"
        )
    for field in ("candidate_intent_hash", "operator_visible_proposal_hash"):
        _hash(state.get(field), field)
    _text(state.get("candidate_created_at"), "candidate_created_at")
    if status != "pending":
        _text(state.get("disposed_at"), "disposed_at")
        _hash(state.get("disposition_intent_hash"), "disposition_intent_hash")
        _hash(
            state.get("operator_confirmation_hash"),
            "operator_confirmation_hash",
        )
    canonical_json(state)
    return state


def _policy_binding_error(snapshot: Mapping[str, Any]) -> str:
    bindings = snapshot.get("system_policy_bindings")
    if not isinstance(bindings, list):
        return "run system policy bindings are unavailable"
    matches = [
        dict(row)
        for row in bindings
        if isinstance(row, Mapping)
        and row.get("policy_id") == OPERATOR_DISPOSITION_POLICY_BINDING["policy_id"]
    ]
    if matches != [OPERATOR_DISPOSITION_POLICY_BINDING]:
        return "run does not pin the exact operator disposition policy"
    return ""


def _proposal_review_postcondition(packet: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "active_hold": True,
        "governance_status": "proposal_pending",
        "packet_projection_hash": canonical_hash(dict(packet)),
        "phase": "proposal_review",
    }


def _disposition_postcondition(
    snapshot: Mapping[str, Any], packet: Mapping[str, Any]
    , *, disposition: str
) -> dict[str, Any]:
    prior = _mapping(snapshot.get("postcondition"), "postcondition")
    if set(prior) != {
        "active_hold",
        "governance_status",
        "packet_projection_hash",
        "phase",
    }:
        raise OperatorDispositionAdapterError("postcondition fields are invalid")
    accepted = disposition == "accept"
    return {
        "active_hold": accepted,
        "governance_status": "proposal_accepted" if accepted else "open",
        "packet_projection_hash": canonical_hash(dict(packet)),
        "phase": "proposal_review" if accepted else "intake",
    }


def _refuse(reason_code: str, detail: str) -> AdmissionDecision:
    return AdmissionDecision.refuse(
        reason_code=reason_code,
        detail=detail,
        validator_binding=OPERATOR_DISPOSITION_VALIDATOR_BINDING,
    )


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise OperatorDispositionAdapterError(f"{label} must be an object")
    return deepcopy(dict(value))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise OperatorDispositionAdapterError(
            f"{field} must be a non-empty string"
        )
    return value


def _hash(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise OperatorDispositionAdapterError(
            f"{field} must be a lowercase SHA-256 hash"
        )
    return text


__all__ = [
    "OPERATOR_DISPOSITION_ACTION_TYPE",
    "OPERATOR_DISPOSITION_ADAPTER_VERSION",
    "OPERATOR_DISPOSITION_EVENT_TYPE",
    "OPERATOR_DISPOSITION_POLICY",
    "OPERATOR_DISPOSITION_POLICY_BINDING",
    "OPERATOR_DISPOSITION_POLICY_HASH",
    "OPERATOR_DISPOSITION_POLICY_VERSION",
    "OPERATOR_DISPOSITION_VALIDATOR_BINDING",
    "OPERATOR_PROPOSAL_STATE_VERSION",
    "OperatorDispositionAdapterError",
    "validate_model_candidate_transition",
    "validate_operator_disposition",
    "validate_operator_proposal_state",
]
