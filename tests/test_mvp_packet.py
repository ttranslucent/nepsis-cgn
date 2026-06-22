from __future__ import annotations

import pytest

from nepsis_cgn.core.mvp import (
    MVP_PACKET_SCHEMA_ID,
    MVP_PACKET_SCHEMA_VERSION,
    build_nepsis_mvp_packet,
)

PUBLIC_MVP_CASE_IDS = ("jailing", "sea_ivdu", "wirecard")

MINIMUM_PACKET_FIELDS = {
    "schema_id",
    "schema_version",
    "packet_id",
    "created_at",
    "case_id",
    "input_text",
    "public_release",
    "observations",
    "constraints",
    "red_channel",
    "blue_channel",
    "contradiction_monitor",
    "denominator_collapse",
    "retessellation_state",
    "voronoi_commitment",
    "state_feedback",
    "non_quiescence",
    "still",
    "zeroback",
    "audit_trace",
    "final_output",
    "demo_limitations",
}


@pytest.mark.parametrize("case_id", PUBLIC_MVP_CASE_IDS)
def test_mvp_packet_top_level_schema_is_stable(case_id: str) -> None:
    packet = build_nepsis_mvp_packet(case_id=case_id)

    assert set(packet) == MINIMUM_PACKET_FIELDS


def test_public_mvp_v04_case_set_and_release_metadata() -> None:
    for case_id in PUBLIC_MVP_CASE_IDS:
        packet = build_nepsis_mvp_packet(case_id=case_id)

        assert packet["schema_id"] == MVP_PACKET_SCHEMA_ID
        assert packet["schema_version"] == MVP_PACKET_SCHEMA_VERSION == "0.2.0"
        assert packet["case_id"] == case_id
        assert packet["public_release"] == {
            "release_id": "public_mvp_v0.4",
            "label": "Public MVP v0.4",
            "mode": "deterministic_packet_proof",
            "model_free": True,
            "login_required": False,
            "api_key_required": False,
            "supported_cases": list(PUBLIC_MVP_CASE_IDS),
        }


def test_retired_public_clinical_case_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="jailing, sea_ivdu, wirecard"):
        build_nepsis_mvp_packet(case_id="clinical")  # type: ignore[arg-type]


def test_jailing_mvp_packet_preserves_constraint_and_retessellates() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")

    assert packet["schema_id"] == MVP_PACKET_SCHEMA_ID
    assert packet["schema_version"] == MVP_PACKET_SCHEMA_VERSION == "0.2.0"
    assert MINIMUM_PACKET_FIELDS.issubset(packet)
    assert packet["case_id"] == "jailing"
    assert packet["red_channel"]["escalation_required"] is True
    assert packet["denominator_collapse"]["detected"] is True
    assert packet["denominator_collapse"]["retessellation_required"] is True
    assert packet["still"]["name"] == "STILL"
    assert len(packet["still"]["checkpoints"]) >= 2
    assert packet["still"]["checkpoints"][0]["position"] == "after_red_before_blue"
    assert packet["still"]["checkpoints"][0]["trigger_status"] == "hold_or_bounded_blue"
    assert packet["still"]["commitment_readiness"]["status"] == "retessellate"
    assert packet["still"]["commitment_readiness"]["zeroback_triggered"] is True
    assert packet["still"]["commitment_readiness"]["effective_action"] == "zeroback"
    assert (
        "retessellate" in packet["still"]["commitment_readiness"]["co_trigger_statuses"]
    )
    assert packet["still"]["audit_events"]
    assert packet["zeroback"]["triggered"] is True
    assert packet["retessellation_state"]["status"] == "completed_in_packet"
    assert packet["retessellation_state"]["trigger_event_order"] == 8
    assert packet["retessellation_state"]["completed_event_order"] == 9
    assert (
        "next-cycle source-token verification"
        in packet["retessellation_state"]["remaining_obligation"]
    )
    assert packet["state_feedback"]["predicted_next_state"]["failure_conditions"]
    assert packet["state_feedback"]["loop_decision"]["status"] == "pending_observation"
    assert packet["state_feedback"]["loop_decision"]["next_observation_required"]
    assert "JINGALL" in packet["final_output"]["concise_recommendation"]
    assert "JAILING" in packet["final_output"]["concise_recommendation"]
    assert packet["final_output"]["required_next_discriminators"]


