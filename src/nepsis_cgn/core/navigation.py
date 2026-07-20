from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Dict, Generic, Mapping, Optional, TypeVar
from uuid import uuid4

from .convergence import explain_trigger_codes
from .constraints import CGNState
from .frame import FrameVersion, ObjectiveType, infer_frame_from_sign
from .governor import GovernorConfig, GovernorDecision, ManifoldGovernor
from .governance import (
    DEFAULT_GOVERNANCE_POLICY_VERSION,
    DEFAULT_EVIDENCE_POLICY_VERSION,
    Event,
    GovernanceCalibration,
    GovernanceContext,
    GovernanceCosts,
    GovernanceDecision,
    GovernanceMetrics,
    GovernanceThresholds,
    IterationStateMachine,
    evaluate_governance_policy,
    threshold_met,
)
from .interpretant import InterpretantManager, ManifoldEvaluation
from .packet import build_iteration_packet, build_still_gate

SignT = TypeVar("SignT")
StateT = TypeVar("StateT", bound=CGNState)

_RED_EVIDENCE_CHECKPOINT_SCHEMA_ID = "nepsis.navigation_red_evidence_checkpoint"
_RED_EVIDENCE_CHECKPOINT_SCHEMA_VERSION = "0.1.0"


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
        policy_version: str = DEFAULT_GOVERNANCE_POLICY_VERSION,
        evidence_policy_version: str = DEFAULT_EVIDENCE_POLICY_VERSION,
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
        self._red_override_dwell_iters = 0
        self._red_capture_review_active = False
        self._last_red_review_fingerprint: Optional[str] = None
        self._seen_red_review_fingerprints: set[str] = set()
        self._evidence_content_by_id: Dict[str, str] = {}
        self._seen_evidence_content_hashes: set[str] = set()
        self._direct_ruin_criterion_latched = False
        self._stable_iters = 0
        self._zeroback_count = 0
        self._emit_iteration_packet = emit_iteration_packet
        self._session_id = session_id or str(uuid4())
        self._frame = frame
        self._policy_version = policy_version
        self._evidence_policy_version = evidence_policy_version
        if self._evidence_policy_version not in {"evidence-v1", "evidence-v2"}:
            raise ValueError("Unsupported evidence policy version.")
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

    @property
    def policy_version(self) -> str:
        return self._policy_version

    @property
    def evidence_policy_version(self) -> str:
        return self._evidence_policy_version

    @property
    def registry_version(self) -> Optional[str]:
        return self._registry_version

    @property
    def direct_ruin_criterion_active(self) -> bool:
        return self._direct_ruin_criterion_latched

    def export_red_evidence_checkpoint(self) -> Dict[str, Any]:
        return {
            "schema_id": _RED_EVIDENCE_CHECKPOINT_SCHEMA_ID,
            "schema_version": _RED_EVIDENCE_CHECKPOINT_SCHEMA_VERSION,
            "policy_version": self._policy_version,
            "evidence_policy_version": self._evidence_policy_version,
            "registry_version": self._registry_version,
            "posterior": self.manager.posterior(),
            "evidence": {
                "content_by_id": dict(self._evidence_content_by_id),
                "seen_content_hashes": sorted(self._seen_evidence_content_hashes),
            },
            "red_state": {
                "direct_ruin_criterion_latched": self._direct_ruin_criterion_latched,
                "red_override_dwell_iters": self._red_override_dwell_iters,
                "red_capture_review_active": self._red_capture_review_active,
                "last_red_review_fingerprint": self._last_red_review_fingerprint,
                "seen_red_review_fingerprints": sorted(
                    self._seen_red_review_fingerprints
                ),
            },
            "recurrence_state": {
                "contradiction_streak": self._contradiction_streak,
                "mixture_dwell_iters": self._mixture_dwell_iters,
                "stable_iters": self._stable_iters,
                "zeroback_count": self._zeroback_count,
            },
        }

    def import_red_evidence_checkpoint(self, checkpoint: Mapping[str, Any]) -> None:
        if checkpoint.get("schema_id") != _RED_EVIDENCE_CHECKPOINT_SCHEMA_ID:
            raise ValueError("Unsupported navigation checkpoint schema_id.")
        if (
            checkpoint.get("schema_version")
            != _RED_EVIDENCE_CHECKPOINT_SCHEMA_VERSION
        ):
            raise ValueError("Unsupported navigation checkpoint schema_version.")
        for key, expected in (
            ("policy_version", self._policy_version),
            ("evidence_policy_version", self._evidence_policy_version),
            ("registry_version", self._registry_version),
        ):
            if checkpoint.get(key) != expected:
                raise ValueError(f"Navigation checkpoint {key} does not match runtime.")

        posterior = checkpoint.get("posterior")
        evidence = checkpoint.get("evidence")
        red_state = checkpoint.get("red_state")
        recurrence_state = checkpoint.get("recurrence_state")
        if not isinstance(posterior, Mapping):
            raise ValueError("Navigation checkpoint posterior must be an object.")
        if not isinstance(evidence, Mapping):
            raise ValueError("Navigation checkpoint evidence must be an object.")
        if not isinstance(red_state, Mapping):
            raise ValueError("Navigation checkpoint red_state must be an object.")
        if not isinstance(recurrence_state, Mapping):
            raise ValueError(
                "Navigation checkpoint recurrence_state must be an object."
            )
        self.manager.restore_posterior(posterior)

        content_by_id = evidence.get("content_by_id")
        seen_content_hashes = evidence.get("seen_content_hashes")
        seen_red_fingerprints = red_state.get("seen_red_review_fingerprints")
        if not isinstance(content_by_id, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in content_by_id.items()
        ):
            raise ValueError(
                "Navigation checkpoint evidence content_by_id is invalid."
            )
        if not _is_string_list(seen_content_hashes):
            raise ValueError(
                "Navigation checkpoint seen_content_hashes must be strings."
            )
        if not _is_string_list(seen_red_fingerprints):
            raise ValueError(
                "Navigation checkpoint seen_red_review_fingerprints must be strings."
            )

        direct_latched = _checkpoint_bool(
            red_state, "direct_ruin_criterion_latched"
        )
        capture_active = _checkpoint_bool(red_state, "red_capture_review_active")
        last_fingerprint = red_state.get("last_red_review_fingerprint")
        if last_fingerprint is not None and not isinstance(last_fingerprint, str):
            raise ValueError(
                "Navigation checkpoint last_red_review_fingerprint is invalid."
            )

        self._evidence_content_by_id = dict(content_by_id)
        self._seen_evidence_content_hashes = set(seen_content_hashes)
        self._direct_ruin_criterion_latched = direct_latched
        self._red_override_dwell_iters = _checkpoint_nonnegative_int(
            red_state, "red_override_dwell_iters"
        )
        self._red_capture_review_active = capture_active
        self._last_red_review_fingerprint = last_fingerprint
        self._seen_red_review_fingerprints = set(seen_red_fingerprints)
        self._contradiction_streak = _checkpoint_nonnegative_int(
            recurrence_state, "contradiction_streak"
        )
        self._mixture_dwell_iters = _checkpoint_nonnegative_int(
            recurrence_state, "mixture_dwell_iters"
        )
        self._stable_iters = _checkpoint_nonnegative_int(
            recurrence_state, "stable_iters"
        )
        self._zeroback_count = _checkpoint_nonnegative_int(
            recurrence_state, "zeroback_count"
        )

    def restore_packet_lineage(
        self,
        *,
        last_packet_id: Optional[str],
        next_iteration: int,
    ) -> None:
        if last_packet_id is not None and not str(last_packet_id).strip():
            raise ValueError("last_packet_id must be non-empty when provided.")
        if next_iteration < 0:
            raise ValueError("next_iteration must be non-negative.")
        self._last_packet_id = last_packet_id
        self._iteration_index = next_iteration

    def apply_frame_transition(
        self,
        *,
        prior_frame: Optional[FrameVersion],
        rationale_for_change: Optional[str],
    ) -> bool:
        """Apply RED review transition semantics to an externally rebuilt frame.

        Operator loops rebuild the controller around a serialized frame instead
        of calling :meth:`reframe`.  This keeps that boundary semantically
        equivalent: a substantive, explained reframe releases capture-review
        dwell, while the independently evidenced direct-hazard latch remains.
        """
        if prior_frame is None or self._frame is None:
            return False
        substantive_change = any(
            (
                self._frame.text != prior_frame.text,
                self._frame.objective_type != prior_frame.objective_type,
                self._frame.domain != prior_frame.domain,
                self._frame.time_horizon != prior_frame.time_horizon,
                self._frame.constraints_hard != prior_frame.constraints_hard,
                self._frame.constraints_soft != prior_frame.constraints_soft,
            )
        )
        if not substantive_change:
            return False
        governed_red_reframe = (
            self._red_capture_review_active
            or self._direct_ruin_criterion_latched
        )
        if governed_red_reframe and not (rationale_for_change or "").strip():
            raise ValueError("RED review requires an explicit rationale for reframe.")
        if governed_red_reframe:
            self._red_override_dwell_iters = 0
            self._red_capture_review_active = False
            self._last_red_review_fingerprint = None
            self._seen_red_review_fingerprints.clear()
        return True

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
        governed_red_reframe = (
            self._red_capture_review_active
            or self._direct_ruin_criterion_latched
        )
        if governed_red_reframe and not (rationale_for_change or "").strip():
            raise ValueError("RED review requires an explicit rationale for reframe.")
        if governed_red_reframe:
            substantive_change = any(
                (
                    text is not None and text != self._frame.text,
                    objective_type is not None and objective_type != self._frame.objective_type,
                    domain is not None and domain != self._frame.domain,
                    time_horizon is not None and time_horizon != self._frame.time_horizon,
                    constraints_hard is not None
                    and tuple(constraints_hard) != self._frame.constraints_hard,
                    constraints_soft is not None
                    and tuple(constraints_soft) != self._frame.constraints_soft,
                )
            )
            if not substantive_change:
                raise ValueError("RED review requires a substantive frame change.")
        self._frame = self._frame.reframe(
            text=text,
            objective_type=objective_type,
            domain=domain,
            time_horizon=time_horizon,
            rationale_for_change=rationale_for_change,
            constraints_hard=constraints_hard,
            constraints_soft=constraints_soft,
        )
        self._red_override_dwell_iters = 0
        self._red_capture_review_active = False
        self._last_red_review_fingerprint = None
        self._seen_red_review_fingerprints.clear()
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

        evidence_id = self._optional_evidence_id(sign)
        evidence_fingerprint = self._fingerprint_payload(
            sign,
            excluded_keys={"evidence_id", "independent_observation"},
        )
        independence_attested = bool(
            getattr(sign, "independent_observation", False)
        )
        if independence_attested and evidence_id is None:
            raise ValueError(
                "independent_observation requires an explicit evidence_id."
            )
        if self._evidence_policy_version == "evidence-v1":
            evidence_identity_mode = "legacy_sequential"
        else:
            evidence_identity_mode = (
                "explicit_independent"
                if independence_attested
                else "explicit"
                if evidence_id is not None
                else "anonymous_content_dedup"
            )
        posterior_update_applied = True
        prior_content = (
            self._evidence_content_by_id.get(evidence_id)
            if evidence_id is not None
            else None
        )
        if prior_content is not None and prior_content != evidence_fingerprint:
            raise ValueError("evidence_id cannot be reused with different content.")
        replayed_id = prior_content is not None
        if self._evidence_policy_version == "evidence-v2":
            repeated_content = (
                evidence_fingerprint in self._seen_evidence_content_hashes
            )
            posterior_update_applied = not replayed_id and (
                not repeated_content or independence_attested
            )
            if evidence_id is not None:
                self._evidence_content_by_id[evidence_id] = evidence_fingerprint
            self._seen_evidence_content_hashes.add(evidence_fingerprint)
        review_fingerprint = self._fingerprint_payload(
            self._red_applicability_fingerprint_payload(sign)
        )
        materially_new_red_evidence = (
            independence_attested and posterior_update_applied
        )

        # Interpretant selects manifold (updates posterior internally).
        manifold = self.manager.select_manifold(
            sign,
            update_posterior=posterior_update_applied,
        )
        posterior = self.manager.posterior()

        # Evaluate manifold.
        evaluation = manifold.run(sign)
        release_evidence_qualified = (
            evidence_id is not None
            and independence_attested
            and posterior_update_applied
            and self._red_release_assessed_negative(sign)
        )
        direct_ruin_criterion_observed = self._update_direct_ruin_criterion_latch(
            sign=sign,
            evaluation=evaluation,
            release_evidence_qualified=release_evidence_qualified,
        )

        # Governor decision using per-manifold state.
        governor = self._get_governor(evaluation.manifold_id)
        decision = governor.evaluate(evaluation, tension=tension)

        governance_metrics: Optional[GovernanceMetrics] = None
        governance_decision: Optional[GovernanceDecision] = None
        why_not_converging: list[dict[str, str]] = []
        if self._governance_costs is not None:
            governance_metrics = self._derive_governance_metrics(
                evaluation=evaluation,
                posterior=posterior,
                direct_ruin_criterion_observed=direct_ruin_criterion_observed,
            )
            context = self._derive_governance_context(
                governance_metrics,
                review_fingerprint=review_fingerprint,
                materially_new_red_evidence=materially_new_red_evidence,
            )
            governance_decision = evaluate_governance_policy(
                governance_metrics,
                self._governance_costs,
                context=context,
                thresholds=self._governance_thresholds,
            )
            self._update_governance_history(
                governance_metrics,
                governance_decision,
                context=context,
                review_fingerprint=review_fingerprint,
            )
            why_not_converging = [r.to_dict() for r in explain_trigger_codes(governance_decision.trigger_codes)]

        if self._frame is None:
            self._frame = infer_frame_from_sign(sign, family=evaluation.family, costs=self._governance_costs)

        if commit:
            still_gate = build_still_gate(
                manifold_evaluation=evaluation,
                governor_decision=decision,
                governance_metrics=governance_metrics,
                governance_decision=governance_decision,
                governance_thresholds=self._governance_thresholds,
                direct_ruin_criterion_active=self._direct_ruin_criterion_latched,
                user_decision=user_decision,
                override_reason=override_reason,
            )
            if not still_gate["finalization_permitted"]:
                stage_events = [event for event in stage_events if event != "COMMIT"]

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
                governance_thresholds=self._governance_thresholds,
                governance_calibration=self._governance_calibration,
                governance_costs=self._governance_costs,
                direct_ruin_criterion_active=self._direct_ruin_criterion_latched,
                user_decision=user_decision,
                override_reason=override_reason,
                carry_forward_policy=carry_forward_policy,
                why_not_converging=why_not_converging,
                commit_requested=commit,
                evidence_id=evidence_id,
                evidence_identity_mode=evidence_identity_mode,
                evidence_independence_attested=independence_attested,
                evidence_fingerprint=evidence_fingerprint,
                posterior_update_applied=posterior_update_applied,
                policy_version=self._policy_version,
                evidence_policy_version=self._evidence_policy_version,
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
                "channel_space": evaluation.channel_semantics.space,
                "channel_mode": evaluation.channel_semantics.decision_mode,
                "decision": decision.decision,
                "cause": decision.cause,
                "tension": decision.metrics.tension,
                "velocity": decision.metrics.velocity,
                "accel": decision.metrics.accel,
                "governance_posture": governance_decision.posture if governance_decision else None,
                "red_veto_active": (
                    governance_decision.red_veto_active
                    if governance_decision
                    else self._direct_ruin_criterion_latched
                ),
                "direct_ruin_criterion_active": self._direct_ruin_criterion_latched,
                "warning_level": governance_decision.warning_level if governance_decision else None,
                "trigger_codes": list(governance_decision.trigger_codes) if governance_decision else [],
                "why_not_converging": why_not_converging,
                "user_decision": user_decision,
                "override_reason": override_reason,
                "stage": self._stage_machine.stage,
                "stage_events": list(stage_events),
                "commit_requested": commit,
                "commit_admitted": "COMMIT" in stage_events,
                "evidence_fingerprint": evidence_fingerprint,
                "evidence_id": evidence_id,
                "evidence_identity_mode": evidence_identity_mode,
                "evidence_independence_attested": independence_attested,
                "posterior_update_applied": posterior_update_applied,
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
        direct_ruin_criterion_observed: bool,
    ) -> GovernanceMetrics:
        sorted_weights = sorted((float(v) for v in posterior.values()), reverse=True)
        top_p = sorted_weights[0] if sorted_weights else 0.0
        second_p = sorted_weights[1] if len(sorted_weights) > 1 else 0.0
        top_margin = max(top_p - second_p, 0.0)

        entropy_norm = self._normalized_entropy(sorted_weights)

        error_count = sum(1 for v in evaluation.result.violations if v.severity == "error")
        adverse_violations = [
            violation
            for violation in evaluation.result.violations
            if (violation.metadata or {}).get("governance_role")
            not in {"informational_context", "manifold_mismatch"}
        ]
        adverse_error_count = sum(
            1 for violation in adverse_violations if violation.severity == "error"
        )
        adverse_warning_count = sum(
            1 for violation in adverse_violations if violation.severity == "warning"
        )
        adverse_info_count = sum(
            1 for violation in adverse_violations if violation.severity == "info"
        )
        constraint_count = int(evaluation.metadata.get("constraint_count", 0)) or max(
            len(evaluation.result.violations), 1
        )

        contradiction_density = min(max(error_count / float(constraint_count), 0.0), 1.0)
        violation_pressure = (
            adverse_error_count
            + (0.5 * adverse_warning_count)
            + (0.2 * adverse_info_count)
        ) / float(constraint_count)
        ambiguity_pressure = (1.0 - top_margin) * entropy_norm
        p_bad = self._governance_calibration.probability(
            violation_pressure=min(max(violation_pressure, 0.0), 1.0),
            ambiguity_pressure=min(max(ambiguity_pressure, 0.0), 1.0),
            contradiction_density=contradiction_density,
            posterior_entropy_norm=entropy_norm,
            top_margin=top_margin,
        )
        ruin_mass = self.manager.ruin_mass(posterior)
        direct_ruin_criterion_active = self._direct_ruin_criterion_latched

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
            direct_ruin_criterion_active=direct_ruin_criterion_active,
            direct_ruin_criterion_observed=direct_ruin_criterion_observed,
        )

    def _update_direct_ruin_criterion_latch(
        self,
        *,
        sign: SignT,
        evaluation: ManifoldEvaluation[StateT],
        release_evidence_qualified: bool,
    ) -> bool:
        sign_predicate = getattr(sign, "direct_ruin_criterion_observed", None)
        direct_ruin_criterion_observed = (
            (bool(sign_predicate()) if callable(sign_predicate) else False)
            or evaluation.is_ruin
            or any(
                bool((violation.metadata or {}).get("red_boundary"))
                for violation in evaluation.result.violations
            )
        )
        if direct_ruin_criterion_observed:
            self._direct_ruin_criterion_latched = True
        elif (
            release_evidence_qualified
            or not self._direct_ruin_latch_requires_qualified_release(sign)
        ):
            self._direct_ruin_criterion_latched = False
        return direct_ruin_criterion_observed

    def _derive_governance_context(
        self,
        metrics: GovernanceMetrics,
        *,
        review_fingerprint: str,
        materially_new_red_evidence: bool,
    ) -> GovernanceContext:
        th = self._governance_thresholds
        contradiction_streak = self._contradiction_streak + 1 if metrics.contradiction_density > th.c_high else 0
        is_stable = (
            metrics.top_p is not None
            and metrics.top_p >= th.tau_collapse
            and metrics.top_margin >= th.eps_collapse
            and metrics.contradiction_density <= th.c_ok
        )
        stable_iters = self._stable_iters + 1 if is_stable else 0
        red_condition = (
            metrics.direct_ruin_criterion_active
            or threshold_met(metrics.ruin_mass, th.tau_red)
        )
        if red_condition:
            red_override_dwell_iters = (
                1
                if materially_new_red_evidence
                else self._red_override_dwell_iters + 1
                if review_fingerprint in self._seen_red_review_fingerprints
                else 1
            )
        else:
            red_override_dwell_iters = 0
        return GovernanceContext(
            contradiction_streak=contradiction_streak,
            mixture_dwell_iters=self._mixture_dwell_iters,
            red_override_dwell_iters=red_override_dwell_iters,
            red_capture_review_active=self._red_capture_review_active,
            stable_iters=stable_iters,
        )

    def _update_governance_history(
        self,
        metrics: GovernanceMetrics,
        decision: GovernanceDecision,
        *,
        context: GovernanceContext,
        review_fingerprint: str,
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

        if decision.red_veto_active:
            self._red_override_dwell_iters = context.red_override_dwell_iters
            self._last_red_review_fingerprint = review_fingerprint
            self._seen_red_review_fingerprints.add(review_fingerprint)
        else:
            self._red_override_dwell_iters = 0
            self._last_red_review_fingerprint = None
            self._seen_red_review_fingerprints.clear()
            self._red_capture_review_active = False

        if "RED_CAPTURE_REVIEW" in decision.trigger_codes:
            self._red_capture_review_active = True

    @staticmethod
    def _fingerprint_payload(
        value: Any,
        *,
        excluded_keys: set[str] | None = None,
    ) -> str:
        if is_dataclass(value) and not isinstance(value, type):
            normalized: Any = asdict(value)
        elif hasattr(value, "__dict__"):
            normalized = dict(vars(value))
        else:
            normalized = value
        if isinstance(normalized, dict) and excluded_keys:
            normalized = {
                key: item
                for key, item in normalized.items()
                if key not in excluded_keys
            }
        if isinstance(normalized, dict) and isinstance(normalized.get("notes"), str):
            normalized["notes"] = NavigationController._normalize_evidence_notes(
                normalized["notes"]
            )
        raw = json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_evidence_notes(value: str) -> str:
        without_controls = re.sub(
            r"(?i)\b(?:evidence_id|independent_observation)\s*[:=]\s*[A-Za-z0-9._:-]+",
            " ",
            value,
        )
        return " ".join(without_controls.split())

    @staticmethod
    def _optional_evidence_id(sign: Any) -> Optional[str]:
        raw = getattr(sign, "evidence_id", None)
        if raw is None:
            return None
        value = str(raw).strip()
        if not value:
            raise ValueError("evidence_id must be non-empty when provided.")
        return value

    @staticmethod
    def _red_release_assessed_negative(sign: Any) -> bool:
        predicate = getattr(sign, "red_release_assessed_negative", None)
        return bool(predicate()) if callable(predicate) else False

    @staticmethod
    def _red_applicability_fingerprint_payload(sign: Any) -> Any:
        predicate = getattr(sign, "red_applicability_fingerprint_payload", None)
        return predicate() if callable(predicate) else sign

    @staticmethod
    def _direct_ruin_latch_requires_qualified_release(sign: Any) -> bool:
        predicate = getattr(
            sign,
            "direct_ruin_latch_requires_qualified_release",
            None,
        )
        return bool(predicate()) if callable(predicate) else True

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


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _checkpoint_bool(checkpoint: Mapping[str, Any], key: str) -> bool:
    value = checkpoint.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"Navigation checkpoint {key} must be boolean.")
    return value


def _checkpoint_nonnegative_int(checkpoint: Mapping[str, Any], key: str) -> int:
    value = checkpoint.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"Navigation checkpoint {key} must be a non-negative integer."
        )
    return value


__all__ = [
    "NavigationController",
    "NavigationTraceEntry",
]
