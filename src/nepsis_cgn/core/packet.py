from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from .governance import GovernanceDecision, GovernanceMetrics
from .governor import GovernorDecision
from .interpretant import ManifoldEvaluation


def _now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _serialize_violations(violations: Iterable[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for violation in violations:
        items.append(
            {
                "code": getattr(violation, "code", "generic"),
                "severity": getattr(violation, "severity", "error"),
                "message": getattr(violation, "message", ""),
                "metadata": getattr(violation, "metadata", None),
            }
        )
    return items


def build_iteration_packet(
    *,
    session_id: str,
    iteration: int,
    parent_packet_id: Optional[str],
    stage: str,
    stage_events: list[str],
    frame_version: Dict[str, Any],
    manifold_evaluation: ManifoldEvaluation[Any],
    governor_decision: GovernorDecision,
    posterior: Dict[str, float],
    governance_metrics: Optional[GovernanceMetrics] = None,
    governance_decision: Optional[GovernanceDecision] = None,
    user_decision: Optional[str] = None,
    override_reason: Optional[str] = None,
    carry_forward_policy: Optional[Dict[str, Any]] = None,
    why_not_converging: Optional[list[dict[str, str]]] = None,
    policy_version: str = "gov-v1.0.0",
    calibration_version: Optional[str] = None,
    registry_version: Optional[str] = None,
) -> Dict[str, Any]:
    packet_id = str(uuid4())
    packet: Dict[str, Any] = {
        "schema_id": "nepsis.iteration_packet",
        "schema_version": "0.1.0",
        "meta": {
            "packet_id": packet_id,
            "session_id": session_id,
            "parent_packet_id": parent_packet_id,
            "iteration": iteration,
            "created_at": _now_iso8601(),
            "policy_version": policy_version,
            "calibration_version": calibration_version,
            "registry_version": registry_version,
        },
        "stage": stage,
        "stage_events": list(stage_events),
        "frame_version": frame_version,
        "manifold": {
            "id": manifold_evaluation.manifold_id,
            "family": manifold_evaluation.family,
        },
        "result": {
            "decision": governor_decision.decision,
            "cause": governor_decision.cause,
            "tension": governor_decision.metrics.tension,
            "velocity": governor_decision.metrics.velocity,
            "accel": governor_decision.metrics.accel,
            "is_ruin": manifold_evaluation.is_ruin,
            "ruin_hits": list(manifold_evaluation.ruin_hits),
            "active_transforms": list(manifold_evaluation.active_transforms),
            "violation_count": len(manifold_evaluation.result.violations),
            "violations": _serialize_violations(manifold_evaluation.result.violations),
        },
        "posterior": {k: float(v) for k, v in posterior.items()},
        "carry_forward": carry_forward_policy
        if carry_forward_policy is not None
        else _default_carry_forward_policy(governance_decision),
        "state": {
            "description": manifold_evaluation.result.state_description,
            "constraint_set": manifold_evaluation.result.metadata.get("constraint_set"),
        },
    }

    if governance_metrics is not None and governance_decision is not None:
        packet["governance"] = {
            "posture": governance_decision.posture,
            "warning_level": governance_decision.warning_level,
            "recommended_action": governance_decision.recommended_action,
            "trigger_codes": list(governance_decision.trigger_codes),
            "user_decision": user_decision,
            "override_reason": override_reason,
            "theta": governance_decision.theta,
            "loss_treat": governance_decision.loss_treat,
            "loss_notreat": governance_decision.loss_notreat,
            "metrics": {
                "p_bad": governance_metrics.p_bad,
                "ruin_mass": governance_metrics.ruin_mass,
                "contradiction_density": governance_metrics.contradiction_density,
                "posterior_entropy_norm": governance_metrics.posterior_entropy_norm,
                "top_margin": governance_metrics.top_margin,
                "top_p": governance_metrics.top_p,
                "zeroback_count": governance_metrics.zeroback_count,
                "filter_ess": governance_metrics.filter_ess,
                "hotspot_score": governance_metrics.hotspot_score,
                "aux_assumption_load": governance_metrics.aux_assumption_load,
            },
        }
        if why_not_converging:
            packet["governance"]["why_not_converging"] = list(why_not_converging)

    return packet


def _default_carry_forward_policy(governance_decision: Optional[GovernanceDecision]) -> Dict[str, Any]:
    policy: Dict[str, Any] = {
        "facts": "keep",
        "contradictions": "keep",
        "priors": "decay",
        "constraints": {"hard": "keep", "soft": "relax"},
        "tests": "keep",
    }
    if governance_decision is None:
        return policy

    action = governance_decision.recommended_action
    posture = governance_decision.posture
    if posture == "zeroback" or action == "reset_priors":
        policy["priors"] = "reset"
    elif posture == "collapse_mode" or action == "collapse":
        policy["priors"] = "keep"
        policy["constraints"]["soft"] = "keep"
    elif posture in {"red_override", "anti_stall"}:
        policy["priors"] = "decay"
        policy["constraints"]["soft"] = "relax"

    return policy


__all__ = [
    "build_iteration_packet",
]
