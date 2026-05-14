from __future__ import annotations

from nepsis_cgn.core.mvp import MVP_PACKET_SCHEMA_ID, build_nepsis_mvp_packet


MINIMUM_PACKET_FIELDS = {
    "case_id",
    "input_text",
    "observations",
    "constraints",
    "red_channel",
    "blue_channel",
    "contradiction_monitor",
    "denominator_collapse",
    "voronoi_commitment",
    "state_feedback",
    "non_quiescence",
    "still",
    "zeroback",
    "audit_trace",
    "final_output",
}


def test_jailing_mvp_packet_preserves_constraint_and_retessellates() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")

    assert packet["schema_id"] == MVP_PACKET_SCHEMA_ID
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
    assert packet["still"]["audit_events"]
    assert packet["zeroback"]["triggered"] is True
    assert packet["state_feedback"]["predicted_next_state"]["failure_conditions"]
    assert packet["state_feedback"]["loop_decision"]["status"] == "retessellate"
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


def test_clinical_mvp_packet_holds_blue_inside_red_boundary() -> None:
    packet = build_nepsis_mvp_packet(case_id="clinical")

    assert packet["red_channel"]["active_hazards"][0]["id"] == "cauda_equina_must_not_miss"
    assert packet["red_channel"]["escalation_required"] is True
    assert packet["blue_channel"]["weights"]["cauda_equina"] == "red-action-dominant"
    assert packet["non_quiescence"]["wrong_manifold_possible"] is True
    assert packet["still"]["checkpoints"][0]["trigger_status"] == "escalation_preserved"
    assert packet["still"]["commitment_readiness"]["status"] == "retessellate"
    assert packet["state_feedback"]["current_state"]["active_frame"] == (
        "high-consequence red-flag clinical uncertainty"
    )
    assert packet["state_feedback"]["predicted_next_state"]["failure_conditions"]
    assert packet["state_feedback"]["loop_decision"]["status"] == "retessellate"
    assert packet["state_feedback"]["loop_decision"]["next_observation_required"]
    assert "Do not close as benign spasm" in packet["final_output"]["concise_recommendation"]
