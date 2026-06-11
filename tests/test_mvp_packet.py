from __future__ import annotations

import pytest

from nepsis_cgn.core.mvp import MVP_PACKET_SCHEMA_ID, MVP_PACKET_SCHEMA_VERSION, build_nepsis_mvp_packet


MINIMUM_PACKET_FIELDS = {
    "schema_id",
    "schema_version",
    "packet_id",
    "created_at",
    "case_id",
    "input_text",
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


def test_mvp_packet_top_level_schema_is_stable() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")

    assert set(packet) == MINIMUM_PACKET_FIELDS


def test_jailing_mvp_packet_preserves_constraint_and_retessellates() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")

    assert packet["schema_id"] == MVP_PACKET_SCHEMA_ID
    assert packet["schema_version"] == MVP_PACKET_SCHEMA_VERSION == "0.1.7"
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
    assert "retessellate" in packet["still"]["commitment_readiness"]["co_trigger_statuses"]
    assert packet["still"]["audit_events"]
    assert packet["zeroback"]["triggered"] is True
    assert packet["retessellation_state"]["status"] == "completed_in_packet"
    assert packet["retessellation_state"]["trigger_event_order"] == 8
    assert packet["retessellation_state"]["completed_event_order"] == 9
    assert "next-cycle source-token verification" in packet["retessellation_state"]["remaining_obligation"]
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
    packet = build_nepsis_mvp_packet(case_id="clinical")
    blue_channel = packet["blue_channel"]
    axes = blue_channel["evaluation_axes"]
    hypotheses = {hypothesis["id"]: hypothesis for hypothesis in blue_channel["hypotheses"]}

    assert "weights" not in blue_channel
    assert hypotheses["benign_radicular_spasm"]["likelihood"] == "medium_support"
    assert hypotheses["benign_radicular_spasm"]["post_constraint_standing"] == "plausible_but_red_bounded"
    assert hypotheses["benign_radicular_spasm"]["action_priority"] == "bounded_until_red_flags_resolved"
    assert hypotheses["cauda_equina"]["likelihood"] == "uncertain_support"
    assert hypotheses["cauda_equina"]["post_constraint_standing"] == "action_dominant_by_consequence"
    assert hypotheses["cauda_equina"]["action_priority"] == "red-action-dominant"
    assert axes["support"]["by_hypothesis"]["benign_radicular_spasm"] == "medium"
    assert axes["support"]["by_hypothesis"]["cauda_equina"] == "uncertain"
    assert axes["action_priority"]["by_hypothesis"]["cauda_equina"] == "red-action-dominant"
    assert "red-action-dominant" not in axes["support"]["by_hypothesis"].values()


def test_mvp_contradiction_density_declares_saturating_count_basis() -> None:
    jailing = build_nepsis_mvp_packet(case_id="jailing")
    clinical = build_nepsis_mvp_packet(case_id="clinical")
    clear = build_nepsis_mvp_packet(case_id="clinical", input_text="Clinical demo: radicular spasm only.")

    assert jailing["contradiction_monitor"]["contradiction_density"] == pytest.approx(2 / 3)
    assert clinical["contradiction_monitor"]["contradiction_density"] == pytest.approx(1 / 2)
    assert clear["contradiction_monitor"]["contradiction_density"] == 0.0

    for packet in (jailing, clinical, clear):
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
    assert jailing_monitor["density_channels"]["object"]["contradiction_density"] == pytest.approx(1 / 2)
    assert jailing_monitor["density_channels"]["object"]["resolved_count"] == 1
    assert jailing_monitor["density_channels"]["meta"]["resolved_count"] == 1


def test_mvp_jailing_packet_declares_support_constraint_and_limitations() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")
    hypotheses = {hypothesis["id"]: hypothesis for hypothesis in packet["blue_channel"]["hypotheses"]}

    assert hypotheses["constraint_preserving_token"]["likelihood"] == "high_support"
    assert hypotheses["constraint_preserving_token"]["post_constraint_standing"] == "dominant_after_red_constraint"
    assert hypotheses["constraint_preserving_token"]["action_priority"] == "commit_after_exact_token_match"
    assert hypotheses["plausible_word_collapse"]["likelihood"] == "surface_plausible_only"
    assert hypotheses["plausible_word_collapse"]["post_constraint_standing"] == "rejected_by_constraint"
    assert hypotheses["plausible_word_collapse"]["action_priority"] == "blocked_by_red_boundary"

    limitation_ids = {limitation["id"] for limitation in packet["demo_limitations"]}
    limitation_text = " ".join(limitation["limitation"] for limitation in packet["demo_limitations"])
    assert "source_token_corruption_not_detected" in limitation_ids
    assert "source token itself is corrupted" in limitation_text


def test_clinical_mvp_packet_holds_blue_inside_red_boundary() -> None:
    packet = build_nepsis_mvp_packet(case_id="clinical")

    assert packet["red_channel"]["active_hazards"][0]["id"] == "cauda_equina_must_not_miss"
    assert packet["red_channel"]["escalation_required"] is True
    assert packet["blue_channel"]["evaluation_axes"]["action_priority"]["by_hypothesis"]["cauda_equina"] == (
        "red-action-dominant"
    )
    assert packet["non_quiescence"]["wrong_manifold_possible"] is True
    assert packet["still"]["checkpoints"][0]["trigger_status"] == "escalation_preserved"
    assert packet["still"]["commitment_readiness"]["status"] == "retessellate"
    assert packet["retessellation_state"]["status"] == "completed_in_packet"
    assert packet["state_feedback"]["current_state"]["active_frame"] == (
        "high-consequence red-flag clinical uncertainty"
    )
    assert packet["state_feedback"]["predicted_next_state"]["failure_conditions"]
    assert packet["state_feedback"]["loop_decision"]["status"] == "pending_observation"
    assert packet["state_feedback"]["loop_decision"]["next_observation_required"]
    contradiction = packet["contradiction_monitor"]["contradictions"][0]
    assert contradiction["level"] == "action_threshold"
    assert contradiction["status"] == "open_pending_discriminators"
    assert packet["contradiction_monitor"]["density_channels"]["action_threshold"]["open_count"] == 1
    assert "Do not close as benign spasm" in packet["final_output"]["concise_recommendation"]
