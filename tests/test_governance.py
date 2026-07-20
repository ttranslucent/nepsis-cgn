from __future__ import annotations

import pytest

from nepsis_cgn.core.governance import (
    GovernanceCalibration,
    GovernanceContext,
    GovernanceCosts,
    GovernanceMetrics,
    GovernanceThresholds,
    IterationStateMachine,
    compute_theta,
    evaluate_governance_policy,
    expected_losses,
    posterior_from_lr,
    posterior_from_score,
)
from nepsis_cgn.core.interpretant import InterpretantManager
from nepsis_cgn.manifolds.red_blue import SafetySign, build_red_blue_hypotheses


def test_compute_theta() -> None:
    assert compute_theta(10.0, 90.0) == 0.1


def test_expected_losses() -> None:
    loss_treat, loss_notreat = expected_losses(p_bad=0.2, c_fp=10.0, c_fn=100.0)
    assert loss_treat == pytest.approx(8.0)
    assert loss_notreat == pytest.approx(20.0)


def test_posterior_from_lr() -> None:
    # Prior 0.2 with LR=4 should move to 0.5.
    assert posterior_from_lr(prior_pi=0.2, lr=4.0) == pytest.approx(0.5)


def test_posterior_from_score_identity_when_zero_calibration() -> None:
    # With zero calibration shift and slope, posterior should equal prior.
    assert posterior_from_score(prior_pi=0.2, score_s=10.0, a=0.0, b=0.0) == pytest.approx(0.2)


def test_governance_calibration_probability_increases_with_violation_pressure() -> None:
    calibration = GovernanceCalibration()
    low = calibration.probability(
        violation_pressure=0.1,
        ambiguity_pressure=0.2,
        contradiction_density=0.1,
        posterior_entropy_norm=0.2,
        top_margin=0.6,
    )
    high = calibration.probability(
        violation_pressure=0.8,
        ambiguity_pressure=0.2,
        contradiction_density=0.1,
        posterior_entropy_norm=0.2,
        top_margin=0.6,
    )
    assert high > low


def test_default_calibration_does_not_convert_uncertainty_into_hazard_evidence() -> None:
    calibration = GovernanceCalibration(prior_pi=0.1)

    probability = calibration.probability(
        violation_pressure=0.0,
        ambiguity_pressure=1.0,
        contradiction_density=0.0,
        posterior_entropy_norm=1.0,
        top_margin=0.0,
    )

    assert probability == pytest.approx(0.1)


def test_iteration_state_machine_happy_path() -> None:
    sm = IterationStateMachine()
    assert sm.stage == "draft"
    assert sm.apply("CALL") == "called"
    assert sm.apply("REPORT") == "reported"
    assert sm.apply("EVALUATE") == "evaluated"
    assert sm.apply("COMMIT") == "committed"
    assert sm.apply("ITERATE") == "draft"


def test_iteration_state_machine_invalid_transition() -> None:
    sm = IterationStateMachine(stage="draft")
    with pytest.raises(ValueError):
        sm.apply("COMMIT")


def test_policy_cost_gate_requests_review_without_acquiring_red_veto() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.3,
        ruin_mass=0.1,
        contradiction_density=0.1,
        posterior_entropy_norm=0.3,
        top_margin=0.3,
        top_p=0.7,
    )
    costs = GovernanceCosts(c_fp=1.0, c_fn=9.0)  # theta=0.1
    decision = evaluate_governance_policy(metrics, costs)
    assert decision.posture == "cost_review"
    assert decision.warning_level == "yellow"
    assert decision.recommended_action == "review_protective_action"
    assert decision.red_veto_active is False
    assert "COST_GATE_CROSSED" in decision.trigger_codes


def test_policy_ruin_only_contains_and_discriminates_without_releasing_veto() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.05,
        ruin_mass=0.3,
        contradiction_density=0.1,
        posterior_entropy_norm=0.3,
        top_margin=0.3,
        top_p=0.7,
    )
    costs = GovernanceCosts(c_fp=1.0, c_fn=9.0)  # theta=0.1

    decision = evaluate_governance_policy(metrics, costs)

    assert decision.posture == "red_override"
    assert decision.red_veto_active is True
    assert decision.recommended_action == "contain_and_discriminate"
    assert decision.loss_treat > decision.loss_notreat
    assert decision.trigger_codes == ("RUIN_MASS_HIGH",)


def test_policy_cost_threshold_equality_does_not_count_as_crossed() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.1,
        ruin_mass=0.24,
        contradiction_density=0.0,
        posterior_entropy_norm=0.2,
        top_margin=0.3,
        top_p=0.7,
    )

    decision = evaluate_governance_policy(
        metrics,
        GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    assert decision.posture == "continue"
    assert decision.red_veto_active is False
    assert "RUIN_MASS_HIGH" not in decision.trigger_codes
    assert "COST_GATE_CROSSED" not in decision.trigger_codes


def test_policy_ruin_threshold_equality_preserves_red_veto() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.05,
        ruin_mass=0.25,
        contradiction_density=0.0,
        posterior_entropy_norm=0.2,
        top_margin=0.3,
        top_p=0.7,
    )

    decision = evaluate_governance_policy(
        metrics,
        GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    assert decision.posture == "red_override"
    assert decision.red_veto_active is True
    assert decision.recommended_action == "contain_and_discriminate"
    assert decision.trigger_codes == ("RUIN_MASS_HIGH",)


def test_persistent_red_zerobacks_without_releasing_ruin_veto() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.05,
        ruin_mass=0.3,
        contradiction_density=0.1,
        posterior_entropy_norm=0.3,
        top_margin=0.3,
        top_p=0.7,
    )
    costs = GovernanceCosts(c_fp=1.0, c_fn=9.0)
    context = GovernanceContext(red_override_dwell_iters=3)

    decision = evaluate_governance_policy(metrics, costs, context=context)

    assert decision.posture == "red_review"
    assert decision.warning_level == "red"
    assert decision.recommended_action == "review_red_applicability"
    assert decision.red_veto_active is True
    assert "RUIN_MASS_HIGH" in decision.trigger_codes
    assert "RED_CAPTURE_REVIEW" in decision.trigger_codes


