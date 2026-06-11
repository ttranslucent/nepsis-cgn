from __future__ import annotations

from typing import Any, Literal

StillReadiness = Literal["ready", "hold", "retessellate", "zeroback"]


def build_still_pathway(
    *,
    checkpoint_1_trigger_status: str,
    checkpoint_1_reason: str,
    checkpoint_1_required_before_commitment: list[str],
    checkpoint_2_reason: str,
    checkpoint_2_required_before_commitment: list[str],
    red_escalation_required: bool,
    contradiction_present: bool,
    denominator_collapse_detected: bool,
    non_quiescence_possible: bool,
    zeroback_triggered: bool,
    learning_notes: list[str],
) -> dict[str, Any]:
    readiness = _commitment_readiness(
        contradiction_present=contradiction_present,
        denominator_collapse_detected=denominator_collapse_detected,
        non_quiescence_possible=non_quiescence_possible,
        zeroback_triggered=zeroback_triggered,
    )
    return {
        "name": "STILL",
        "definition": "Strategic Time-in-Loop for Learning",
        "checkpoints": [
            {
                "name": "STILL Checkpoint 1",
                "position": "after_red_before_blue",
                "trigger_status": checkpoint_1_trigger_status,
                "reason": checkpoint_1_reason,
                "required_before_commitment": checkpoint_1_required_before_commitment,
            },
            {
                "name": "STILL Checkpoint 2",
                "position": "after_blue_before_commitment",
                "trigger_status": readiness,
                "reason": checkpoint_2_reason,
                "required_before_commitment": checkpoint_2_required_before_commitment,
            },
        ],
        "commitment_readiness": {
            "status": readiness,
            "zeroback_triggered": zeroback_triggered,
            "effective_action": _effective_action(
                readiness,
                zeroback_triggered=zeroback_triggered,
            ),
            "co_trigger_statuses": _co_trigger_statuses(
                readiness=readiness,
                contradiction_present=contradiction_present,
                denominator_collapse_detected=denominator_collapse_detected,
                non_quiescence_possible=non_quiescence_possible,
                zeroback_triggered=zeroback_triggered,
            ),
            "rationale": _readiness_rationale(
                readiness,
                red_escalation_required=red_escalation_required,
                contradiction_present=contradiction_present,
                denominator_collapse_detected=denominator_collapse_detected,
                non_quiescence_possible=non_quiescence_possible,
            ),
        },
        "learning_notes": learning_notes,
        "audit_events": [
            {
                "order": 1,
                "stage": "still_checkpoint_1",
                "summary": "Checked permission to enter BLUE without clearing RED.",
            },
            {
                "order": 2,
                "stage": "still_checkpoint_2",
                "summary": f"Set commitment readiness to {readiness}.",
            },
        ],
    }


def _commitment_readiness(
    *,
    contradiction_present: bool,
    denominator_collapse_detected: bool,
    non_quiescence_possible: bool,
    zeroback_triggered: bool,
) -> StillReadiness:
    if denominator_collapse_detected or contradiction_present:
        return "retessellate"
    if zeroback_triggered:
        return "zeroback"
    if non_quiescence_possible:
        return "hold"
    return "ready"


def _readiness_rationale(
    readiness: StillReadiness,
    *,
    red_escalation_required: bool,
    contradiction_present: bool,
    denominator_collapse_detected: bool,
    non_quiescence_possible: bool,
) -> str:
    if readiness == "retessellate":
        if denominator_collapse_detected:
            return "Hypothesis space is undercomplete; rebuild before commitment."
        return "Contradiction remains live; commitment is not justified."
    if readiness == "zeroback":
        return "Recursive instability requires reset with audit trail."
    if readiness == "hold":
        return "Wrong-manifold risk remains; request discriminator before commitment."
    if red_escalation_required:
        return "Ready only after RED escalation remains preserved."
    return "No live STILL blockers remain."


def _effective_action(
    readiness: StillReadiness,
    *,
    zeroback_triggered: bool,
) -> StillReadiness:
    if zeroback_triggered:
        return "zeroback"
    return readiness


def _co_trigger_statuses(
    *,
    readiness: StillReadiness,
    contradiction_present: bool,
    denominator_collapse_detected: bool,
    non_quiescence_possible: bool,
    zeroback_triggered: bool,
) -> list[StillReadiness]:
    statuses: list[StillReadiness] = []
    if contradiction_present or denominator_collapse_detected:
        statuses.append("retessellate")
    if zeroback_triggered:
        statuses.append("zeroback")
    if non_quiescence_possible:
        statuses.append("hold")
    if not statuses:
        statuses.append("ready")
    if readiness not in statuses:
        statuses.insert(0, readiness)
    return statuses


__all__ = [
    "StillReadiness",
    "build_still_pathway",
]
