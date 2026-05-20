from __future__ import annotations

import pytest

from nepsis_cgn.core.mvp import MVP_PACKET_SCHEMA_ID, build_nepsis_mvp_packet


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
    "voronoi_commitment",
    "state_feedback",
    "non_quiescence",
    "still",
    "zeroback",
    "audit_trace",
    "final_output",
}


def test_mvp_packet_top_level_schema_is_stable() -> None:
    packet = build_nepsis_mvp_packet(case_id="jailing")

    assert set(packet) == MINIMUM_PACKET_FIELDS


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


def test_mvp_blue_channel_separates_support_and_action_axes() -> None:
    packet = build_nepsis_mvp_packet(case_id="clinical")
    blue_channel = packet["blue_channel"]
    axes = blue_channel["evaluation_axes"]

    assert "weights" not in blue_channel
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
        assert basis["runtime_gate_input"] is False


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
    assert packet["state_feedback"]["current_state"]["active_frame"] == (
        "high-consequence red-flag clinical uncertainty"
    )
    assert packet["state_feedback"]["predicted_next_state"]["failure_conditions"]
    assert packet["state_feedback"]["loop_decision"]["status"] == "retessellate"
    assert packet["state_feedback"]["loop_decision"]["next_observation_required"]
    assert "Do not close as benign spasm" in packet["final_output"]["concise_recommendation"]
