from __future__ import annotations

from dataclasses import replace

import pytest

from nepsis_cgn.core import InterpretantManager, NavigationController
from nepsis_cgn.core.interpretant import WordPuzzleSign
from nepsis_cgn.core.governance import (
    GovernanceCalibration,
    GovernanceCosts,
    GovernanceThresholds,
)
from nepsis_cgn.core.runtime import build_navigation_controller
from nepsis_cgn.manifolds.clinical import ClinicalSign
from nepsis_cgn.manifolds.red_blue import SafetySign, build_red_blue_hypotheses


def test_navigation_packet_lineage_increments() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(manager, emit_iteration_packet=True)

    first = nav.step(SafetySign(critical_signal=True))
    second = nav.step(SafetySign(critical_signal=False))

    assert first.iteration_packet is not None
    assert second.iteration_packet is not None

    p1 = first.iteration_packet
    p2 = second.iteration_packet

    assert p1["meta"]["iteration"] == 0
    assert p2["meta"]["iteration"] == 1
    assert p1["meta"]["session_id"] == p2["meta"]["session_id"]
    assert p2["meta"]["parent_packet_id"] == p1["meta"]["packet_id"]
    assert p1["stage"] == "evaluated"
    assert p1["stage_events"] == ["CALL", "REPORT", "EVALUATE"]
    assert p2["stage"] == "evaluated"
    assert p2["stage_events"] == ["ITERATE", "CALL", "REPORT", "EVALUATE"]


def test_navigation_commit_stage_and_next_iteration_reset() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(manager, emit_iteration_packet=True)

    committed = nav.step(SafetySign(critical_signal=False), commit=True)
    assert committed.iteration_packet is not None
    p1 = committed.iteration_packet
    assert p1["stage"] == "committed"
    assert p1["stage_events"] == ["CALL", "REPORT", "EVALUATE", "COMMIT"]
    assert nav.current_stage == "committed"

    follow_up = nav.step(SafetySign(critical_signal=False))
    assert follow_up.iteration_packet is not None
    p2 = follow_up.iteration_packet
    assert p2["stage"] == "evaluated"
    assert p2["stage_events"] == ["ITERATE", "CALL", "REPORT", "EVALUATE"]


def test_frame_lineage_in_packet_after_reframe() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(manager, emit_iteration_packet=True)

    first = nav.step(SafetySign(critical_signal=True))
    assert first.iteration_packet is not None
    frame_1 = first.iteration_packet["frame_version"]
    assert frame_1["frame_version"] == 1

    nav.reframe(
        text="Refined safety question after contradiction review.",
        rationale_for_change="ABDUCT candidate frame selected.",
    )
    second = nav.step(SafetySign(critical_signal=False))
    assert second.iteration_packet is not None
    frame_2 = second.iteration_packet["frame_version"]
    assert frame_2["frame_version"] == 2
    assert frame_2["frame_id"] == frame_1["frame_id"]


def test_packet_includes_override_and_carry_forward() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        emit_iteration_packet=True,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    entry = nav.step(
        SafetySign(critical_signal=True),
        user_decision="continue_override",
        override_reason="Need one more real-world check before stopping.",
    )
    assert entry.iteration_packet is not None
    packet = entry.iteration_packet
    assert "carry_forward" in packet
    assert packet["carry_forward"]["facts"] == "keep"
    assert packet["governance"]["user_decision"] == "continue_override"
    assert "Need one more real-world check" in packet["governance"]["override_reason"]
    assert packet["schema_version"] == "0.2.0"
    assert packet["meta"]["policy_version"] == "gov-v1.1.0"
    assert packet["meta"]["evidence_policy_version"] == "evidence-v2"
    assert packet["governance"]["policy_inputs"]["costs"] == {
        "c_fp": 1.0,
        "c_fn": 9.0,
    }
    assert packet["governance"]["policy_inputs"]["calibration"] is not None
    assert packet["governance"]["policy_inputs"]["thresholds"] is not None
    assert packet["governance"]["policy_inputs_hash"].startswith("sha256:")
    assert packet["governance"]["red_authority"]["epistemic_scope"] == (
        "hazard_applicability_not_truth_selection"
    )


