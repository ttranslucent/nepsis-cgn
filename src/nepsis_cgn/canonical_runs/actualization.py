from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from nepsis_cgn.canonical_runs.operator_disposition import (
    validate_operator_proposal_state,
)
from nepsis_cgn.canonical_runs.store import AdmissionDecision
from nepsis_cgn.contracts.canonical_json import canonical_hash, canonical_json


CANONICAL_ACTUALIZATION_POLICY_VERSION = (
    "nepsis.canonical_actualization_policy@0.1.0"
)
CANONICAL_ACTUALIZATION_ADAPTER_VERSION = (
    "nepsis.canonical_actualization_adapter@0.1.0"
)
PROPOSAL_APPLICATION_VERSION = "nepsis.proposal_application@0.1.0"
ZEROBACK_STATE_VERSION = "nepsis.zeroback_state@0.1.0"

RELEASE_STILL_ACTION_TYPE = "release_still"
PERFORM_ZEROBACK_ACTION_TYPE = "perform_zeroback"
REQUEST_DECISION_COMMIT_ACTION_TYPE = "request_decision_commit"

CANONICAL_ACTUALIZATION_POLICY = {
    "actualization_policy_schema_version": CANONICAL_ACTUALIZATION_POLICY_VERSION,
    "accepted_proposal_application": "validator_only_at_decision_commit",
    "commit_requires": [
        "accepted_exact_proposal",
        "released_still",
        "no_denominator_collapse",
        "no_unresolved_contradictions",
        "no_unresolved_red_hazards",
    ],
    "packet_patch_projection": "fields_by_governed_target_path",
    "still_release_actor": "operator",
    "supported_actions": [
        PERFORM_ZEROBACK_ACTION_TYPE,
        RELEASE_STILL_ACTION_TYPE,
        REQUEST_DECISION_COMMIT_ACTION_TYPE,
    ],
    "zeroback_preserves": [
        "evidence_root_hash",
        "observation_root_hash",
        "population_root_hash",
        "unresolved_contradiction_hashes",
        "unresolved_red_hazard_hashes",
    ],
}
CANONICAL_ACTUALIZATION_POLICY_HASH = canonical_hash(
    CANONICAL_ACTUALIZATION_POLICY
)
CANONICAL_ACTUALIZATION_POLICY_BINDING = {
    "policy_hash": CANONICAL_ACTUALIZATION_POLICY_HASH,
    "policy_id": "canonical_actualization",
    "policy_version": CANONICAL_ACTUALIZATION_POLICY_VERSION,
}
CANONICAL_ACTUALIZATION_VALIDATOR_BINDING = {
    "adapter_version": CANONICAL_ACTUALIZATION_ADAPTER_VERSION,
    "policy_hash": CANONICAL_ACTUALIZATION_POLICY_HASH,
    "policy_version": CANONICAL_ACTUALIZATION_POLICY_VERSION,
    "validator_id": f"validator:{CANONICAL_ACTUALIZATION_ADAPTER_VERSION}",
}

_CHANGE_FIELDS = {
    "base_event_hash",
    "model_proposed_tier",
    "operation_type",
    "proposed_value",
    "target_path",
}
_ALLOWED_TARGET_PREFIXES = (
    "analysis.",
    "decision.",
    "display.",
    "frame.",
    "gate.",
    "risk.",
)


class CanonicalActualizationError(RuntimeError):
    """A canonical actualization transition is malformed or unsafe."""


