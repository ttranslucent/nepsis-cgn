from __future__ import annotations

from typing import Any, Literal

LoopDecisionStatus = Literal["continue", "hold", "retessellate", "zeroback", "pending_observation"]


def build_state_feedback(
    *,
    timestamp_or_phase: str,
    active_frame: str,
    active_constraints: list[str],
    active_hazards: list[str],
    current_commitment: str,
    uncertainty_level: str,
    expected_time_window: str,
    expected_changes: list[str],
    expected_discriminators: list[str],
    expected_resolution_signs: list[str],
    failure_conditions: list[str],
    loop_status: LoopDecisionStatus,
    loop_rationale: str,
    next_observation_required: str,
    delta_reason: str,
    audit_events: list[str],
) -> dict[str, Any]:
    return {
        "current_state": {
            "timestamp_or_phase": timestamp_or_phase,
            "active_frame": active_frame,
            "active_constraints": active_constraints,
            "active_hazards": active_hazards,
            "current_commitment": current_commitment,
            "uncertainty_level": uncertainty_level,
        },
        "predicted_next_state": {
            "expected_time_window": expected_time_window,
            "expected_changes": expected_changes,
            "expected_discriminators": expected_discriminators,
            "expected_resolution_signs": expected_resolution_signs,
            "failure_conditions": failure_conditions,
        },
        "observed_next_state": {
            "status": "not_observed_in_mvp",
            "placeholder_reason": "The MVP packet declares the expected next-state check but does not run a live feedback loop.",
        },
        "delta_analysis": {
            "matches_prediction": "pending",
            "contradiction_delta": "pending",
            "confidence_delta": "pending",
            "reason": delta_reason,
        },
        "loop_decision": {
            "status": loop_status,
            "rationale": loop_rationale,
            "next_observation_required": next_observation_required,
        },
        "audit_events": audit_events,
    }


__all__ = [
    "LoopDecisionStatus",
    "build_state_feedback",
]