def test_packet_includes_channel_semantics() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(manager, emit_iteration_packet=True)

    entry = nav.step(SafetySign(critical_signal=False, policy_violation=False))
    assert entry.iteration_packet is not None
    packet = entry.iteration_packet

    assert packet["manifold"]["channel"]["space"] == "utility"
    assert packet["manifold"]["channel"]["label"] == "Blue channel"
    assert packet["manifold"]["channel"]["decision_mode"] == "graded"
    assert entry.trace_metadata["channel_space"] == "utility"
    assert entry.trace_metadata["channel_mode"] == "graded"


def test_packet_includes_still_gate_for_runtime_finalization() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        emit_iteration_packet=True,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    entry = nav.step(SafetySign(critical_signal=True, policy_violation=False))
    assert entry.iteration_packet is not None
    packet = entry.iteration_packet

    assert packet["still"]["name"] == "STILL"
    assert packet["still"]["status"] == "blocked"
    assert packet["still"]["finalization_permitted"] is False
    assert "governance_red_override" in packet["still"]["finalization_blockers"]
    assert packet["still"]["next_allowed_move"] == "contain_and_discriminate"


def test_still_blocked_red_cannot_advance_stage_to_committed() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        emit_iteration_packet=True,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    entry = nav.step(
        SafetySign(critical_signal=True, policy_violation=False),
        commit=True,
    )

    assert entry.iteration_packet is not None
    packet = entry.iteration_packet
    assert packet["stage"] == "evaluated"
    assert "COMMIT" not in packet["stage_events"]
    assert packet["commit_request"]["requested"] is True
    assert packet["commit_request"]["admitted"] is False
    assert packet["still"]["finalization_permitted"] is False
    assert "red_veto_active" in packet["still"]["finalization_blockers"]


def test_red_channel_commit_is_blocked_without_governance_costs() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(manager, emit_iteration_packet=True)

    entry = nav.step(
        SafetySign(critical_signal=True, policy_violation=False),
        commit=True,
    )

    assert entry.iteration_packet is not None
    packet = entry.iteration_packet
    assert packet["stage"] == "evaluated"
    assert packet["commit_request"]["admitted"] is False
    assert "COMMIT" not in packet["stage_events"]
    assert "red_boundary_active" in packet["still"]["finalization_blockers"]


def test_direct_red_latch_persists_without_governance_costs_until_qualified_release() -> None:
    nav = build_navigation_controller(
        families=["safety"],
        emit_iteration_packet=True,
    )
    nav.step(
        SafetySign(
            critical_signal=True,
            policy_violation=True,
            evidence_id="direct-hazard",
        )
    )

    blocked = nav.step(
        SafetySign(
            critical_signal=False,
            policy_violation=False,
            evidence_id="ordinary-negative",
        ),
        commit=True,
    )
    released = nav.step(
        SafetySign(
            critical_signal=False,
            policy_violation=False,
            evidence_id="independent-negative",
            independent_observation=True,
        ),
        commit=True,
    )

    assert blocked.governance_decision is None
    assert blocked.trace_metadata["red_veto_active"] is True
    assert blocked.iteration_packet is not None
    assert blocked.iteration_packet["commit_request"]["admitted"] is False
    assert "direct_ruin_criterion_active" in blocked.iteration_packet["still"][
        "finalization_blockers"
    ]
    assert released.iteration_packet is not None
    assert released.iteration_packet["commit_request"]["admitted"] is True


