from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional
from uuid import uuid4

from .governance import (
    DEFAULT_GOVERNANCE_POLICY_VERSION,
    DEFAULT_EVIDENCE_POLICY_VERSION,
    GovernanceCalibration,
    GovernanceCosts,
    GovernanceDecision,
    GovernanceMetrics,
    GovernanceThresholds,
)
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
    governance_thresholds: Optional[GovernanceThresholds] = None,
    governance_calibration: Optional[GovernanceCalibration] = None,
    governance_costs: Optional[GovernanceCosts] = None,
    direct_ruin_criterion_active: bool = False,
    user_decision: Optional[str] = None,
    override_reason: Optional[str] = None,
    carry_forward_policy: Optional[Dict[str, Any]] = None,
    why_not_converging: Optional[list[dict[str, str]]] = None,
    commit_requested: bool = False,
    evidence_id: Optional[str] = None,
    evidence_identity_mode: str = "independent_untracked",
    evidence_independence_attested: bool = False,
    evidence_fingerprint: Optional[str] = None,
    posterior_update_applied: bool = True,
    policy_version: str = DEFAULT_GOVERNANCE_POLICY_VERSION,
    evidence_policy_version: str = DEFAULT_EVIDENCE_POLICY_VERSION,
    calibration_version: Optional[str] = None,
    registry_version: Optional[str] = None,
) -> Dict[str, Any]:
    packet_id = str(uuid4())
    still_gate = build_still_gate(
        manifold_evaluation=manifold_evaluation,
        governor_decision=governor_decision,
        governance_metrics=governance_metrics,
        governance_decision=governance_decision,
        governance_thresholds=governance_thresholds,
        direct_ruin_criterion_active=direct_ruin_criterion_active,
        user_decision=user_decision,
        override_reason=override_reason,
    )
    packet: Dict[str, Any] = {
        "schema_id": "nepsis.iteration_packet",
        "schema_version": "0.2.0",
        "meta": {
            "packet_id": packet_id,
            "session_id": session_id,
            "parent_packet_id": parent_packet_id,
            "iteration": iteration,
            "created_at": _now_iso8601(),
            "policy_version": policy_version,
            "evidence_policy_version": evidence_policy_version,
            "calibration_version": calibration_version,
            "registry_version": registry_version,
        },
        "stage": stage,
        "stage_events": list(stage_events),
        "evidence_update": {
            "evidence_id": evidence_id,
            "identity_mode": evidence_identity_mode,
            "independence_attested": evidence_independence_attested,
            "content_hash": evidence_fingerprint,
            "posterior_update_applied": posterior_update_applied,
        },
        "frame_version": frame_version,
        "manifold": {
            "id": manifold_evaluation.manifold_id,
            "family": manifold_evaluation.family,
            "channel": manifold_evaluation.channel_semantics.to_dict(),
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
        "still": still_gate,
        "commit_request": {
            "requested": commit_requested,
            "admitted": commit_requested and "COMMIT" in stage_events,
            "blocked_by": (
                list(still_gate["finalization_blockers"])
                if commit_requested and "COMMIT" not in stage_events
                else []
            ),
        },
    }

    if governance_metrics is not None and governance_decision is not None:
        policy_inputs = {
            "costs": asdict(governance_costs) if governance_costs is not None else None,
            "calibration": (
                asdict(governance_calibration)
                if governance_calibration is not None
                else None
            ),
            "thresholds": (
                asdict(governance_thresholds)
                if governance_thresholds is not None
                else asdict(GovernanceThresholds())
            ),
        }
        policy_inputs_hash = "sha256:" + hashlib.sha256(
            json.dumps(policy_inputs, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        packet["governance"] = {
            "posture": governance_decision.posture,
            "warning_level": governance_decision.warning_level,
            "recommended_action": governance_decision.recommended_action,
            "red_veto_active": governance_decision.red_veto_active,
            "trigger_codes": list(governance_decision.trigger_codes),
            "user_decision": user_decision,
            "override_reason": override_reason,
            "theta": governance_decision.theta,
            "loss_treat": governance_decision.loss_treat,
            "loss_notreat": governance_decision.loss_notreat,
            "policy_inputs": policy_inputs,
            "policy_inputs_hash": policy_inputs_hash,
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
                "direct_ruin_criterion_active": governance_metrics.direct_ruin_criterion_active,
                "direct_ruin_criterion_observed": governance_metrics.direct_ruin_criterion_observed,
            },
            "red_authority": {
                "veto_active": governance_decision.red_veto_active,
                "applicability_boundary_met": any(
                    code in governance_decision.trigger_codes
                    for code in {
                        "DIRECT_RUIN_CRITERION_ACTIVE",
                        "RUIN_MASS_HIGH",
                    }
                ),
                "applicability_basis": [
                    code
                    for code in governance_decision.trigger_codes
                    if code
                    in {
                        "DIRECT_RUIN_CRITERION_ACTIVE",
                        "RUIN_MASS_HIGH",
                    }
                ],
                "cost_gate_crossed": "COST_GATE_CROSSED"
                in governance_decision.trigger_codes,
                "decision_scope": "unsafe_commitment",
                "epistemic_scope": "hazard_applicability_not_truth_selection",
                "posterior_hypothesis_weights_preserved": bool(posterior),
                "review_required": "RED_CAPTURE_REVIEW"
                in governance_decision.trigger_codes,
                "loss_if_protective_action_is_wrong": governance_decision.loss_treat,
                "loss_if_protective_action_is_omitted": governance_decision.loss_notreat,
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
    if action == "reset_priors":
        policy["priors"] = "reset"
    elif posture in {"zeroback", "red_review"}:
        policy["priors"] = "keep"
    elif posture == "collapse_mode" or action == "collapse":
        policy["priors"] = "keep"
        policy["constraints"]["soft"] = "keep"
    elif posture in {"red_override", "anti_stall"}:
        policy["priors"] = "decay"
        policy["constraints"]["soft"] = "relax"
    elif posture == "cost_review":
        policy["priors"] = "keep"
        policy["constraints"]["soft"] = "keep"

    return policy


def build_still_gate(
    *,
    manifold_evaluation: ManifoldEvaluation[Any],
    governor_decision: GovernorDecision,
    governance_metrics: Optional[GovernanceMetrics],
    governance_decision: Optional[GovernanceDecision],
    governance_thresholds: Optional[GovernanceThresholds] = None,
    direct_ruin_criterion_active: bool = False,
    user_decision: Optional[str] = None,
    override_reason: Optional[str] = None,
) -> Dict[str, Any]:
    blockers: list[str] = []
    required_exit_criteria: list[str] = []
    thresholds = governance_thresholds or GovernanceThresholds()

    channel_space = manifold_evaluation.channel_semantics.space
    error_count = sum(1 for v in manifold_evaluation.result.violations if getattr(v, "severity", None) == "error")
    warning_count = sum(1 for v in manifold_evaluation.result.violations if getattr(v, "severity", None) == "warning")

    if manifold_evaluation.is_ruin:
        blockers.append("ruin_node_active")
        required_exit_criteria.append("Resolve or explicitly escalate active ruin node.")
    if channel_space == "ruin":
        blockers.append("red_boundary_active")
        required_exit_criteria.append("Red boundary must be released by explicit re-evaluation or reframe.")
    if error_count > 0:
        blockers.append("constraint_contradiction")
        required_exit_criteria.append("Clear hard constraint violations or retessellate the hypothesis space.")
    if warning_count > 0:
        required_exit_criteria.append("Review warning-level evidence before commitment.")

    if direct_ruin_criterion_active and governance_decision is None:
        blockers.append("direct_ruin_criterion_active")
        required_exit_criteria.append(
            "Keep the RED veto until independent assessed-negative evidence resolves applicability; governed reframe may reopen assessment without silently clearing it."
        )

    if governance_metrics is not None:
        if governance_metrics.contradiction_density >= thresholds.c_high:
            blockers.append("contradiction_density_high")
            required_exit_criteria.append("Add a discriminator targeting the contradiction cluster.")
        if (
            governance_metrics.top_margin < thresholds.eps_margin
            and governance_metrics.posterior_entropy_norm > thresholds.h_high
        ):
            blockers.append("posterior_margin_collapse")
            required_exit_criteria.append("Hold plurality until posterior margin improves or denominator is rebuilt.")

    if governance_decision is not None:
        if governance_decision.red_veto_active:
            blockers.append("red_veto_active")
            required_exit_criteria.append(
                "Keep the RED veto until governed evidence narrows, contains, or resolves its applicability."
            )
        if "RED_CAPTURE_REVIEW" in governance_decision.trigger_codes:
            blockers.append("red_capture_review_required")
            required_exit_criteria.append(
                "Run ZeroBack or a safe RED discriminator without treating review as hazard release."
            )
        if governance_decision.posture in {
            "red_override",
            "red_review",
            "anti_stall",
            "zeroback",
        }:
            blockers.append(f"governance_{governance_decision.posture}")
            required_exit_criteria.append(f"Complete recommended governance action: {governance_decision.recommended_action}.")
        elif governance_decision.posture == "mixture_mode":
            blockers.append("mixture_mode")
            required_exit_criteria.append("Run abductive discriminator before collapse.")
        elif governance_decision.posture == "cost_review":
            cost_review_acknowledged = (
                user_decision == "continue_override"
                and bool((override_reason or "").strip())
            )
            if not cost_review_acknowledged:
                blockers.append("governance_cost_review")
                required_exit_criteria.append(
                    "Review or explicitly disposition the cost-derived protective action without treating it as a RED truth claim."
                )

    blockers = list(dict.fromkeys(blockers))
    required_exit_criteria = list(dict.fromkeys(required_exit_criteria))
    blocked = bool(blockers)

    return {
        "name": "STILL",
        "purpose": "Stability and termination interlock before final answer collapse.",
        "finalization_permitted": not blocked,
        "status": "blocked" if blocked else "clear",
        "finalization_blockers": blockers,
        "required_exit_criteria": required_exit_criteria,
        "next_allowed_move": _still_next_move(blockers, governance_decision),
        "rationale": "Do not finalize while live hazards, contradictions, denominator collapse, or wrong-manifold risk remain.",
    }


def _still_next_move(
    blockers: list[str],
    governance_decision: Optional[GovernanceDecision],
) -> str:
    if not blockers:
        return "finalize_with_audit"
    if "red_capture_review_required" in blockers:
        return "review_red_applicability"
    if any(
        blocker in blockers
        for blocker in {
            "red_veto_active",
            "red_boundary_active",
            "ruin_node_active",
            "direct_ruin_criterion_active",
        }
    ):
        if governance_decision is not None and governance_decision.recommended_action in {
            "contain_and_discriminate",
            "escalate_red",
            "review_red_applicability",
        }:
            return governance_decision.recommended_action
        return "escalate_or_reframe"
    if "posterior_margin_collapse" in blockers:
        return "retessellate"
    if "contradiction_density_high" in blockers or "constraint_contradiction" in blockers:
        return "request_discriminator"
    if governance_decision is not None and governance_decision.recommended_action:
        return governance_decision.recommended_action
    return "hold"


__all__ = [
    "build_iteration_packet",
    "build_still_gate",
]