def validate_release_still(
    request: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> AdmissionDecision:
    binding_error = _policy_binding_error(snapshot)
    if binding_error:
        return _refuse("canonical_actualization_policy_unbound", binding_error)
    _require_action(
        request,
        capability="release_still",
        action_type=RELEASE_STILL_ACTION_TYPE,
    )
    payload = _closed_payload(
        request,
        {"operator_visible_proposal_hash", "run_id"},
    )
    _require_run(payload, snapshot)
    proposal_hash = _hash(
        payload["operator_visible_proposal_hash"],
        "operator_visible_proposal_hash",
    )
    packet = _packet(snapshot)
    state = validate_operator_proposal_state(
        packet.get("operator_proposal_state")
    )
    postcondition = _postcondition(snapshot)
    if state["status"] != "accepted":
        return _refuse(
            "accepted_operator_proposal_required",
            "STILL release requires the exact accepted proposal",
        )
    if state["operator_visible_proposal_hash"] != proposal_hash:
        return _refuse(
            "operator_proposal_hash_mismatch",
            "STILL release does not address the accepted proposal",
        )
    if postcondition["active_hold"] is not True or postcondition["phase"] != (
        "proposal_review"
    ):
        return _refuse(
            "active_still_required",
            "STILL release requires the proposal-review hold",
        )
    return AdmissionDecision.accept(
        event_type="still_released",
        packet_projection=packet,
        postcondition={
            "active_hold": False,
            "governance_status": "ready_for_commit",
            "packet_projection_hash": canonical_hash(packet),
            "phase": "decision_ready",
        },
        validator_binding=CANONICAL_ACTUALIZATION_VALIDATOR_BINDING,
    )


def validate_decision_commit(
    request: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> AdmissionDecision:
    binding_error = _policy_binding_error(snapshot)
    if binding_error:
        return _refuse("canonical_actualization_policy_unbound", binding_error)
    _require_action(
        request,
        capability="request_decision_commit",
        action_type=REQUEST_DECISION_COMMIT_ACTION_TYPE,
    )
    payload = _closed_payload(
        request,
        {"operator_visible_proposal_hash", "requested_change", "run_id"},
    )
    _require_run(payload, snapshot)
    proposal_hash = _hash(
        payload["operator_visible_proposal_hash"],
        "operator_visible_proposal_hash",
    )
    if request.get("artifact_hashes") != [proposal_hash]:
        raise CanonicalActualizationError(
            "decision commit must causally reference exactly its proposal artifact"
        )
    packet = _packet(snapshot)
    state = validate_operator_proposal_state(
        packet.get("operator_proposal_state")
    )
    postcondition = _postcondition(snapshot)
    if state["status"] != "accepted" or state[
        "operator_visible_proposal_hash"
    ] != proposal_hash:
        return _refuse(
            "accepted_operator_proposal_required",
            "decision commit requires the exact accepted proposal",
        )
    if postcondition["active_hold"] is not False or postcondition["phase"] != (
        "decision_ready"
    ):
        return _refuse(
            "still_release_required",
            "decision commit requires a prior exact STILL release",
        )
    context = _context_state(packet)
    blockers = _commit_blockers(context)
    if blockers:
        return _refuse("commit_governance_blocked", blockers[0])

    requested_change = _normalize_requested_change(payload["requested_change"])
    target_path = str(requested_change["target_path"])
    operation_type = str(requested_change["operation_type"])
    effective_tier = _computed_tier(target_path, operation_type)
    if requested_change["model_proposed_tier"] != effective_tier:
        return _refuse(
            "patch_tier_mismatch",
            "model-proposed tier does not match deterministic policy",
        )
    if effective_tier == "T0":
        return _refuse(
            "tier_does_not_commit_packet_state",
            "display-only proposals cannot commit canonical packet state",
        )

    resulting_packet = deepcopy(packet)
    fields = resulting_packet.setdefault("fields", {})
    if not isinstance(fields, dict):
        raise CanonicalActualizationError("packet fields must be an object")
    field_id = f"field_{canonical_hash({'target_path': target_path})[:20]}"
    for existing_id, existing in fields.items():
        if not isinstance(existing_id, str) or not isinstance(existing, Mapping):
            raise CanonicalActualizationError(
                "packet fields must contain governed field records"
            )
        if existing.get("target_path") == target_path and existing_id != field_id:
            raise CanonicalActualizationError(
                "packet field target has a conflicting identity"
            )
    fields[field_id] = {
        "target_path": target_path,
        "value": deepcopy(requested_change["proposed_value"]),
    }
    confirmation = _mapping(
        request.get("operator_confirmation"), "operator confirmation"
    )
    resulting_packet["operator_proposal_application"] = {
        "applied_at": _text(request.get("created_at"), "created_at"),
        "application_intent_hash": _hash(
            request.get("intent_hash"), "application_intent_hash"
        ),
        "base_event_hash": requested_change["base_event_hash"],
        "effective_tier": effective_tier,
        "field_id": field_id,
        "operation_type": operation_type,
        "operator_confirmation_hash": canonical_hash(confirmation),
        "operator_visible_proposal_hash": proposal_hash,
        "proposal_application_schema_version": PROPOSAL_APPLICATION_VERSION,
        "requested_change_hash": canonical_hash(requested_change),
        "target_path": target_path,
    }
    canonical_json(resulting_packet["operator_proposal_application"])
    return AdmissionDecision.accept(
        event_type="decision_committed",
        packet_projection=resulting_packet,
        postcondition={
            "active_hold": False,
            "governance_status": "committed",
            "packet_projection_hash": canonical_hash(resulting_packet),
            "phase": "committed",
        },
        validator_binding=CANONICAL_ACTUALIZATION_VALIDATOR_BINDING,
    )


def validate_zeroback(
    request: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> AdmissionDecision:
    binding_error = _policy_binding_error(snapshot)
    if binding_error:
        return _refuse("canonical_actualization_policy_unbound", binding_error)
    _require_action(
        request,
        capability="perform_zeroback",
        action_type=PERFORM_ZEROBACK_ACTION_TYPE,
    )
    payload = _closed_payload(
        request, {"replacement_frame_root_hash", "run_id"}
    )
    _require_run(payload, snapshot)
    replacement = _hash(
        payload["replacement_frame_root_hash"],
        "replacement_frame_root_hash",
    )
    packet = _packet(snapshot)
    context = _context_state(packet)
    prior_frame = _hash(context.get("frame_root_hash"), "frame_root_hash")
    if replacement == prior_frame:
        return _refuse(
            "zeroback_requires_new_frame",
            "ZeroBack requires a distinct replacement frame root",
        )
    previous = packet.get("zeroback_state")
    count = 1
    if previous is not None:
        prior_state = _mapping(previous, "zeroback_state")
        prior_count = prior_state.get("count")
        if isinstance(prior_count, bool) or not isinstance(prior_count, int):
            raise CanonicalActualizationError("zeroback count is invalid")
        count = prior_count + 1
    resulting_packet = deepcopy(packet)
    resulting_context = _context_state(resulting_packet)
    resulting_context["frame_root_hash"] = replacement
    resulting_packet["context_state"] = resulting_context
    resulting_packet["zeroback_state"] = {
        "count": count,
        "performed_at": _text(request.get("created_at"), "created_at"),
        "preserved_evidence_root_hash": _hash(
            context.get("evidence_root_hash"), "evidence_root_hash"
        ),
        "preserved_observation_root_hash": _hash(
            context.get("observation_root_hash"), "observation_root_hash"
        ),
        "preserved_population_root_hash": _hash(
            context.get("population_root_hash"), "population_root_hash"
        ),
        "preserved_unresolved_contradiction_hashes": _hash_array(
            context.get("unresolved_contradiction_hashes"),
            "unresolved_contradiction_hashes",
        ),
        "preserved_unresolved_red_hazard_hashes": _hash_array(
            context.get("unresolved_red_hazard_hashes"),
            "unresolved_red_hazard_hashes",
        ),
        "prior_frame_root_hash": prior_frame,
        "replacement_frame_root_hash": replacement,
        "zeroback_intent_hash": _hash(
            request.get("intent_hash"), "zeroback_intent_hash"
        ),
        "zeroback_state_schema_version": ZEROBACK_STATE_VERSION,
    }
    canonical_json(resulting_packet["zeroback_state"])
    return AdmissionDecision.accept(
        event_type="zeroback_performed",
        packet_projection=resulting_packet,
        postcondition={
            "active_hold": True,
            "governance_status": "zeroback",
            "packet_projection_hash": canonical_hash(resulting_packet),
            "phase": "zeroback",
        },
        validator_binding=CANONICAL_ACTUALIZATION_VALIDATOR_BINDING,
    )


def normalize_requested_change(value: Any) -> dict[str, Any]:
    return _normalize_requested_change(value)


def _normalize_requested_change(value: Any) -> dict[str, Any]:
    change = _mapping(value, "requested_change")
    if set(change) != _CHANGE_FIELDS:
        raise CanonicalActualizationError("requested_change fields are not closed")
    change["base_event_hash"] = _hash(
        change["base_event_hash"], "base_event_hash"
    )
    change["target_path"] = _text(change["target_path"], "target_path")
    change["operation_type"] = _text(
        change["operation_type"], "operation_type"
    )
    change["model_proposed_tier"] = _text(
        change["model_proposed_tier"], "model_proposed_tier"
    )
    if change["operation_type"] not in {"extract", "replace"}:
        raise CanonicalActualizationError(
            "requested_change operation_type must be extract or replace"
        )
    if change["model_proposed_tier"] not in {"T0", "T1", "T2", "T3", "T4"}:
        raise CanonicalActualizationError("requested_change tier is unsupported")
    canonical_json(change)
    return change


def _computed_tier(target: str, operation: str) -> str:
    if not (target == "known_facts" or target.startswith(_ALLOWED_TARGET_PREFIXES)):
        raise CanonicalActualizationError(
            "requested_change target_path is not allowed by policy"
        )
    if target.startswith("display."):
        return "T0"
    if target == "known_facts" or operation == "extract":
        return "T1"
    if target in {"frame.constraints_hard", "frame.red_definition"} or (
        target.startswith("risk.")
    ):
        return "T3"
    if target.startswith(("decision.", "gate.")):
        return "T4"
    return "T2"


def _commit_blockers(context: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if context.get("denominator_collapse_active") is not False:
        blockers.append("denominator collapse remains active")
    if _hash_array(
        context.get("unresolved_contradiction_hashes"),
        "unresolved_contradiction_hashes",
    ):
        blockers.append("unresolved contradictions remain")
    if _hash_array(
        context.get("unresolved_red_hazard_hashes"),
        "unresolved_red_hazard_hashes",
    ):
        blockers.append("unresolved RED hazards remain")
    return blockers


def _policy_binding_error(snapshot: Mapping[str, Any]) -> str:
    bindings = snapshot.get("system_policy_bindings")
    if not isinstance(bindings, list):
        return "run system policy bindings are unavailable"
    matches = [
        dict(row)
        for row in bindings
        if isinstance(row, Mapping)
        and row.get("policy_id")
        == CANONICAL_ACTUALIZATION_POLICY_BINDING["policy_id"]
    ]
    if matches != [CANONICAL_ACTUALIZATION_POLICY_BINDING]:
        return "run does not pin the exact canonical actualization policy"
    return ""


def _refuse(reason_code: str, detail: str) -> AdmissionDecision:
    return AdmissionDecision.refuse(
        reason_code=reason_code,
        detail=detail,
        validator_binding=CANONICAL_ACTUALIZATION_VALIDATOR_BINDING,
    )


def _require_action(
    request: Mapping[str, Any], *, capability: str, action_type: str
) -> None:
    if request.get("capability") != capability or request.get(
        "action_type"
    ) != action_type:
        raise CanonicalActualizationError(
            f"actualization action requires {capability}/{action_type}"
        )


def _closed_payload(
    request: Mapping[str, Any], fields: set[str]
) -> dict[str, Any]:
    payload = _mapping(request.get("payload"), "actualization payload")
    if set(payload) != fields:
        raise CanonicalActualizationError(
            "actualization payload fields are not closed"
        )
    return payload


def _require_run(payload: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    if payload.get("run_id") != snapshot.get("run_id"):
        raise CanonicalActualizationError("actualization run_id mismatch")


def _packet(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(snapshot.get("packet_projection"), "packet projection")


def _postcondition(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(snapshot.get("postcondition"), "postcondition")
    if set(value) != {
        "active_hold",
        "governance_status",
        "packet_projection_hash",
        "phase",
    }:
        raise CanonicalActualizationError("postcondition fields are invalid")
    return value


def _context_state(packet: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(packet.get("context_state"), "context_state")


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalActualizationError(f"{label} must be an object")
    return deepcopy(dict(value))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CanonicalActualizationError(f"{field} must be a non-empty string")
    return value


def _hash(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise CanonicalActualizationError(
            f"{field} must be a lowercase SHA-256 hash"
        )
    return text


def _hash_array(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) != len(set(value)):
        raise CanonicalActualizationError(f"{field} must be a unique array")
    normalized = [_hash(item, f"{field} item") for item in value]
    if normalized != sorted(normalized):
        raise CanonicalActualizationError(f"{field} must be sorted")
    return normalized


__all__ = [
    "CANONICAL_ACTUALIZATION_ADAPTER_VERSION",
    "CANONICAL_ACTUALIZATION_POLICY",
    "CANONICAL_ACTUALIZATION_POLICY_BINDING",
    "CANONICAL_ACTUALIZATION_POLICY_HASH",
    "CANONICAL_ACTUALIZATION_POLICY_VERSION",
    "CANONICAL_ACTUALIZATION_VALIDATOR_BINDING",
    "CanonicalActualizationError",
    "PERFORM_ZEROBACK_ACTION_TYPE",
    "PROPOSAL_APPLICATION_VERSION",
    "RELEASE_STILL_ACTION_TYPE",
    "REQUEST_DECISION_COMMIT_ACTION_TYPE",
    "ZEROBACK_STATE_VERSION",
    "normalize_requested_change",
    "validate_decision_commit",
    "validate_release_still",
    "validate_zeroback",
]
