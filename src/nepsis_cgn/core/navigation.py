from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Mapping, Optional, TypeVar
from uuid import uuid4

from .convergence import explain_trigger_codes
from .constraints import CGNState
from .frame import FrameVersion, ObjectiveType, infer_frame_from_sign
from .governor import GovernorConfig, GovernorDecision, ManifoldGovernor
from .governance import (
    Event,
    GovernanceCalibration,
    GovernanceContext,
    GovernanceCosts,
    GovernanceDecision,
    GovernanceMetrics,
    GovernanceThresholds,
    IterationStateMachine,
    evaluate_governance_policy,
)
from .interpretant import InterpretantManager, ManifoldEvaluation
from .packet import build_iteration_packet

SignT = TypeVar("SignT")
StateT = TypeVar("StateT", bound=CGNState)


@dataclass
class NavigationTraceEntry(Generic[SignT, StateT]):
    sign: SignT
    manifold_evaluation: ManifoldEvaluation[StateT]
    governor_decision: GovernorDecision
    posterior: Dict[str, float]
    governance_decision: Optional[GovernanceDecision] = None
    governance_metrics: Optional[GovernanceMetrics] = None
    iteration_packet: Optional[Dict[str, Any]] = None
    trace_metadata: Dict[str, Any] = field(default_factory=dict)