def test_mvp_audit_trace_runs_red_before_blue_and_retessellation() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")
    stages = [event["stage"] for event in packet["audit_trace"]]

    assert stages.index("red_channel") < stages.index("still_checkpoint_1")
    assert stages.index("still_checkpoint_1") < stages.index("blue_channel")
    assert stages.index("blue_channel") < stages.index("contradiction_monitor")
    assert stages.index("contradiction_monitor") < stages.index("still_checkpoint_2")
    assert stages.index("still_checkpoint_2") < stages.index("retessellation")
    assert stages.index("voronoi_commitment") < stages.index("state_feedback")
    assert stages[-1] == "state_feedback"


def test_mvp_state_feedback_declares_predicted_next_state() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")
    feedback = packet["state_feedback"]

    assert feedback["current_state"]["active_frame"] == "governed token constraint"
    assert feedback["predicted_next_state"]["expected_changes"]
    assert feedback["predicted_next_state"]["failure_conditions"]
    assert feedback["observed_next_state"]["status"] == "not_observed_in_mvp"
    assert feedback["delta_analysis"]["matches_prediction"] == "pending"
    assert feedback["loop_decision"]["next_observation_required"]
    assert feedback["audit_events"]


def test_mvp_still_audit_events_are_ordered() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")
    still_events = packet["still"]["audit_events"]

    assert [event["stage"] for event in still_events] == [
        "still_checkpoint_1",
        "still_checkpoint_2",
    ]
    assert still_events[0]["order"] < still_events[1]["order"]


def test_mvp_blue_channel_separates_support_and_action_axes() -> None:
    packet = build_nepsis_mvp_packet(case_id="sea_ivdu")
    blue_channel = packet["blue_channel"]
    axes = blue_channel["evaluation_axes"]
    hypotheses = {
        hypothesis["id"]: hypothesis for hypothesis in blue_channel["hypotheses"]
    }

    assert "weights" not in blue_channel
    assert (
        hypotheses["benign_non_radicular_back_pain"]["likelihood"]
        == "surface_plausible"
    )
    assert (
        hypotheses["benign_non_radicular_back_pain"]["post_constraint_standing"]
        == "red_bounded"
    )
    assert (
        hypotheses["benign_non_radicular_back_pain"]["action_priority"]
        == "blocked_until_sea_closed"
    )
    assert hypotheses["spinal_epidural_abscess"]["likelihood"] == "uncertain_support"
    assert (
        hypotheses["spinal_epidural_abscess"]["post_constraint_standing"]
        == "action_dominant_by_risk_feature"
    )
    assert (
        hypotheses["spinal_epidural_abscess"]["action_priority"]
        == "red-action-dominant"
    )
    assert (
        axes["support"]["by_hypothesis"]["benign_non_radicular_back_pain"]
        == "surface_plausible"
    )
    assert axes["support"]["by_hypothesis"]["spinal_epidural_abscess"] == "uncertain"
    assert (
        axes["action_priority"]["by_hypothesis"]["spinal_epidural_abscess"]
        == "red-action-dominant"
    )
    assert "red-action-dominant" not in axes["support"]["by_hypothesis"].values()


def test_mvp_contradiction_density_declares_saturating_count_basis() -> None:
    jailing = build_nepsis_mvp_packet(case_id="jailing")
    sea = build_nepsis_mvp_packet(case_id="sea_ivdu")
    wirecard = build_nepsis_mvp_packet(case_id="wirecard")

    assert jailing["contradiction_monitor"]["contradiction_density"] == pytest.approx(
        2 / 3
    )
    assert sea["contradiction_monitor"]["contradiction_density"] == pytest.approx(1 / 2)
    assert wirecard["contradiction_monitor"]["contradiction_density"] == pytest.approx(
        1 / 2
    )

    for packet in (jailing, sea, wirecard):
        monitor = packet["contradiction_monitor"]
        basis = monitor["density_basis"]
        count = len(monitor["contradictions"])

        assert basis["model"] == "saturating_count_v1"
        assert basis["formula"] == "contradiction_count / (contradiction_count + 1)"
        assert basis["contradiction_count"] == count
        assert basis["aggregate_role"] == "demo_only_scalar_summary"
        assert basis["runtime_gate_input"] is False
        assert basis["channel_note"]

    jailing_monitor = jailing["contradiction_monitor"]
    assert jailing_monitor["contradictions"][0] == {
        "id": "candidate_token_mismatch",
        "type": "constraint contradiction",
        "level": "object",
        "status": "resolved_in_packet",
        "observation": "candidate_token=JAILING",
        "conflicts_with": "Hard constraint requires JINGALL",
        "introduced_at_order": 5,
        "resolution_event_order": 11,
    }
    assert jailing_monitor["density_channels"]["object"][
        "contradiction_density"
    ] == pytest.approx(1 / 2)
    assert jailing_monitor["density_channels"]["object"]["resolved_count"] == 1
    assert jailing_monitor["density_channels"]["meta"]["resolved_count"] == 1