def test_fully_reassessed_puzzle_ruin_clears_without_an_impossible_evidence_attestation() -> None:
    nav = build_navigation_controller(
        families=["puzzle"],
        emit_iteration_packet=True,
    )
    first = nav.step(
        WordPuzzleSign(letters="JAIILUNG", candidate="JAILING"),
        commit=True,
    )
    corrected = nav.step(
        WordPuzzleSign(letters="JAIILUNG", candidate="JAILINGU"),
        commit=True,
    )

    assert first.iteration_packet is not None
    assert first.trace_metadata["direct_ruin_criterion_active"] is True
    assert first.iteration_packet["commit_request"]["admitted"] is False
    assert corrected.iteration_packet is not None
    assert corrected.trace_metadata["direct_ruin_criterion_active"] is False
    assert corrected.iteration_packet["commit_request"]["admitted"] is True


def test_repeated_red_requires_zeroback_while_veto_remains_active() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        emit_iteration_packet=True,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_thresholds=GovernanceThresholds(max_red_dwell_iters=3),
    )

    first = nav.step(SafetySign(critical_signal=True, policy_violation=False))
    second = nav.step(SafetySign(critical_signal=True, policy_violation=False))
    third = nav.step(SafetySign(critical_signal=True, policy_violation=False))

    assert first.governance_decision is not None
    assert second.governance_decision is not None
    assert first.governance_decision.posture == "red_override"
    assert second.governance_decision.posture == "red_override"
    assert third.iteration_packet is not None
    packet = third.iteration_packet
    assert packet["governance"]["posture"] == "red_review"
    assert packet["governance"]["red_veto_active"] is True
    assert "RED_CAPTURE_REVIEW" in packet["governance"]["trigger_codes"]
    assert packet["still"]["finalization_permitted"] is False
    assert "governance_red_review" in packet["still"]["finalization_blockers"]
    assert packet["still"]["next_allowed_move"] == "review_red_applicability"