class NavigationController(Generic[SignT, StateT]):
    """
    Thin supervisor wiring interpretant → manifold → governor.

    This is intentionally minimal; it keeps per-manifold governor state so
    tension history is preserved across steps.
    """

    def __init__(
        self,
        manager: InterpretantManager[SignT, StateT],
        *,
        governor_configs: Optional[Mapping[str, GovernorConfig]] = None,
        default_governor_config: Optional[GovernorConfig] = None,
        governance_costs: Optional[GovernanceCosts] = None,
        governance_calibration: Optional[GovernanceCalibration] = None,
        governance_thresholds: Optional[GovernanceThresholds] = None,
        emit_iteration_packet: bool = False,
        session_id: Optional[str] = None,
        frame: Optional[FrameVersion] = None,
        policy_version: str = "gov-v1.0.0",
        calibration_version: Optional[str] = None,
        registry_version: Optional[str] = None,
    ):
        self.manager = manager
        self._governor_configs = dict(governor_configs or {})
        self._default_config = default_governor_config or GovernorConfig()
        self._governors: Dict[str, ManifoldGovernor[StateT]] = {}
        self._governance_costs = governance_costs
        self._governance_calibration = governance_calibration or GovernanceCalibration()
        self._governance_thresholds = governance_thresholds or GovernanceThresholds()
        self._contradiction_streak = 0
        self._mixture_dwell_iters = 0
        self._stable_iters = 0
        self._zeroback_count = 0
        self._emit_iteration_packet = emit_iteration_packet
        self._session_id = session_id or str(uuid4())
        self._frame = frame
        self._policy_version = policy_version
        self._calibration_version = calibration_version or self._governance_calibration.version
        self._registry_version = registry_version
        self._iteration_index = 0
        self._last_packet_id: Optional[str] = None
        self._stage_machine = IterationStateMachine(stage="draft")
        self.trace: list[NavigationTraceEntry[SignT, StateT]] = []

    def _get_governor(self, manifold_id: str) -> ManifoldGovernor[StateT]:
        if manifold_id in self._governors:
            return self._governors[manifold_id]
        cfg = self._governor_configs.get(manifold_id, self._default_config)
        governor = ManifoldGovernor[StateT](config=cfg)
        self._governors[manifold_id] = governor
        return governor

    @property
    def current_stage(self) -> str:
        return self._stage_machine.stage

    @property
    def frame(self) -> Optional[FrameVersion]:
        return self._frame

    def reframe(
        self,
        *,
        text: Optional[str] = None,
        objective_type: Optional[ObjectiveType] = None,
        domain: Optional[str] = None,
        time_horizon: Optional[str] = None,
        rationale_for_change: Optional[str] = None,
        constraints_hard: Optional[list[str]] = None,
        constraints_soft: Optional[list[str]] = None,
    ) -> FrameVersion:
        if self._frame is None:
            raise ValueError("Cannot reframe before initial frame is established.")
        self._frame = self._frame.reframe(
            text=text,
            objective_type=objective_type,
            domain=domain,
            time_horizon=time_horizon,
            rationale_for_change=rationale_for_change,
            constraints_hard=constraints_hard,
            constraints_soft=constraints_soft,
        )
        return self._frame

    def step(
        self,
        sign: SignT,
        *,
        tension: Optional[float] = None,
        commit: bool = False,
        user_decision: Optional[str] = None,
        override_reason: Optional[str] = None,
        carry_forward_policy: Optional[Dict[str, Any]] = None,
    ) -> NavigationTraceEntry[SignT, StateT]:
        self._validate_user_decision(user_decision=user_decision, override_reason=override_reason)
        if user_decision == "stop":
            commit = False

        stage_events = self._prepare_stage_events(commit=commit)

        # Interpretant selects manifold (updates posterior internally).
        manifold = self.manager.select_manifold(sign)
        posterior = self.manager.posterior()

        # Evaluate manifold.
        evaluation = manifold.run(sign)

        # Governor decision using per-manifold state.
        governor = self._get_governor(evaluation.manifold_id)
        decision = governor.evaluate(evaluation, tension=tension)

        governance_metrics: Optional[GovernanceMetrics] = None
        governance_decision: Optional[GovernanceDecision] = None
        why_not_converging: list[dict[str, str]] = []
        if self._governance_costs is not None:
            governance_metrics = self._derive_governance_metrics(evaluation=evaluation, posterior=posterior)
            context = self._derive_governance_context(governance_metrics)
            governance_decision = evaluate_governance_policy(
                governance_metrics,
                self._governance_costs,
                context=context,
                thresholds=self._governance_thresholds,
            )
            self._update_governance_history(governance_metrics, governance_decision)
            why_not_converging = [r.to_dict() for r in explain_trigger_codes(governance_decision.trigger_codes)]

        if self._frame is None:
            self._frame = infer_frame_from_sign(sign, family=evaluation.family, costs=self._governance_costs)

        self._apply_stage_events(stage_events)

        iteration_packet: Optional[Dict[str, Any]] = None
        if self._emit_iteration_packet:
            assert self._frame is not None
            iteration_packet = build_iteration_packet(
                session_id=self._session_id,
                iteration=self._iteration_index,
                parent_packet_id=self._last_packet_id,
                stage=self._stage_machine.stage,
                stage_events=stage_events,
                frame_version=self._frame.to_dict(),
                manifold_evaluation=evaluation,
                governor_decision=decision,
                posterior=posterior,
                governance_metrics=governance_metrics,
                governance_decision=governance_decision,
                user_decision=user_decision,
                override_reason=override_reason,
                carry_forward_policy=carry_forward_policy,
                why_not_converging=why_not_converging,
                policy_version=self._policy_version,
                calibration_version=self._calibration_version,
                registry_version=self._registry_version,
            )
            self._last_packet_id = str(iteration_packet["meta"]["packet_id"])
            self._iteration_index += 1

        trace_entry = NavigationTraceEntry(
            sign=sign,
            manifold_evaluation=evaluation,
            governor_decision=decision,
            posterior=posterior,
            governance_decision=governance_decision,
            governance_metrics=governance_metrics,
            iteration_packet=iteration_packet,
            trace_metadata={
                "manifold_id": evaluation.manifold_id,
                "family": evaluation.family,
                "decision": decision.decision,
                "cause": decision.cause,
                "tension": decision.metrics.tension,
                "velocity": decision.metrics.velocity,
                "accel": decision.metrics.accel,
                "governance_posture": governance_decision.posture if governance_decision else None,
                "warning_level": governance_decision.warning_level if governance_decision else None,
                "trigger_codes": list(governance_decision.trigger_codes) if governance_decision else [],
                "why_not_converging": why_not_converging,
                "user_decision": user_decision,
                "override_reason": override_reason,
                "stage": self._stage_machine.stage,
                "stage_events": list(stage_events),
                "frame_id": self._frame.frame_id if self._frame else None,
                "frame_version": self._frame.frame_version if self._frame else None,
                "packet_id": iteration_packet["meta"]["packet_id"] if iteration_packet else None,
                "iteration": iteration_packet["meta"]["iteration"] if iteration_packet else None,
            },
        )
        self.trace.append(trace_entry)
        return trace_entry

    def _derive_governance_metrics(
        self,
        *,
        evaluation: ManifoldEvaluation[StateT],
        posterior: Dict[str, float],
    ) -> GovernanceMetrics:
        sorted_weights = sorted((float(v) for v in posterior.values()), reverse=True)
        top_p = sorted_weights[0] if sorted_weights else 0.0
        second_p = sorted_weights[1] if len(sorted_weights) > 1 else 0.0
        top_margin = max(top_p - second_p, 0.0)

        entropy_norm = self._normalized_entropy(sorted_weights)

        error_count = sum(1 for v in evaluation.result.violations if v.severity == "error")
        warning_count = sum(1 for v in evaluation.result.violations if v.severity == "warning")
        info_count = sum(1 for v in evaluation.result.violations if v.severity == "info")
        constraint_count = int(evaluation.metadata.get("constraint_count", 0)) or max(
            len(evaluation.result.violations), 1
        )

        contradiction_density = min(max(error_count / float(constraint_count), 0.0), 1.0)
        violation_pressure = (error_count + (0.5 * warning_count) + (0.2 * info_count)) / float(constraint_count)
        ambiguity_pressure = (1.0 - top_margin) * entropy_norm
        p_bad = self._governance_calibration.probability(
            violation_pressure=min(max(violation_pressure, 0.0), 1.0),
            ambiguity_pressure=min(max(ambiguity_pressure, 0.0), 1.0),
            contradiction_density=contradiction_density,
            posterior_entropy_norm=entropy_norm,
            top_margin=top_margin,
        )
        if evaluation.is_ruin:
            p_bad = 1.0

        ruin_mass = self.manager.ruin_mass(posterior)
        if ruin_mass == 0.0 and evaluation.is_ruin:
            ruin_mass = min(max(float(posterior.get(evaluation.manifold_id, 0.0)), 0.0), 1.0)

        return GovernanceMetrics(
            p_bad=p_bad,
            ruin_mass=ruin_mass,
            contradiction_density=contradiction_density,
            posterior_entropy_norm=entropy_norm,
            top_margin=top_margin,
            top_p=top_p,
            aux_assumption_load=None,
            zeroback_count=self._zeroback_count,
            filter_ess=None,
            hotspot_score=None,
        )

    def _derive_governance_context(self, metrics: GovernanceMetrics) -> GovernanceContext:
        th = self._governance_thresholds
        contradiction_streak = self._contradiction_streak + 1 if metrics.contradiction_density > th.c_high else 0
        is_stable = (
            metrics.top_p is not None
            and metrics.top_p >= th.tau_collapse
            and metrics.top_margin >= th.eps_collapse
            and metrics.contradiction_density <= th.c_ok
        )
        stable_iters = self._stable_iters + 1 if is_stable else 0
        return GovernanceContext(
            contradiction_streak=contradiction_streak,
            mixture_dwell_iters=self._mixture_dwell_iters,
            stable_iters=stable_iters,
        )

    def _update_governance_history(
        self,
        metrics: GovernanceMetrics,
        decision: GovernanceDecision,
    ) -> None:
        th = self._governance_thresholds
        self._contradiction_streak = self._contradiction_streak + 1 if metrics.contradiction_density > th.c_high else 0

        is_stable = (
            metrics.top_p is not None
            and metrics.top_p >= th.tau_collapse
            and metrics.top_margin >= th.eps_collapse
            and metrics.contradiction_density <= th.c_ok
        )
        self._stable_iters = self._stable_iters + 1 if is_stable else 0

        if decision.posture in {"mixture_mode", "anti_stall"}:
            self._mixture_dwell_iters += 1
        else:
            self._mixture_dwell_iters = 0

        if decision.posture == "zeroback":
            self._zeroback_count += 1

    @staticmethod
    def _normalized_entropy(weights: list[float]) -> float:
        filtered = [w for w in weights if w > 0.0]
        k = len(filtered)
        if k <= 1:
            return 0.0
        entropy = -sum(w * math.log(w) for w in filtered)
        return min(max(entropy / math.log(k), 0.0), 1.0)

    def _prepare_stage_events(self, *, commit: bool) -> list[str]:
        events: list[str] = []
        if not self._stage_machine.can_apply("CALL"):
            if self._stage_machine.can_apply("ITERATE"):
                events.append("ITERATE")
            else:
                raise ValueError(f"Cannot transition to CALL from stage {self._stage_machine.stage}.")
        events.extend(["CALL", "REPORT", "EVALUATE"])
        if commit:
            events.append("COMMIT")
        return events

    def _apply_stage_events(self, events: list[str]) -> None:
        for raw_event in events:
            event: Event = raw_event  # type: ignore[assignment]
            self._stage_machine.apply(event)

    def _validate_user_decision(
        self,
        *,
        user_decision: Optional[str],
        override_reason: Optional[str],
    ) -> None:
        if user_decision is None and override_reason is None:
            return
        if self._governance_costs is None:
            raise ValueError("User governance decision requires governance to be enabled (set costs).")
        valid = {None, "stop", "continue_override"}
        if user_decision not in valid:
            raise ValueError("user_decision must be one of: stop, continue_override, or None.")
        if override_reason and user_decision != "continue_override":
            raise ValueError("override_reason is only valid when user_decision is continue_override.")
        if user_decision == "continue_override" and not override_reason:
            raise ValueError("override_reason is required when user_decision is continue_override.")


__all__ = [
    "NavigationController",
    "NavigationTraceEntry",
]
