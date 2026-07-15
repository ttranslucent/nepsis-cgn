from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from nepsis_cgn.contracts.canonical_json import canonical_hash, canonical_json


_POLICY_VERSION = "nepsis.canonical_actualization_policy@0.1.0"
_ADAPTER_VERSION = "nepsis.canonical_actualization_adapter@0.1.0"
_APPLICATION_VERSION = "nepsis.proposal_application@0.1.0"
_ZEROBACK_VERSION = "nepsis.zeroback_state@0.1.0"
_POLICY = {
    "actualization_policy_schema_version": _POLICY_VERSION,
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
        "perform_zeroback",
        "release_still",
        "request_decision_commit",
    ],
    "zeroback_preserves": [
        "evidence_root_hash",
        "observation_root_hash",
        "population_root_hash",
        "unresolved_contradiction_hashes",
        "unresolved_red_hazard_hashes",
    ],
}
_POLICY_HASH = canonical_hash(_POLICY)
_POLICY_BINDING = {
    "policy_hash": _POLICY_HASH,
    "policy_id": "canonical_actualization",
    "policy_version": _POLICY_VERSION,
}
_VALIDATOR_BINDING = {
    "adapter_version": _ADAPTER_VERSION,
    "policy_hash": _POLICY_HASH,
    "policy_version": _POLICY_VERSION,
    "validator_id": f"validator:{_ADAPTER_VERSION}",
}
_CHANGE_FIELDS = {
    "base_event_hash",
    "model_proposed_tier",
    "operation_type",
    "proposed_value",
    "target_path",
}
_TARGET_PREFIXES = (
    "analysis.",
    "decision.",
    "display.",
    "frame.",
    "gate.",
    "risk.",
)


class CanonicalActualizationVerificationError(ValueError):
    pass