def test_manifest_runtime_negative_evidence_lowers_red_hypothesis_and_ruin_mass() -> None:
    nav = build_navigation_controller(
        families=["safety"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    first = nav.step(SafetySign(critical_signal=True, policy_violation=False))
    second = nav.step(SafetySign(critical_signal=False, policy_violation=False))

    assert first.governance_metrics is not None
    assert second.governance_metrics is not None
    assert second.posterior["safety_red"] < first.posterior["safety_red"]
    assert second.posterior["safety_blue"] > first.posterior["safety_blue"]
    assert second.governance_metrics.ruin_mass < first.governance_metrics.ruin_mass


def test_manifest_runtime_benign_signal_does_not_activate_red() -> None:
    nav = build_navigation_controller(
        families=["safety"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    entry = nav.step(SafetySign(critical_signal=False, policy_violation=False))

    assert entry.governance_decision is not None
    assert entry.governance_metrics is not None
    assert entry.governance_decision.posture != "red_override"
    assert entry.governance_decision.red_veto_active is False
    assert entry.governance_metrics.ruin_mass < 0.25


def test_manifest_clinical_unassessed_flags_are_neutral_but_assessed_absent_lowers_red() -> None:
    unassessed_nav = build_navigation_controller(
        families=["clinical"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    assessed_nav = build_navigation_controller(
        families=["clinical"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    unassessed = unassessed_nav.step(
        ClinicalSign(radicular_pain=True, spasm_present=True)
    )
    assessed_absent = assessed_nav.step(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            saddle_anesthesia=False,
            bladder_dysfunction=False,
            bilateral_weakness=False,
        )
    )

    assert unassessed.governance_metrics.ruin_mass == pytest.approx(0.25)
    assert unassessed.governance_decision.red_veto_active is True
    assert assessed_absent.governance_metrics.ruin_mass < 0.25
    assert assessed_absent.governance_decision.red_veto_active is False


def test_policy_violation_activates_red_even_without_critical_signal() -> None:
    nav = build_navigation_controller(
        families=["safety"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    entry = nav.step(
        SafetySign(critical_signal=False, policy_violation=True)
    )

    assert entry.manifold_evaluation.channel_semantics.space == "ruin"
    assert entry.manifold_evaluation.is_ruin is True
    assert entry.governance_decision.red_veto_active is True
    assert "DIRECT_RUIN_CRITERION_ACTIVE" in entry.governance_decision.trigger_codes


def test_direct_ruin_criterion_is_distinct_from_high_posterior_mass() -> None:
    nav = build_navigation_controller(
        families=["safety"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    for index in range(4):
        nav.step(
            SafetySign(
                critical_signal=False,
                policy_violation=False,
                notes=f"distinct clear observation {index}",
                evidence_id=f"clear-{index}",
            )
        )

    entry = nav.step(
        SafetySign(
            critical_signal=False,
            policy_violation=True,
            evidence_id="policy-violation",
        )
    )

    assert entry.governance_metrics.ruin_mass < 0.25
    assert entry.governance_metrics.p_bad < 1.0
    assert entry.governance_decision.red_veto_active is True
    assert "DIRECT_RUIN_CRITERION_ACTIVE" in entry.governance_decision.trigger_codes
    assert "RUIN_MASS_HIGH" not in entry.governance_decision.trigger_codes


def test_direct_ruin_latch_requires_assessed_negative_release_evidence() -> None:
    nav = build_navigation_controller(
        families=["clinical"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    nav.step(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            saddle_anesthesia=True,
            evidence_id="positive-red-flag",
        )
    )

    unassessed = nav.step(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            evidence_id="unassessed-followup",
            independent_observation=True,
        )
    )
    assessed_clear = nav.step(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            saddle_anesthesia=False,
            bladder_dysfunction=False,
            bilateral_weakness=False,
            evidence_id="assessed-clear-followup",
            independent_observation=True,
        )
    )

    assert unassessed.governance_metrics.direct_ruin_criterion_active is True
    assert unassessed.governance_decision.red_veto_active is True
    assert assessed_clear.governance_metrics.direct_ruin_criterion_active is False


def test_negative_red_discriminator_does_not_turn_manifold_mismatch_into_cost_escalation() -> None:
    nav = build_navigation_controller(
        families=["clinical"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    positive = nav.step(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            saddle_anesthesia=True,
            evidence_id="positive-exam",
        )
    )
    negative = nav.step(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            saddle_anesthesia=False,
            bladder_dysfunction=False,
            bilateral_weakness=False,
            evidence_id="negative-exam",
            independent_observation=True,
        )
    )

    assert negative.governance_metrics.ruin_mass < positive.governance_metrics.ruin_mass
    assert negative.governance_metrics.p_bad <= positive.governance_metrics.p_bad
    assert "COST_GATE_CROSSED" not in negative.governance_decision.trigger_codes
    assert negative.governance_decision.recommended_action == "contain_and_discriminate"


def test_ordinary_safety_notes_do_not_increase_bad_state_probability() -> None:
    plain_nav = build_navigation_controller(
        families=["safety"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    noted_nav = build_navigation_controller(
        families=["safety"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    plain = plain_nav.step(
        SafetySign(
            critical_signal=False,
            policy_violation=False,
            evidence_id="plain-clear-observation",
        )
    )
    noted = noted_nav.step(
        SafetySign(
            critical_signal=False,
            policy_violation=False,
            notes="Ordinary context that does not change the structured safety flags.",
            evidence_id="noted-clear-observation",
        )
    )

    assert noted.governance_metrics.p_bad == plain.governance_metrics.p_bad
    assert noted.governance_decision.posture == plain.governance_decision.posture
    assert "COST_GATE_CROSSED" not in noted.governance_decision.trigger_codes


def test_bilateral_weakness_recovers_red_after_prior_negative_evidence() -> None:
    nav = build_navigation_controller(
        families=["clinical"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    nav.step(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            saddle_anesthesia=False,
            bladder_dysfunction=False,
            bilateral_weakness=False,
            evidence_id="negative-exam",
        )
    )

    entry = nav.step(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            saddle_anesthesia=False,
            bladder_dysfunction=False,
            bilateral_weakness=True,
            evidence_id="weakness-exam",
        )
    )

    assert entry.manifold_evaluation.channel_semantics.space == "ruin"
    assert entry.manifold_evaluation.is_ruin is True
    assert entry.governance_decision.red_veto_active is True


def test_transformed_followup_ruin_qualifies_red_independent_of_posterior() -> None:
    nav = build_navigation_controller(
        families=["clinical"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    for index in range(4):
        nav.step(
            ClinicalSign(
                radicular_pain=True,
                spasm_present=True,
                saddle_anesthesia=False,
                bladder_dysfunction=False,
                bilateral_weakness=False,
                notes=f"clear clinical observation {index}",
                evidence_id=f"clear-clinical-{index}",
            )
        )
    entry = nav.step(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            saddle_anesthesia=False,
            bladder_dysfunction=False,
            bilateral_weakness=False,
            followup={"bilateral_weakness": True},
            evidence_id="followup-weakness",
        )
    )

    assert entry.manifold_evaluation.is_ruin is True
    assert entry.governance_metrics.ruin_mass < 0.25
    assert entry.governance_decision.red_veto_active is True


def test_manifest_clinical_likelihood_uses_effective_followup_red_flags() -> None:
    def posterior_for(sign: ClinicalSign) -> float:
        nav = build_navigation_controller(families=["clinical"])
        return nav.step(sign).posterior["clinical_cauda_equina"]

    top_level_negative = posterior_for(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            saddle_anesthesia=False,
            bladder_dysfunction=False,
            bilateral_weakness=False,
        )
    )
    followup_negative = posterior_for(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            followup={
                "saddle_anesthesia": False,
                "bladder_dysfunction": False,
                "bilateral_weakness": False,
            },
        )
    )
    top_level_positive = posterior_for(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            bilateral_weakness=True,
        )
    )
    followup_positive = posterior_for(
        ClinicalSign(
            radicular_pain=True,
            spasm_present=True,
            followup={"bilateral_weakness": True},
        )
    )

    assert followup_negative == pytest.approx(top_level_negative)
    assert followup_negative < 0.25
    assert followup_positive == pytest.approx(top_level_positive)
    assert followup_positive > 0.25


def test_manifest_runtime_sufficient_negative_evidence_exits_red() -> None:
    nav = build_navigation_controller(
        families=["safety"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    first = nav.step(
        SafetySign(critical_signal=True, policy_violation=False, evidence_id="signal-1")
    )
    second = nav.step(
        SafetySign(
            critical_signal=False,
            policy_violation=False,
            evidence_id="negative-1",
            independent_observation=True,
        )
    )
    third = nav.step(
        SafetySign(
            critical_signal=False,
            policy_violation=False,
            evidence_id="negative-2",
            independent_observation=True,
        )
    )

    assert first.governance_decision is not None
    assert second.governance_decision is not None
    assert third.governance_decision is not None
    assert first.governance_decision.red_veto_active is True
    assert second.governance_decision.red_veto_active is True
    assert third.governance_decision.red_veto_active is False
    assert third.governance_decision.posture != "zeroback"


def test_red_capture_review_stays_latched_until_explicit_reframe() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_thresholds=GovernanceThresholds(max_red_dwell_iters=2),
    )

    postures = [
        nav.step(
            SafetySign(critical_signal=True, policy_violation=False)
        ).governance_decision.posture
        for _ in range(5)
    ]

    assert postures == [
        "red_override",
        "red_review",
        "red_review",
        "red_review",
        "red_review",
    ]


def test_fresh_red_evidence_does_not_count_as_stagnant_capture() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_thresholds=GovernanceThresholds(max_red_dwell_iters=3),
    )

    entries = [
        nav.step(
            SafetySign(
                critical_signal=True,
                policy_violation=False,
                notes=f"fresh report {index}",
                evidence_id=f"report-{index}",
                independent_observation=True,
            )
        )
        for index in range(3)
    ]

    assert [entry.governance_decision.posture for entry in entries] == [
        "red_override",
        "red_override",
        "red_override",
    ]


def test_rotating_evidence_ids_cannot_hide_unchanged_red_content() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_thresholds=GovernanceThresholds(max_red_dwell_iters=3),
    )

    entries = [
        nav.step(
            SafetySign(
                critical_signal=True,
                policy_violation=False,
                evidence_id=f"rotating-id-{index}",
            )
        )
        for index in range(3)
    ]

    assert entries[2].governance_decision.posture == "red_review"
    assert "RED_CAPTURE_REVIEW" in entries[2].governance_decision.trigger_codes


def test_irrelevant_note_churn_cannot_evade_red_capture_review() -> None:
    nav = NavigationController(
        InterpretantManager(build_red_blue_hypotheses()),
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_thresholds=GovernanceThresholds(max_red_dwell_iters=3),
    )

    entries = [
        nav.step(
            SafetySign(
                critical_signal=True,
                policy_violation=False,
                notes=f"cosmetic note {index}",
                evidence_id=f"note-{index}",
            )
        )
        for index in range(3)
    ]

    assert entries[2].governance_decision.posture == "red_review"
    assert "RED_CAPTURE_REVIEW" in entries[2].governance_decision.trigger_codes


def test_user_decision_churn_does_not_evade_red_capture_review() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_thresholds=GovernanceThresholds(max_red_dwell_iters=3),
    )
    sign = SafetySign(critical_signal=True, policy_violation=False)

    nav.step(sign)
    nav.step(
        sign,
        user_decision="continue_override",
        override_reason="Reviewed, but no new evidence acquired.",
    )
    third = nav.step(sign)

    assert third.governance_decision.posture == "red_review"
    assert "RED_CAPTURE_REVIEW" in third.governance_decision.trigger_codes


def test_reframe_with_rationale_releases_capture_review_not_red_veto() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_thresholds=GovernanceThresholds(max_red_dwell_iters=2),
    )
    sign = SafetySign(critical_signal=True, policy_violation=False)

    nav.step(sign)
    review = nav.step(sign)
    assert review.governance_decision.posture == "red_review"
    with pytest.raises(ValueError):
        nav.reframe(text="Cosmetic reframe without rationale")
    with pytest.raises(ValueError):
        nav.reframe(
            rationale_for_change="Reviewed without changing the frame.",
        )

    nav.reframe(
        text="Reassess whether the signal applies to the blocked action.",
        rationale_for_change="Explicit RED applicability review.",
    )
    after = nav.step(sign)

    assert after.governance_decision.posture == "red_override"
    assert after.governance_decision.red_veto_active is True


def test_exact_ruin_boundary_accumulates_capture_review_dwell() -> None:
    base = build_red_blue_hypotheses()
    manager = InterpretantManager(
        [
            replace(base[0], prior=0.75),
            replace(base[1], prior=0.25, likelihood_fn=lambda _: 1.0),
        ]
    )
    nav = NavigationController(
        manager,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_thresholds=GovernanceThresholds(max_red_dwell_iters=3),
    )
    sign = SafetySign(
        critical_signal=False,
        policy_violation=False,
        evidence_id="boundary-observation",
    )

    first = nav.step(sign)
    second = nav.step(sign)
    third = nav.step(sign)

    assert first.governance_metrics.ruin_mass == pytest.approx(0.25)
    assert first.governance_decision.posture == "red_override"
    assert second.governance_decision.posture == "red_override"
    assert third.governance_decision.posture == "red_review"


def test_replayed_evidence_id_does_not_update_posterior_again() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(manager, emit_iteration_packet=True)

    nav.step(SafetySign(critical_signal=False, evidence_id="negative-a"))
    positive = nav.step(SafetySign(critical_signal=True, evidence_id="positive-b"))
    replay = nav.step(SafetySign(critical_signal=False, evidence_id="negative-a"))

    assert replay.posterior == positive.posterior
    assert replay.iteration_packet is not None
    assert replay.iteration_packet["evidence_update"]["posterior_update_applied"] is False


def test_control_tags_embedded_in_notes_cannot_disguise_duplicate_evidence() -> None:
    nav = build_navigation_controller(
        families=["safety"],
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    first = nav.step(
        SafetySign(
            critical_signal=False,
            policy_violation=False,
            notes="same clear observation evidence_id:clear-a",
            evidence_id="clear-a",
        )
    )
    second = nav.step(
        SafetySign(
            critical_signal=False,
            policy_violation=False,
            notes="same clear observation evidence_id:clear-b",
            evidence_id="clear-b",
        )
    )

    assert first.trace_metadata["posterior_update_applied"] is True
    assert second.trace_metadata["posterior_update_applied"] is False
    assert second.posterior == first.posterior


def test_anonymous_duplicate_governance_evidence_is_content_deduplicated() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        emit_iteration_packet=True,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )

    first = nav.step(SafetySign(critical_signal=False))
    replay = nav.step(SafetySign(critical_signal=False))

    assert replay.posterior == first.posterior
    assert replay.iteration_packet is not None
    assert replay.iteration_packet["evidence_update"]["identity_mode"] == (
        "anonymous_content_dedup"
    )
    assert replay.iteration_packet["evidence_update"]["posterior_update_applied"] is False


def test_alternating_replayed_ids_cannot_reset_red_capture_dwell() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_thresholds=GovernanceThresholds(max_red_dwell_iters=3),
    )
    first = SafetySign(critical_signal=True, notes="source A", evidence_id="red-a")
    second = SafetySign(critical_signal=True, notes="source B", evidence_id="red-b")

    nav.step(first)
    nav.step(second)
    nav.step(first)
    review = nav.step(second)

    assert review.governance_decision.posture == "red_review"


def test_reusing_evidence_id_with_changed_content_is_rejected() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(manager)
    nav.step(SafetySign(critical_signal=False, evidence_id="observation-1"))

    with pytest.raises(ValueError):
        nav.step(SafetySign(critical_signal=True, evidence_id="observation-1"))


def test_cost_review_blocks_commit_until_explicitly_dispositioned() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        emit_iteration_packet=True,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
        governance_calibration=GovernanceCalibration(prior_pi=0.3),
    )

    blocked = nav.step(
        SafetySign(critical_signal=False, evidence_id="cost-review-1"),
        commit=True,
    )
    admitted = nav.step(
        SafetySign(critical_signal=False, evidence_id="cost-review-2"),
        commit=True,
        user_decision="continue_override",
        override_reason="Reviewed expected-loss asymmetry; reversible action remains appropriate.",
    )

    assert blocked.governance_decision.posture == "cost_review"
    assert blocked.governance_decision.red_veto_active is False
    assert blocked.iteration_packet["commit_request"]["admitted"] is False
    assert "governance_cost_review" in blocked.iteration_packet["still"]["finalization_blockers"]
    assert admitted.iteration_packet["commit_request"]["admitted"] is True


def test_stop_decision_prevents_commit_transition() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(
        manager,
        emit_iteration_packet=True,
        governance_costs=GovernanceCosts(c_fp=1.0, c_fn=9.0),
    )
    entry = nav.step(
        SafetySign(critical_signal=True),
        commit=True,
        user_decision="stop",
    )
    assert entry.iteration_packet is not None
    packet = entry.iteration_packet
    assert packet["stage"] == "evaluated"
    assert "COMMIT" not in packet["stage_events"]


def test_override_requires_governance_enabled() -> None:
    manager = InterpretantManager(build_red_blue_hypotheses())
    nav = NavigationController(manager, emit_iteration_packet=True)
    with pytest.raises(ValueError):
        nav.step(
            SafetySign(critical_signal=True),
            user_decision="continue_override",
            override_reason="cannot without governance",
        )