def test_policy_mixture_mode_for_margin_and_entropy() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.05,
        ruin_mass=0.02,
        contradiction_density=0.2,
        posterior_entropy_norm=0.8,
        top_margin=0.03,
        top_p=0.55,
    )
    costs = GovernanceCosts(c_fp=1.0, c_fn=9.0)  # theta=0.1
    decision = evaluate_governance_policy(metrics, costs)
    assert decision.posture == "mixture_mode"
    assert decision.warning_level == "yellow"
    assert decision.recommended_action == "abduct"
    assert "MARGIN_COLLAPSE" in decision.trigger_codes


def test_policy_anti_stall_after_dwell_limit() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.05,
        ruin_mass=0.01,
        contradiction_density=0.25,
        posterior_entropy_norm=0.75,
        top_margin=0.02,
        top_p=0.58,
    )
    costs = GovernanceCosts(c_fp=1.0, c_fn=9.0)
    context = GovernanceContext(mixture_dwell_iters=4)
    decision = evaluate_governance_policy(metrics, costs, context=context)
    assert decision.posture == "anti_stall"
    assert decision.recommended_action == "run_test"
    assert "ANTI_STALL" in decision.trigger_codes


def test_policy_anti_stall_on_dwell_limit_boundary() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.05,
        ruin_mass=0.01,
        contradiction_density=0.25,
        posterior_entropy_norm=0.75,
        top_margin=0.02,
        top_p=0.58,
    )
    costs = GovernanceCosts(c_fp=1.0, c_fn=9.0)
    context = GovernanceContext(mixture_dwell_iters=3)
    decision = evaluate_governance_policy(metrics, costs, context=context)
    assert decision.posture == "anti_stall"


def test_policy_zeroback_on_recurrence_pattern() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.05,
        ruin_mass=0.01,
        contradiction_density=0.5,
        posterior_entropy_norm=0.8,
        top_margin=0.03,
        top_p=0.56,
    )
    costs = GovernanceCosts(c_fp=1.0, c_fn=9.0)
    context = GovernanceContext(contradiction_streak=3, mixture_dwell_iters=4)
    decision = evaluate_governance_policy(metrics, costs, context=context)
    assert decision.posture == "zeroback"
    assert decision.recommended_action == "perform_zeroback"
    assert "RECURRENCE_PATTERN" in decision.trigger_codes


def test_governance_thresholds_validate_margin_and_collapse_epsilons() -> None:
    with pytest.raises(ValueError, match="eps_margin"):
        evaluate_governance_policy(
            GovernanceMetrics(
                p_bad=0.01,
                ruin_mass=0.01,
                contradiction_density=0.0,
                posterior_entropy_norm=0.2,
                top_margin=0.9,
            ),
            GovernanceCosts(c_fp=1.0, c_fn=9.0),
            thresholds=GovernanceThresholds(eps_margin=-0.1),
        )

    with pytest.raises(ValueError, match="eps_collapse"):
        evaluate_governance_policy(
            GovernanceMetrics(
                p_bad=0.01,
                ruin_mass=0.01,
                contradiction_density=0.0,
                posterior_entropy_norm=0.2,
                top_margin=0.9,
            ),
            GovernanceCosts(c_fp=1.0, c_fn=9.0),
            thresholds=GovernanceThresholds(eps_collapse=1.1),
        )


def test_policy_collapse_mode_when_stable() -> None:
    metrics = GovernanceMetrics(
        p_bad=0.03,
        ruin_mass=0.02,
        contradiction_density=0.05,
        posterior_entropy_norm=0.2,
        top_margin=0.25,
        top_p=0.85,
    )
    costs = GovernanceCosts(c_fp=1.0, c_fn=9.0)
    context = GovernanceContext(stable_iters=2)
    decision = evaluate_governance_policy(metrics, costs, context=context)
    assert decision.posture == "collapse_mode"
    assert decision.recommended_action == "collapse"
    assert decision.warning_level == "green"


def test_ruin_mass_uses_catastrophic_hypotheses() -> None:
    hypotheses = build_red_blue_hypotheses()
    manager = InterpretantManager(hypotheses=hypotheses)
    posterior = manager.update(SafetySign(critical_signal=True))
    ruin_mass = manager.ruin_mass(posterior)
    assert 0.0 <= ruin_mass <= 1.0
    assert ruin_mass == pytest.approx(posterior["red_channel"])


def test_interpretant_manager_allows_negative_evidence_to_lower_red_posterior() -> None:
    manager = InterpretantManager(hypotheses=build_red_blue_hypotheses())
    first = manager.update(SafetySign(critical_signal=True))
    second = manager.update(SafetySign(critical_signal=False))
    assert first["red_channel"] > 0.5
    assert second["red_channel"] < first["red_channel"]
    assert second["blue_channel"] > first["blue_channel"]