def verify_canonical_actualization(
    *,
    events: list[dict[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    final_packet_projection: Mapping[str, Any],
    final_postcondition: Mapping[str, Any],
    system_policy_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    if not events or events[0].get("event_type") != "run_created":
        raise CanonicalActualizationVerificationError(
            "canonical actualization requires run_created genesis"
        )
    genesis = _mapping(events[0].get("payload"), "run_created payload")
    packet = _mapping(
        genesis.get("initial_packet_projection"), "initial packet projection"
    )
    postcondition = _postcondition(genesis.get("initial_postcondition"))
    counts = {"decision_committed": 0, "still_released": 0, "zeroback_performed": 0}

    for event in events[1:]:
        payload = _mapping(event.get("payload"), "event payload")
        next_packet_raw = payload.get("packet_projection")
        next_postcondition_raw = payload.get("postcondition")
        if next_packet_raw is None or next_postcondition_raw is None:
            continue
        next_packet = _mapping(next_packet_raw, "event packet projection")
        next_postcondition = _postcondition(next_postcondition_raw)
        event_type = event.get("event_type")
        if event_type in counts:
            _verify_policy_binding(system_policy_bindings)
            counts[str(event_type)] += 1
        if event_type == "still_released":
            _verify_still_release(
                event=event,
                payload=payload,
                prior_packet=packet,
                prior_postcondition=postcondition,
                resulting_packet=next_packet,
                resulting_postcondition=next_postcondition,
                artifacts=artifacts,
            )
        elif event_type == "decision_committed":
            _verify_decision_commit(
                event=event,
                payload=payload,
                prior_packet=packet,
                prior_postcondition=postcondition,
                resulting_packet=next_packet,
                resulting_postcondition=next_postcondition,
                artifacts=artifacts,
            )
        elif event_type == "zeroback_performed":
            _verify_zeroback(
                event=event,
                payload=payload,
                prior_packet=packet,
                resulting_packet=next_packet,
                resulting_postcondition=next_postcondition,
            )
        packet = next_packet
        postcondition = next_postcondition

    if canonical_json(packet) != canonical_json(dict(final_packet_projection)):
        raise CanonicalActualizationVerificationError(
            "actualization replay packet does not match final projection"
        )
    if canonical_json(postcondition) != canonical_json(dict(final_postcondition)):
        raise CanonicalActualizationVerificationError(
            "actualization replay postcondition does not match final projection"
        )
    return {**counts, "observed": any(counts.values())}


def _verify_still_release(
    *,
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
    prior_packet: Mapping[str, Any],
    prior_postcondition: Mapping[str, Any],
    resulting_packet: Mapping[str, Any],
    resulting_postcondition: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    _event_authority(event, payload, capability="release_still", validator=False)
    action = _action_payload(
        event,
        payload,
        capability="release_still",
        action_type="release_still",
        fields={"operator_visible_proposal_hash", "run_id"},
    )
    proposal_hash = _proposal_hash(action, prior_packet, artifacts)
    if event.get("caused_by_artifact_hashes") != [proposal_hash]:
        raise CanonicalActualizationVerificationError(
            "STILL release proposal cause mismatch"
        )
    if canonical_json(dict(prior_packet)) != canonical_json(dict(resulting_packet)):
        raise CanonicalActualizationVerificationError(
            "STILL release changed packet state"
        )
    if prior_postcondition.get("active_hold") is not True or prior_postcondition.get(
        "phase"
    ) != "proposal_review":
        raise CanonicalActualizationVerificationError(
            "STILL release lacks the proposal-review hold"
        )
    _expected_postcondition(
        resulting_postcondition,
        resulting_packet,
        active_hold=False,
        governance_status="ready_for_commit",
        phase="decision_ready",
    )


def _verify_decision_commit(
    *,
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
    prior_packet: Mapping[str, Any],
    prior_postcondition: Mapping[str, Any],
    resulting_packet: Mapping[str, Any],
    resulting_postcondition: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> None:
    _event_authority(
        event, payload, capability="request_decision_commit", validator=True
    )
    action = _action_payload(
        event,
        payload,
        capability="request_decision_commit",
        action_type="request_decision_commit",
        fields={"operator_visible_proposal_hash", "requested_change", "run_id"},
    )
    proposal_hash = _proposal_hash(action, prior_packet, artifacts)
    if event.get("caused_by_artifact_hashes") != [proposal_hash]:
        raise CanonicalActualizationVerificationError(
            "decision commit proposal cause mismatch"
        )
    if prior_postcondition.get("active_hold") is not False or prior_postcondition.get(
        "phase"
    ) != "decision_ready":
        raise CanonicalActualizationVerificationError(
            "decision commit lacks a prior STILL release"
        )
    context = _mapping(prior_packet.get("context_state"), "context_state")
    if context.get("denominator_collapse_active") is not False:
        raise CanonicalActualizationVerificationError(
            "decision committed during denominator collapse"
        )
    if _hash_array(context.get("unresolved_contradiction_hashes")):
        raise CanonicalActualizationVerificationError(
            "decision committed with unresolved contradictions"
        )
    if _hash_array(context.get("unresolved_red_hazard_hashes")):
        raise CanonicalActualizationVerificationError(
            "decision committed with unresolved RED hazards"
        )

    change = _requested_change(action.get("requested_change"))
    proposal = _proposal_artifact(proposal_hash, artifacts)
    if canonical_json(change) != canonical_json(
        _requested_change(proposal.get("requested_change"))
    ):
        raise CanonicalActualizationVerificationError(
            "decision commit change differs from proposal artifact"
        )
    target = str(change["target_path"])
    tier = _tier(target, str(change["operation_type"]))
    if change["model_proposed_tier"] != tier or tier == "T0":
        raise CanonicalActualizationVerificationError(
            "decision commit tier is not deterministically committable"
        )
    expected_packet = deepcopy(dict(prior_packet))
    fields = expected_packet.setdefault("fields", {})
    if not isinstance(fields, dict):
        raise CanonicalActualizationVerificationError(
            "packet fields projection is invalid"
        )
    field_id = f"field_{canonical_hash({'target_path': target})[:20]}"
    fields[field_id] = {
        "target_path": target,
        "value": deepcopy(change["proposed_value"]),
    }
    confirmation = _confirmation(event, payload)
    expected_packet["operator_proposal_application"] = {
        "applied_at": event.get("created_at"),
        "application_intent_hash": event.get("intent_hash"),
        "base_event_hash": change["base_event_hash"],
        "effective_tier": tier,
        "field_id": field_id,
        "operation_type": change["operation_type"],
        "operator_confirmation_hash": canonical_hash(confirmation),
        "operator_visible_proposal_hash": proposal_hash,
        "proposal_application_schema_version": _APPLICATION_VERSION,
        "requested_change_hash": canonical_hash(change),
        "target_path": target,
    }
    if canonical_json(expected_packet) != canonical_json(dict(resulting_packet)):
        raise CanonicalActualizationVerificationError(
            "validator-owned proposal application projection mismatch"
        )
    _expected_postcondition(
        resulting_postcondition,
        resulting_packet,
        active_hold=False,
        governance_status="committed",
        phase="committed",
    )


def _verify_zeroback(
    *,
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
    prior_packet: Mapping[str, Any],
    resulting_packet: Mapping[str, Any],
    resulting_postcondition: Mapping[str, Any],
) -> None:
    _event_authority(event, payload, capability="perform_zeroback", validator=False)
    action = _action_payload(
        event,
        payload,
        capability="perform_zeroback",
        action_type="perform_zeroback",
        fields={"replacement_frame_root_hash", "run_id"},
    )
    replacement = _hash(action.get("replacement_frame_root_hash"))
    prior_context = _mapping(prior_packet.get("context_state"), "context_state")
    prior_frame = _hash(prior_context.get("frame_root_hash"))
    if replacement == prior_frame:
        raise CanonicalActualizationVerificationError(
            "ZeroBack did not replace the frame root"
        )
    expected = deepcopy(dict(prior_packet))
    expected_context = _mapping(expected.get("context_state"), "context_state")
    expected_context["frame_root_hash"] = replacement
    expected["context_state"] = expected_context
    previous = prior_packet.get("zeroback_state")
    count = 1
    if previous is not None:
        previous_count = _mapping(previous, "zeroback_state").get("count")
        if isinstance(previous_count, bool) or not isinstance(previous_count, int):
            raise CanonicalActualizationVerificationError(
                "prior ZeroBack count is invalid"
            )
        count = previous_count + 1
    expected["zeroback_state"] = {
        "count": count,
        "performed_at": event.get("created_at"),
        "preserved_evidence_root_hash": _hash(
            prior_context.get("evidence_root_hash")
        ),
        "preserved_observation_root_hash": _hash(
            prior_context.get("observation_root_hash")
        ),
        "preserved_population_root_hash": _hash(
            prior_context.get("population_root_hash")
        ),
        "preserved_unresolved_contradiction_hashes": _hash_array(
            prior_context.get("unresolved_contradiction_hashes")
        ),
        "preserved_unresolved_red_hazard_hashes": _hash_array(
            prior_context.get("unresolved_red_hazard_hashes")
        ),
        "prior_frame_root_hash": prior_frame,
        "replacement_frame_root_hash": replacement,
        "zeroback_intent_hash": event.get("intent_hash"),
        "zeroback_state_schema_version": _ZEROBACK_VERSION,
    }
    if canonical_json(expected) != canonical_json(dict(resulting_packet)):
        raise CanonicalActualizationVerificationError(
            "ZeroBack failed to preserve protected context"
        )
    _expected_postcondition(
        resulting_postcondition,
        resulting_packet,
        active_hold=True,
        governance_status="zeroback",
        phase="zeroback",
    )


def _event_authority(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    capability: str,
    validator: bool,
) -> None:
    expected_class = "validator" if validator else "operator"
    if event.get("provenance_class") != expected_class or not str(
        event.get("actor_id", "")
    ).startswith(f"{expected_class}:"):
        raise CanonicalActualizationVerificationError(
            "actualization event authority mismatch"
        )
    if payload.get("capability") != capability or payload.get(
        "validator_binding"
    ) != _VALIDATOR_BINDING:
        raise CanonicalActualizationVerificationError(
            "actualization capability or validator binding mismatch"
        )
    if validator and not str(payload.get("requested_by_actor_id", "")).startswith(
        "operator:"
    ):
        raise CanonicalActualizationVerificationError(
            "validator commit lacks operator request provenance"
        )


def _action_payload(
    event: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    capability: str,
    action_type: str,
    fields: set[str],
) -> dict[str, Any]:
    action = _mapping(payload.get("action_payload"), "action payload")
    if set(action) != fields or action.get("run_id") != event.get("run_id"):
        raise CanonicalActualizationVerificationError(
            "actualization action payload mismatch"
        )
    confirmation = _confirmation(event, payload)
    expected_intent = canonical_hash(
        {
            "action": action_type,
            "capability": capability,
            "operator_confirmation": confirmation,
            "payload": action,
        }
    )
    if event.get("intent_hash") != expected_intent:
        raise CanonicalActualizationVerificationError(
            "actualization intent does not bind confirmation and payload"
        )
    return action


def _confirmation(
    event: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    confirmation = _mapping(
        payload.get("operator_confirmation"), "operator confirmation"
    )
    if set(confirmation) != {
        "confirmed",
        "confirmed_at",
        "consequence_acknowledged",
        "rationale",
    } or confirmation.get("confirmed") is not True or confirmation.get(
        "consequence_acknowledged"
    ) is not True:
        raise CanonicalActualizationVerificationError(
            "actualization confirmation is not exact and affirmative"
        )
    if confirmation.get("confirmed_at") != event.get("created_at") or not isinstance(
        confirmation.get("rationale"), str
    ) or not confirmation["rationale"]:
        raise CanonicalActualizationVerificationError(
            "actualization confirmation timestamp or rationale mismatch"
        )
    return confirmation


def _proposal_hash(
    action: Mapping[str, Any],
    packet: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> str:
    proposal_hash = _hash(action.get("operator_visible_proposal_hash"))
    state = _mapping(packet.get("operator_proposal_state"), "proposal state")
    if state.get("status") != "accepted" or state.get(
        "operator_visible_proposal_hash"
    ) != proposal_hash:
        raise CanonicalActualizationVerificationError(
            "actualization does not address the accepted proposal"
        )
    _proposal_artifact(proposal_hash, artifacts)
    return proposal_hash


def _proposal_artifact(
    proposal_hash: str, artifacts: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    row = artifacts.get(proposal_hash)
    if not isinstance(row, Mapping) or row.get(
        "artifact_schema_version"
    ) != "nepsis.operator_visible_proposal@0.1.0" or row.get("roles") != [
        "operator_visible_proposal"
    ]:
        raise CanonicalActualizationVerificationError(
            "actualization proposal artifact is unavailable"
        )
    artifact = _mapping(row.get("artifact"), "proposal artifact")
    if canonical_hash(artifact) != proposal_hash:
        raise CanonicalActualizationVerificationError(
            "actualization proposal artifact hash mismatch"
        )
    return artifact


def _requested_change(value: Any) -> dict[str, Any]:
    change = _mapping(value, "requested_change")
    if set(change) != _CHANGE_FIELDS:
        raise CanonicalActualizationVerificationError(
            "requested_change fields mismatch"
        )
    change["base_event_hash"] = _hash(change["base_event_hash"])
    for field in ("model_proposed_tier", "operation_type", "target_path"):
        if not isinstance(change.get(field), str) or not change[field]:
            raise CanonicalActualizationVerificationError(
                f"requested_change {field} is invalid"
            )
    if change["operation_type"] not in {"extract", "replace"}:
        raise CanonicalActualizationVerificationError(
            "requested_change operation is unsupported"
        )
    canonical_json(change)
    return change


def _tier(target: str, operation: str) -> str:
    if not (target == "known_facts" or target.startswith(_TARGET_PREFIXES)):
        raise CanonicalActualizationVerificationError(
            "requested_change target is outside policy"
        )
    if target.startswith("display."):
        return "T0"
    if target == "known_facts" or operation == "extract":
        return "T1"
    if target in {"frame.constraints_hard", "frame.red_definition"} or target.startswith(
        "risk."
    ):
        return "T3"
    if target.startswith(("decision.", "gate.")):
        return "T4"
    return "T2"


def _verify_policy_binding(bindings: list[dict[str, Any]]) -> None:
    matches = [
        row
        for row in bindings
        if isinstance(row, dict) and row.get("policy_id") == "canonical_actualization"
    ]
    if matches != [_POLICY_BINDING]:
        raise CanonicalActualizationVerificationError(
            "run does not pin the exact canonical actualization policy"
        )


def _expected_postcondition(
    value: Mapping[str, Any],
    packet: Mapping[str, Any],
    *,
    active_hold: bool,
    governance_status: str,
    phase: str,
) -> None:
    expected = {
        "active_hold": active_hold,
        "governance_status": governance_status,
        "packet_projection_hash": canonical_hash(dict(packet)),
        "phase": phase,
    }
    if canonical_json(dict(value)) != canonical_json(expected):
        raise CanonicalActualizationVerificationError(
            "actualization postcondition mismatch"
        )


def _postcondition(value: Any) -> dict[str, Any]:
    postcondition = _mapping(value, "postcondition")
    if set(postcondition) != {
        "active_hold",
        "governance_status",
        "packet_projection_hash",
        "phase",
    }:
        raise CanonicalActualizationVerificationError(
            "postcondition fields mismatch"
        )
    return postcondition


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalActualizationVerificationError(f"{label} must be an object")
    return deepcopy(dict(value))


def _hash(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise CanonicalActualizationVerificationError(
            "expected a lowercase SHA-256 hash"
        )
    return value


def _hash_array(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) != len(set(value)):
        raise CanonicalActualizationVerificationError(
            "expected a unique hash array"
        )
    normalized = [_hash(item) for item in value]
    if normalized != sorted(normalized):
        raise CanonicalActualizationVerificationError(
            "hash array must be sorted"
        )
    return normalized


__all__ = [
    "CanonicalActualizationVerificationError",
    "verify_canonical_actualization",
]