def test_mvp_jailing_packet_declares_support_constraint_and_limitations() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")
    hypotheses = {
        hypothesis["id"]: hypothesis
        for hypothesis in packet["blue_channel"]["hypotheses"]
    }

    assert hypotheses["constraint_preserving_token"]["likelihood"] == "high_support"
    assert (
        hypotheses["constraint_preserving_token"]["post_constraint_standing"]
        == "dominant_after_red_constraint"
    )
    assert (
        hypotheses["constraint_preserving_token"]["action_priority"]
        == "commit_after_exact_token_match"
    )
    assert (
        hypotheses["plausible_word_collapse"]["likelihood"] == "surface_plausible_only"
    )
    assert (
        hypotheses["plausible_word_collapse"]["post_constraint_standing"]
        == "rejected_by_constraint"
    )
    assert (
        hypotheses["plausible_word_collapse"]["action_priority"]
        == "blocked_by_red_boundary"
    )

    limitation_ids = {limitation["id"] for limitation in packet["demo_limitations"]}
    limitation_text = " ".join(
        limitation["limitation"] for limitation in packet["demo_limitations"]
    )
    assert "source_token_corruption_not_detected" in limitation_ids
    assert "source token itself is corrupted" in limitation_text


def test_revised_sea_mvp_packet_holds_red_open_from_ivdu_feature() -> None:
    packet = build_nepsis_mvp_packet(case_id="sea_ivdu")

    assert "non-radicular back pain" in packet["input_text"]
    assert "intravenous use" in packet["input_text"]
    assert (
        packet["red_channel"]["active_hazards"][0]["id"]
        == "spinal_epidural_abscess_must_not_miss"
    )
    assert packet["red_channel"]["active_hazards"][0]["features"] == [
        "intravenous_use_history"
    ]
    assert packet["red_channel"]["escalation_required"] is True
    assert packet["blue_channel"]["evaluation_axes"]["action_priority"][
        "by_hypothesis"
    ]["spinal_epidural_abscess"] == ("red-action-dominant")
    assert packet["non_quiescence"]["wrong_manifold_possible"] is True
    assert packet["still"]["checkpoints"][0]["trigger_status"] == "escalation_preserved"
    assert packet["still"]["commitment_readiness"]["status"] == "retessellate"
    assert packet["retessellation_state"]["status"] == "completed_in_packet"
    assert (
        packet["state_feedback"]["current_state"]["active_frame"]
        == "SEA red-channel risk from intravenous use"
    )
    assert packet["state_feedback"]["predicted_next_state"]["failure_conditions"]
    assert packet["state_feedback"]["loop_decision"]["status"] == "pending_observation"
    assert packet["state_feedback"]["loop_decision"]["next_observation_required"]
    contradiction = packet["contradiction_monitor"]["contradictions"][0]
    assert contradiction["level"] == "action_threshold"
    assert contradiction["status"] == "open_pending_discriminators"
    assert (
        packet["contradiction_monitor"]["density_channels"]["action_threshold"][
            "open_count"
        ]
        == 1
    )
    assert (
        "MRI-level evaluation is required to close RED"
        in packet["final_output"]["concise_recommendation"]
    )
    assert (
        "Deterministic public MVP scaffold; not medical advice or a diagnosis."
        in packet["final_output"]["caveats"]
    )


def test_wirecard_mvp_packet_holds_red_open_until_cash_verification() -> None:
    packet = build_nepsis_mvp_packet(case_id="wirecard")
    hypotheses = {
        hypothesis["id"]: hypothesis
        for hypothesis in packet["blue_channel"]["hypotheses"]
    }

    assert (
        packet["red_channel"]["active_hazards"][0]["id"]
        == "unverifiable_cash_must_not_miss"
    )
    assert packet["red_channel"]["escalation_required"] is True
    assert (
        "independent bank or custodian confirmation"
        in packet["red_channel"]["missing_discriminators"]
    )
    assert (
        hypotheses["reported_cash_valid"]["post_constraint_standing"]
        == "blocked_until_independently_verified"
    )
    assert (
        hypotheses["unverifiable_cash_gap"]["action_priority"] == "red-action-dominant"
    )
    assert (
        packet["contradiction_monitor"]["contradictions"][0]["id"]
        == "authority_assurance_vs_unverified_cash"
    )
    assert packet["non_quiescence"]["wrong_manifold_possible"] is True
    assert (
        "independently verifiable bank or custodian evidence"
        in packet["final_output"]["concise_recommendation"]
    )
    assert (
        "Deterministic public MVP scaffold; not financial, accounting, or legal advice."
        in packet["final_output"]["caveats"]
    )
