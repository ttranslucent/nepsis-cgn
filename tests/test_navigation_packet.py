from __future__ import annotations

import pytest

from nepsis_cgn.core import InterpretantManager, NavigationController
from nepsis_cgn.core.governance import GovernanceCosts
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

    committed = nav.step(SafetySign(critical_signal=True), commit=True)
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
