from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from nepsis_cgn.api.service import EngineApiService, _build_threshold_stage_packet


def _passing_operator_frame() -> dict[str, object]:
    return {
        "text": "Decide whether to escalate response.",
        "objective_type": "decide",
        "domain": "safety",
        "time_horizon": "short",
        "rationale_for_change": (
            "Red channel: avoid missing a catastrophic incident | "
            "Blue channel: protect users while minimizing disruption | "
            "Uncertainty: signal quality from the first report"
        ),
        "constraints_hard": ["No policy breach"],
        "constraints_soft": ["Minimize disruption"],
    }


def _passing_operator_report_context() -> dict[str, object]:
    return {
        "report_text": "obs: critical signal present\nobs: no policy violation",
        "evidence_count": 2,
        "contradictions_status": "none_identified",
        "contradictions_note": "",
        "contradiction_density": 0.0,
    }


def test_create_and_step_safety_session_with_governance() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    sid = created["session_id"]
    assert created["stage"] == "draft"
    assert created["family"] == "safety"

    step = svc.step_session(
        sid,
        sign={"critical_signal": True, "policy_violation": False},
        user_decision="continue_override",
        override_reason="Need one more check.",
    )
    assert step["stage"] == "evaluated"
    assert "governance" in step
    assert step["channel"]["space"] == "ruin"
    assert step["channel"]["decision_mode"] == "boundary"
    assert step["governance"]["user_decision"] == "continue_override"
    assert "iteration_packet" in step
    assert step["iteration_packet"]["schema_id"] == "nepsis.iteration_packet"
    assert step["iteration_packet"]["manifold"]["channel"]["space"] == "ruin"
    assert step["iteration_packet"]["meta"]["session_id"] == sid
    assert step["session"]["packet_count"] == 1


def test_no_cost_direct_red_latch_is_visible_and_blocks_commit_until_qualified_release() -> None:
    svc = EngineApiService()
    created = svc.create_session(family="safety")
    sid = created["session_id"]
    svc.step_session(
        sid,
        sign={
            "critical_signal": True,
            "policy_violation": False,
            "evidence_id": "direct-hazard",
        },
    )

    blocked = svc.step_session(
        sid,
        sign={
            "critical_signal": False,
            "policy_violation": False,
            "evidence_id": "ordinary-negative",
        },
        commit=True,
    )

    assert blocked["red_veto_active"] is True
    assert blocked["direct_ruin_criterion_active"] is True
    assert blocked["stage"] == "evaluated"
    assert blocked["iteration_packet"]["commit_request"]["admitted"] is False
    assert "direct_ruin_criterion_active" in blocked["iteration_packet"]["still"][
        "finalization_blockers"
    ]

    released = svc.step_session(
        sid,
        sign={
            "critical_signal": False,
            "policy_violation": False,
            "evidence_id": "independent-negative",
            "independent_observation": True,
        },
        commit=True,
    )
    assert released["red_veto_active"] is False
    assert released["direct_ruin_criterion_active"] is False
    assert released["stage"] == "committed"


def test_no_cost_operator_audit_inherits_authoritative_still_red_veto() -> None:
    svc = EngineApiService()
    locked = svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs=None,
    )
    result = svc.operator_run_report(
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={
            "critical_signal": True,
            "policy_violation": False,
            "evidence_id": "no-cost-operator-red",
        },
        interpretation=_passing_operator_report_context(),
    )

    latest_packet = result["step"]["iteration_packet"]
    assert "governance" not in latest_packet
    assert "direct_ruin_criterion_active" in latest_packet["still"][
        "finalization_blockers"
    ]
    threshold = svc.stage_audit_session(locked["session_id"])["threshold"][
        "packet"
    ]
    assert threshold["red_veto_active"] is True
    assert threshold["gate_crossed"] is True
    assert threshold["cost_review_required"] is False


def test_operator_run_report_before_lock_frame_returns_phase_rejection() -> None:
    svc = EngineApiService()
    state = svc.get_operator_session_state()

    result = svc.operator_run_report(
        report_text="obs: critical signal present",
        sign={"critical_signal": True, "policy_violation": False},
    )

    assert result["schema_id"] == "nepsis.phase_rejection"
    assert result["session_id"] == state["session_id"]
    assert result["attempted_tool"] == "run_report"
    assert result["current_phase"] == "frame_draft"
    assert result["failed_precondition"] == "lock_frame_required"
    assert result["legal_next_tools"] == ["get_session_state", "lock_frame", "abandon_session"]
    assert result["gate_status"] == "BLOCK"
    assert result["missing"]
    assert result["coach_prompts"]


def test_operator_lock_report_before_passing_interpretation_rejected() -> None:
    svc = EngineApiService()
    locked = svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )

    result = svc.operator_lock_report()

    assert locked["phase"] == "frame_locked"
    assert result["schema_id"] == "nepsis.phase_rejection"
    assert result["attempted_tool"] == "lock_report"
    assert result["current_phase"] == "frame_locked"
    assert result["failed_precondition"] == "run_report_required"
    assert result["legal_next_tools"] == ["get_session_state", "run_report", "abandon_session"]


def test_operator_report_can_rerun_from_report_evaluated() -> None:
    svc = EngineApiService()
    svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )

    first = svc.operator_run_report(
        report_text="obs: critical signal present",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_passing_operator_report_context(),
    )
    second = svc.operator_run_report(
        report_text="obs: critical signal not present",
        sign={"critical_signal": False, "policy_violation": False},
        interpretation={
            **_passing_operator_report_context(),
            "report_text": "obs: critical signal not present\nobs: no policy violation",
        },
    )

    assert first["phase"] == "report_evaluated"
    assert second["phase"] == "report_evaluated"
    assert second["step"]["session"]["steps"] == 2
    assert second["audit"]["interpretation"]["status"] == "PASS"


def test_operator_threshold_recommend_rejected_when_red_override_active() -> None:
    svc = EngineApiService()
    svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    svc.operator_run_report(
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_passing_operator_report_context(),
    )
    svc.operator_lock_report()

    result = svc.operator_set_threshold_decision(
        decision="recommend",
        hold_reason="",
    )

    assert result["schema_id"] == "nepsis.phase_rejection"
    assert result["attempted_tool"] == "set_threshold_decision"
    assert result["current_phase"] == "report_locked"
    assert result["failed_precondition"] == "threshold_gate_blocked"
    assert "set_threshold_decision" in result["legal_next_tools"]
    assert "RED veto enforcement" in result["missing"]


def test_operator_cost_review_requires_explicit_disposition_without_claiming_red_veto() -> None:
    svc = EngineApiService()
    svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 0.5, "c_fn": 9.5},
    )
    svc.operator_run_report(
        report_text="obs: critical signal absent\nobs: no policy violation",
        sign={"critical_signal": False, "policy_violation": False},
        interpretation={
            **_passing_operator_report_context(),
            "report_text": "obs: critical signal absent\nobs: no policy violation",
        },
    )
    svc.operator_lock_report()

    blocked = svc.operator_set_threshold_decision(decision="recommend")

    assert blocked["schema_id"] == "nepsis.phase_rejection"
    assert blocked["failed_precondition"] == "threshold_gate_blocked"
    assert "Cost-review disposition" in blocked["missing"]

    accepted = svc.operator_set_threshold_decision(
        decision="recommend",
        cost_review_acknowledged=True,
        cost_review_rationale=(
            "The bounded protective burden is proportionate while the low-risk path remains monitored."
        ),
    )
    assert accepted["phase"] == "threshold_set"

    committed = svc.operator_commit_iteration()
    assert committed["packet"]["red_override"]["active"] is False
    review = committed["packet"]["protective_action_review"]
    assert review["active"] is True
    assert review["cost_review_required"] is True
    assert review["cost_review_acknowledged"] is True
    assert "bounded protective burden" in review["cost_review_rationale"]
    checkpoint = svc._sessions[committed["session_id"]].seed_navigation_checkpoint
    assert checkpoint is not None
    assert checkpoint["red_state"]["direct_ruin_criterion_latched"] is False


def test_runtime_red_veto_cannot_be_cleared_by_false_request_or_compiler_gate() -> None:
    threshold = _build_threshold_stage_packet(
        {"gate_crossed": False},
        {
            "posterior": {"safety_blue": 0.43, "safety_red": 0.57},
            "governance": {
                "red_veto_active": True,
                "trigger_codes": ["RUIN_MASS_HIGH"],
                "theta": 0.1,
                "loss_treat": 0.9,
                "loss_notreat": 0.5,
                "metrics": {"p_bad": 0.05, "ruin_mass": 0.57},
            },
        },
        interpretation_context={
            "case_reasoning": {
                "threshold_decision": {"gate_crossed": False},
            }
        },
    )

    assert threshold["gate_crossed"] is True


def test_operator_commit_iteration_emits_audit_packet_and_cycles_phase() -> None:
    svc = EngineApiService()
    svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    svc.operator_run_report(
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_passing_operator_report_context(),
    )
    svc.operator_lock_report()
    threshold = svc.operator_set_threshold_decision(
        decision="hold",
        hold_reason="Collect one additional discriminator before recommendation.",
    )

    committed = svc.operator_commit_iteration(
        carry_forward_frame={
            "text": "Continue escalation assessment after the next discriminator.",
            "rationale_for_change": "Carry forward held threshold decision.",
        },
    )

    assert threshold["phase"] == "threshold_set"
    assert committed["phase"] == "frame_draft"
    assert committed["packet"]["schema_id"] == "nepsis.operator_audit_packet"
    assert committed["packet"]["phase_events"] == [
        "LOCK_FRAME",
        "RUN_REPORT",
        "LOCK_REPORT",
        "SET_THRESHOLD_DECISION",
        "COMMIT_ITERATION",
    ]
    assert committed["packet"]["threshold"]["decision"] == "hold"
    assert committed["packet"]["final_frame"]["text"].startswith("Continue escalation")
    assert svc.get_operator_session_state()["phase"] == "frame_draft"


def test_operator_packet_lineage_continues_across_live_loops() -> None:
    svc = EngineApiService()
    svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    first = svc.operator_run_report(
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={
            "critical_signal": True,
            "policy_violation": False,
            "evidence_id": "loop-one-red",
        },
        interpretation=_passing_operator_report_context(),
    )
    first_packet = first["step"]["iteration_packet"]
    svc.operator_lock_report()
    svc.operator_set_threshold_decision(
        decision="hold",
        hold_reason="Collect an independent discriminator.",
    )
    svc.operator_commit_iteration()

    svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    second = svc.operator_run_report(
        report_text="obs: critical signal absent\nobs: no policy violation",
        sign={
            "critical_signal": False,
            "policy_violation": False,
            "evidence_id": "loop-two-observation",
        },
        interpretation={
            **_passing_operator_report_context(),
            "report_text": "obs: critical signal absent\nobs: no policy violation",
        },
    )
    second_meta = second["step"]["iteration_packet"]["meta"]

    assert second_meta["iteration"] == 1
    assert second_meta["parent_packet_id"] == first_packet["meta"]["packet_id"]


def test_operator_red_checkpoint_survives_restart_and_qualified_release(
    tmp_path,
) -> None:
    store_path = tmp_path / "operator-red-checkpoint.json"
    svc = EngineApiService(store_path=str(store_path))
    locked = svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    sid = locked["session_id"]
    first = svc.operator_run_report(
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={
            "critical_signal": True,
            "policy_violation": False,
            "evidence_id": "restart-red",
        },
        interpretation=_passing_operator_report_context(),
    )
    first_packet = first["step"]["iteration_packet"]
    svc.operator_lock_report()
    svc.operator_set_threshold_decision(
        decision="hold",
        hold_reason="Await an independent negative observation.",
    )
    svc.operator_commit_iteration()
    retained_packets = svc.get_packets(sid)["packets"]
    assert svc._sessions[sid].actions == []
    assert svc._sessions[sid].steps == 0
    assert svc._sessions[sid].navigation.direct_ruin_criterion_active is True

    restored = EngineApiService(store_path=str(store_path))
    assert restored.get_packets(sid)["packets"] == retained_packets
    assert restored.get_session(sid)["operator_phase"] == "frame_draft"
    assert restored._sessions[sid].navigation.direct_ruin_criterion_active is True

    restored.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    ordinary = restored.operator_run_report(
        report_text="obs: critical signal absent\nobs: no policy violation",
        sign={
            "critical_signal": False,
            "policy_violation": False,
            "evidence_id": "ordinary-negative",
        },
        interpretation={
            **_passing_operator_report_context(),
            "report_text": "obs: critical signal absent\nobs: no policy violation",
        },
    )
    ordinary_step = ordinary["step"]
    assert ordinary_step["direct_ruin_criterion_active"] is True
    assert ordinary_step["red_veto_active"] is True
    ordinary_meta = ordinary_step["iteration_packet"]["meta"]
    assert ordinary_meta["iteration"] == 1
    assert ordinary_meta["parent_packet_id"] == first_packet["meta"]["packet_id"]

    qualified = restored.operator_run_report(
        report_text="obs: independent critical signal assessment is negative",
        sign={
            "critical_signal": False,
            "policy_violation": False,
            "evidence_id": "qualified-independent-negative",
            "independent_observation": True,
        },
        interpretation={
            **_passing_operator_report_context(),
            "report_text": "obs: independent critical signal assessment is negative",
        },
    )
    assert qualified["step"]["direct_ruin_criterion_active"] is False


@pytest.mark.parametrize("suffix", [".json", ".db"])
def test_restore_rejects_tampered_operator_red_checkpoint(
    tmp_path,
    monkeypatch,
    suffix,
) -> None:
    monkeypatch.delenv("NEPSIS_API_DATA_KEY", raising=False)
    store_path = tmp_path / f"operator-checkpoint-tamper{suffix}"
    svc = EngineApiService(store_path=str(store_path))
    locked = svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    sid = locked["session_id"]
    report = svc.operator_run_report(
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={
            "critical_signal": True,
            "policy_violation": False,
            "evidence_id": "tamper-red",
        },
        interpretation=_passing_operator_report_context(),
    )
    assert report["step"]["direct_ruin_criterion_active"] is True
    svc.operator_lock_report()
    svc.operator_set_threshold_decision(
        decision="hold",
        hold_reason="Retain the RED boundary pending a discriminator.",
    )
    svc.operator_commit_iteration()
    checkpoint = svc._sessions[sid].seed_navigation_checkpoint
    assert checkpoint is not None
    assert checkpoint["red_state"]["direct_ruin_criterion_latched"] is True

    if suffix == ".json":
        stored = json.loads(store_path.read_text(encoding="utf-8"))
        stored_checkpoint = stored["sessions"][0]["seed_navigation_checkpoint"]
        stored_checkpoint["red_state"]["direct_ruin_criterion_latched"] = False
        store_path.write_text(json.dumps(stored), encoding="utf-8")
    else:
        with sqlite3.connect(store_path) as conn:
            raw_checkpoint = conn.execute(
                "SELECT seed_navigation_checkpoint_json FROM engine_sessions "
                "WHERE session_id = ?",
                (sid,),
            ).fetchone()[0]
            stored_checkpoint = json.loads(raw_checkpoint)
            stored_checkpoint["red_state"]["direct_ruin_criterion_latched"] = False
            conn.execute(
                "UPDATE engine_sessions SET seed_navigation_checkpoint_json = ? "
                "WHERE session_id = ?",
                (json.dumps(stored_checkpoint), sid),
            )

    with pytest.raises(ValueError, match="failed integrity validation"):
        EngineApiService(store_path=str(store_path))


@pytest.mark.parametrize("suffix", [".json", ".db"])
def test_restore_rejects_tampered_operator_audit_packet(
    tmp_path,
    monkeypatch,
    suffix,
) -> None:
    monkeypatch.delenv("NEPSIS_API_DATA_KEY", raising=False)
    store_path = tmp_path / f"operator-audit-tamper{suffix}"
    svc = EngineApiService(store_path=str(store_path))
    locked = svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    sid = locked["session_id"]
    svc.operator_run_report(
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={
            "critical_signal": True,
            "policy_violation": False,
            "evidence_id": "audit-tamper-red",
        },
        interpretation=_passing_operator_report_context(),
    )
    svc.operator_lock_report()
    svc.operator_set_threshold_decision(
        decision="hold",
        hold_reason="Retain the RED boundary pending independent evidence.",
    )
    committed = svc.operator_commit_iteration()
    assert committed["packet"]["threshold"]["decision"] == "hold"
    assert committed["packet"]["red_override"]["active"] is True

    if suffix == ".json":
        stored = json.loads(store_path.read_text(encoding="utf-8"))
        packets = stored["sessions"][0]["packets"]
        audit_packet = next(
            packet
            for packet in packets
            if packet.get("schema_id") == "nepsis.operator_audit_packet"
        )
        audit_packet["threshold"]["decision"] = "recommend"
        audit_packet["red_override"]["active"] = False
        store_path.write_text(json.dumps(stored), encoding="utf-8")
    else:
        with sqlite3.connect(store_path) as conn:
            raw_packets = conn.execute(
                "SELECT packets_json FROM engine_sessions WHERE session_id = ?",
                (sid,),
            ).fetchone()[0]
            packets = json.loads(raw_packets)
            audit_packet = next(
                packet
                for packet in packets
                if packet.get("schema_id") == "nepsis.operator_audit_packet"
            )
            audit_packet["threshold"]["decision"] = "recommend"
            audit_packet["red_override"]["active"] = False
            conn.execute(
                "UPDATE engine_sessions SET packets_json = ? WHERE session_id = ?",
                (json.dumps(packets), sid),
            )

    with pytest.raises(
        ValueError,
        match="packet artifacts failed integrity validation",
    ):
        EngineApiService(store_path=str(store_path))


def test_operator_red_capture_dwell_survives_restart_and_reframe_releases_review(
    tmp_path,
) -> None:
    store_path = tmp_path / "operator-red-dwell.json"
    svc = EngineApiService(store_path=str(store_path))
    locked = svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    sid = locked["session_id"]
    for index in range(2):
        result = svc.operator_run_report(
            report_text="obs: critical signal present\nobs: no policy violation",
            sign={
                "critical_signal": True,
                "policy_violation": False,
                "evidence_id": f"repeated-red-{index}",
            },
            interpretation=_passing_operator_report_context(),
        )
        assert result["step"]["governance"]["posture"] == "red_override"
    svc.operator_lock_report()
    svc.operator_set_threshold_decision(
        decision="hold",
        hold_reason="Review whether the repeated RED signal still applies.",
    )
    svc.operator_commit_iteration()
    checkpoint = svc._sessions[sid].seed_navigation_checkpoint
    assert checkpoint is not None
    assert checkpoint["red_state"]["red_override_dwell_iters"] == 2

    restored = EngineApiService(store_path=str(store_path))
    restored.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    review = restored.operator_run_report(
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={
            "critical_signal": True,
            "policy_violation": False,
            "evidence_id": "repeated-red-2",
        },
        interpretation=_passing_operator_report_context(),
    )
    assert review["step"]["governance"]["posture"] == "red_review"
    assert "RED_CAPTURE_REVIEW" in review["step"]["governance"]["trigger_codes"]

    restored.operator_lock_report()
    restored.operator_set_threshold_decision(
        decision="hold",
        hold_reason="Substantively narrow the frame before another review.",
    )
    restored.operator_commit_iteration(
        carry_forward_frame={
            "text": "Assess only whether the repeated signal applies to this bounded action.",
            "rationale_for_change": "Narrow RED applicability after explicit capture review.",
        }
    )
    transitioned = restored._sessions[sid].seed_navigation_checkpoint
    assert transitioned is not None
    assert transitioned["red_state"]["direct_ruin_criterion_latched"] is True
    assert transitioned["red_state"]["red_capture_review_active"] is False
    assert transitioned["red_state"]["red_override_dwell_iters"] == 0


def test_operator_abandon_session_emits_fragment_and_starts_fresh_session() -> None:
    svc = EngineApiService()
    original = svc.operator_lock_frame(
        family="safety",
        frame=_passing_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )

    abandoned = svc.operator_abandon_session(reason="Frame was too broad.")
    state = svc.get_operator_session_state()

    assert abandoned["packet"]["schema_id"] == "nepsis.operator_abandoned_loop"
    assert abandoned["packet"]["session_id"] == original["session_id"]
    assert abandoned["packet"]["reason"] == "Frame was too broad."
    assert abandoned["phase"] == "frame_draft"
    assert state["phase"] == "frame_draft"
    assert state["session_id"] != original["session_id"]


def test_session_owner_limits_cross_user_access() -> None:
    svc = EngineApiService()
    created = svc.create_session(family="safety", owner_id="Alice@Example.com")
    sid = created["session_id"]

    assert created["owner_id"] == "alice@example.com"
    assert svc.get_session(sid, owner_id="alice@example.com")["session_id"] == sid
    assert svc.get_session(sid)["session_id"] == sid
    assert svc.list_sessions(owner_id="alice@example.com")["pagination"]["total"] == 1
    assert svc.list_sessions(owner_id="bob@example.com")["pagination"]["total"] == 0

    with pytest.raises(PermissionError):
        svc.get_session(sid, owner_id="bob@example.com")

    with pytest.raises(PermissionError):
        svc.step_session(
            sid,
            sign={"critical_signal": True, "policy_violation": False},
            owner_id="bob@example.com",
        )


def test_sqlite_store_owner_lookup_rejects_sql_like_owner_input(tmp_path) -> None:
    db_path = tmp_path / "engine_sessions.db"
    svc = EngineApiService(store_path=str(db_path))
    created = svc.create_session(family="safety", owner_id="alice@example.com")
    sid = created["session_id"]
    svc.create_session(family="safety", owner_id="bob@example.com")

    restored = EngineApiService(store_path=str(db_path))
    injected_owner = "alice@example.com' OR '1'='1"

    assert restored.list_sessions(owner_id=injected_owner)["pagination"]["total"] == 0
    with pytest.raises(PermissionError):
        restored.get_session(sid, owner_id=injected_owner)


def test_reframe_increments_frame_version() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        frame={"text": "Initial frame for safety reasoning."},
    )
    sid = created["session_id"]
    frame_before = created["frame"]
    assert frame_before["frame_version"] == 1

    reframed = svc.reframe_session(
        sid,
        frame={
            "text": "Refined frame after contradiction review.",
            "rationale_for_change": "ABDUCT promoted",
        },
    )
    assert reframed["frame"]["frame_version"] == 2
    assert reframed["frame"]["frame_id"] == frame_before["frame_id"]


def test_reframe_tracks_lineage_branch_and_parent_frame() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        frame={"text": "Initial frame for lineage"},
    )
    sid = created["session_id"]
    assert created["lineage_version"] == 1
    assert created["branch_id"].endswith("-b1")
    assert created["parent_frame_id"] is None
    parent_ref = created["frame_ref"]
    assert isinstance(parent_ref, str) and parent_ref

    reframed = svc.reframe_session(
        sid,
        frame={"text": "Lineage update frame"},
        branch_id="test-branch-b2",
        parent_frame_id=parent_ref,
    )
    assert reframed["lineage_version"] == 2
    assert reframed["branch_id"] == "test-branch-b2"
    assert reframed["parent_frame_id"] == parent_ref

    summary = svc.get_session(sid)
    assert summary["lineage_version"] == 2
    assert summary["branch_id"] == "test-branch-b2"
    assert summary["parent_frame_id"] == parent_ref


def test_stage_audit_defaults_show_blocked_contracts() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        frame={"text": "Initial question only"},
    )
    sid = created["session_id"]

    audit = svc.stage_audit_session(sid)
    assert audit["policy"]["name"] == "nepsis_cgn.stage_audit"
    assert audit["policy"]["version"] == "2026-03-10"
    assert audit["frame"]["status"] == "BLOCK"
    assert audit["interpretation"]["status"] == "BLOCK"
    assert audit["threshold"]["status"] == "BLOCK"
    assert isinstance(audit["frame"]["coach"]["prompts"], list)


def test_stage_audit_accepts_context_and_can_pass_all_stages() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={
            "text": "Assess whether to escalate.",
            "time_horizon": "short",
            "constraints_hard": ["No policy breach"],
            "constraints_soft": ["Keep response latency low"],
            "rationale_for_change": "Red channel: avoid catastrophic miss | Blue channel: optimize utility | Uncertainty: signal quality",
        },
    )
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True, "policy_violation": False})

    audit = svc.stage_audit_session(
        sid,
        context={
            "frame": {
                "problem_statement": "Assess whether to escalate now.",
                "catastrophic_outcome": "Miss a catastrophic event.",
                "optimization_goal": "Maximize safety while minimizing disruption.",
                "decision_horizon": "short",
                "key_uncertainty": "Signal reliability from first report.",
                "hard_constraints": ["No policy breach"],
                "soft_constraints": ["Keep response latency low"],
            },
            "interpretation": {
                "report_text": "obs: critical signal present\nobs: no policy violation",
                "evidence_count": 2,
                "report_synced": True,
                "contradictions_status": "none_identified",
                "contradictions_note": "",
            },
            "threshold": {
                "decision": "hold",
                "hold_reason": "Need one additional discriminator before recommendation.",
            },
        },
    )
    assert audit["frame"]["status"] == "PASS"
    assert audit["interpretation"]["status"] == "PASS"
    assert audit["threshold"]["status"] == "PASS"
    assert audit["policy"]["name"] == "nepsis_cgn.stage_audit"
    assert audit["threshold"]["coach"]["summary"].startswith("Threshold contract")


def test_stage_audit_can_persist_gate_context_for_canonical_reads() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={
            "text": "Assess whether to escalate.",
            "time_horizon": "short",
            "constraints_hard": ["No policy breach"],
            "constraints_soft": ["Keep response latency low"],
            "rationale_for_change": "Red channel: avoid catastrophic miss | Blue channel: optimize utility | Uncertainty: signal quality",
        },
    )
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True, "policy_violation": False})

    context = {
        "frame": {
            "problem_statement": "Assess whether to escalate now.",
            "catastrophic_outcome": "Miss a catastrophic event.",
            "optimization_goal": "Maximize safety while minimizing disruption.",
            "decision_horizon": "short",
            "key_uncertainty": "Signal reliability from first report.",
            "hard_constraints": ["No policy breach"],
            "soft_constraints": ["Keep response latency low"],
        },
        "interpretation": {
            "report_text": "obs: critical signal present\nobs: no policy violation",
            "evidence_count": 2,
            "report_synced": True,
            "contradictions_status": "none_identified",
            "contradictions_note": "",
        },
        "threshold": {
            "decision": "hold",
            "hold_reason": "Need one additional discriminator before recommendation.",
        },
    }

    preview = svc.stage_audit_session(sid, context=context, persist_context=True)
    canonical = svc.stage_audit_session(sid)

    assert preview["threshold"]["status"] == "PASS"
    assert canonical["frame"]["status"] == "PASS"
    assert canonical["interpretation"]["status"] == "PASS"
    assert canonical["threshold"]["status"] == "PASS"
    assert canonical["source"]["context_applied"] is True
    assert canonical["source"]["context_source"] == "session"
    assert svc.get_session(sid)["workspace_state"]["stage_audit_context"]["threshold"]["decision"] == "hold"


def test_workspace_state_persists_in_json_store(tmp_path) -> None:
    store_path = tmp_path / "sessions.json"
    svc = EngineApiService(store_path=str(store_path))
    created = svc.create_session(family="safety", frame={"text": "Assess whether to escalate."})
    sid = created["session_id"]

    updated = svc.update_workspace_state(
        sid,
        workspace_state={
            "schema_version": "2026-05-19",
            "frame_locked": True,
            "report_locked": False,
            "stage_audit_context": {"frame": {"problem_statement": "Assess whether to escalate."}},
        },
    )

    assert updated["workspace_state"]["frame_locked"] is True
    restored = EngineApiService(store_path=str(store_path))
    assert restored.get_session(sid)["workspace_state"]["frame_locked"] is True


def test_stage_audit_workflow_blocks_and_unblocks_across_stages() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={
            "text": "Decide whether to escalate response.",
        },
    )
    sid = created["session_id"]

    frame_context = {
        "problem_statement": "Decide escalation now.",
        "catastrophic_outcome": "Miss a catastrophic incident.",
        "optimization_goal": "Protect safety while reducing unnecessary disruption.",
        "decision_horizon": "short",
        "key_uncertainty": "Signal quality from the first report.",
        "hard_constraints": ["No policy breach"],
        "soft_constraints": ["Minimize disruption"],
    }
    interpretation_context = {
        "report_text": "obs: critical signal present\nobs: no policy violation",
        "evidence_count": 2,
        "report_synced": True,
        "contradictions_status": "none_identified",
        "contradictions_note": "",
    }
    threshold_base = {
        "loss_treat": 1.0,
        "loss_not_treat": 9.0,
        "warning_level": "red",
        "gate_crossed": True,
        "recommendation": "escalate",
    }

    audit_initial = svc.stage_audit_session(sid)
    assert audit_initial["frame"]["status"] == "BLOCK"
    assert audit_initial["interpretation"]["status"] == "BLOCK"
    assert audit_initial["threshold"]["status"] == "BLOCK"

    audit_frame_ready = svc.stage_audit_session(
        sid,
        context={
            "frame": frame_context,
        },
    )
    assert audit_frame_ready["frame"]["status"] == "PASS"
    assert audit_frame_ready["interpretation"]["status"] == "BLOCK"
    assert audit_frame_ready["threshold"]["status"] == "BLOCK"

    svc.step_session(sid, sign={"critical_signal": True, "policy_violation": False})

    audit_missing_decision = svc.stage_audit_session(
        sid,
        context={
            "frame": frame_context,
            "interpretation": interpretation_context,
            "threshold": {
                **threshold_base,
                "decision": "undecided",
                "hold_reason": "",
            },
        },
    )
    assert audit_missing_decision["frame"]["status"] == "PASS"
    assert audit_missing_decision["interpretation"]["status"] == "PASS"
    assert audit_missing_decision["threshold"]["status"] == "BLOCK"
    threshold_checks_missing_decision = {
        check["key"]: check for check in audit_missing_decision["threshold"]["checks"]
    }
    assert threshold_checks_missing_decision["decision_declared"]["status"] == "block"

    audit_red_override = svc.stage_audit_session(
        sid,
        context={
            "frame": frame_context,
            "interpretation": interpretation_context,
            "threshold": {
                **threshold_base,
                "decision": "recommend",
                "hold_reason": "",
            },
        },
    )
    assert audit_red_override["threshold"]["status"] == "BLOCK"
    threshold_checks_red_override = {
        check["key"]: check for check in audit_red_override["threshold"]["checks"]
    }
    assert threshold_checks_red_override["red_override_enforced"]["status"] == "block"

    audit_hold_pass = svc.stage_audit_session(
        sid,
        context={
            "frame": frame_context,
            "interpretation": interpretation_context,
            "threshold": {
                **threshold_base,
                "decision": "hold",
                "hold_reason": "Collect one additional discriminator before recommendation.",
            },
        },
    )
    assert audit_hold_pass["frame"]["status"] == "PASS"
    assert audit_hold_pass["interpretation"]["status"] == "PASS"
    assert audit_hold_pass["threshold"]["status"] == "PASS"


def test_stage_audit_adversarial_vague_frame_blocks_contract() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        frame={"text": "Help?"},
    )
    sid = created["session_id"]

    audit = svc.stage_audit_session(
        sid,
        context={
            "frame": {
                "problem_statement": "Not sure, maybe this?",
            }
        },
    )
    assert audit["frame"]["status"] == "BLOCK"
    assert audit["interpretation"]["status"] == "BLOCK"
    assert audit["threshold"]["status"] == "BLOCK"

    checks = {check["key"]: check for check in audit["frame"]["checks"]}
    assert checks["problem_statement"]["status"] == "pass"
    assert checks["catastrophic_outcome"]["status"] == "block"
    assert checks["optimization_goal"]["status"] == "block"
    assert checks["decision_horizon"]["status"] == "block"
    assert checks["key_uncertainty"]["status"] == "block"
    assert checks["constraint_structure"]["status"] == "block"


def test_stage_audit_adversarial_contradiction_heavy_report_warns_interpretation() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={"text": "Decide escalation path."},
    )
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True, "policy_violation": False})

    audit = svc.stage_audit_session(
        sid,
        context={
            "frame": {
                "problem_statement": "Decide escalation now.",
                "catastrophic_outcome": "Miss critical incident.",
                "optimization_goal": "Protect users while reducing disruption.",
                "decision_horizon": "short",
                "key_uncertainty": "Signal quality from first report.",
                "hard_constraints": ["No policy breach"],
                "soft_constraints": ["Minimize disruption"],
            },
            "interpretation": {
                "report_text": (
                    "obs: signal strongly indicates escalation\n"
                    "obs: signal likely false positive\n"
                    "obs: team reports conflicting timelines"
                ),
                "evidence_count": 3,
                "report_synced": True,
                "contradictions_status": "declared",
                "contradictions_note": "Signal reliability and timeline evidence conflict.",
                "contradiction_density": 0.82,
            },
            "threshold": {
                "loss_treat": 1.0,
                "loss_not_treat": 9.0,
                "warning_level": "yellow",
                "gate_crossed": False,
                "recommendation": "hold",
                "decision": "hold",
                "hold_reason": "Gather one additional discriminator.",
            },
        },
    )
    assert audit["frame"]["status"] == "PASS"
    assert audit["interpretation"]["status"] == "WARN"

    checks = {check["key"]: check for check in audit["interpretation"]["checks"]}
    assert checks["report_text"]["status"] == "pass"
    assert checks["contradictions_declared"]["status"] == "pass"
    assert checks["contradiction_density"]["status"] == "warn"
    assert audit["interpretation"]["coach"]["status"] == "WARN"


def test_stage_audit_adversarial_forced_red_override_conflict_blocks_threshold() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={"text": "Decide escalation path."},
    )
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True, "policy_violation": False})

    audit = svc.stage_audit_session(
        sid,
        context={
            "frame": {
                "problem_statement": "Decide escalation now.",
                "catastrophic_outcome": "Miss critical incident.",
                "optimization_goal": "Protect users while reducing disruption.",
                "decision_horizon": "short",
                "key_uncertainty": "Signal quality from first report.",
                "hard_constraints": ["No policy breach"],
                "soft_constraints": ["Minimize disruption"],
            },
            "interpretation": {
                "report_text": "obs: critical signal present\nobs: no policy violation",
                "evidence_count": 2,
                "report_synced": True,
                "contradictions_status": "none_identified",
                "contradictions_note": "",
            },
            "threshold": {
                "loss_treat": 1.0,
                "loss_not_treat": 9.0,
                "warning_level": "red",
                "gate_crossed": True,
                "recommendation": "escalate",
                "decision": "recommend",
                "hold_reason": "",
            },
        },
    )
    assert audit["frame"]["status"] == "PASS"
    assert audit["interpretation"]["status"] == "PASS"
    assert audit["threshold"]["status"] == "BLOCK"

    checks = {check["key"]: check for check in audit["threshold"]["checks"]}
    assert checks["decision_declared"]["status"] == "pass"
    assert checks["red_override_enforced"]["status"] == "block"
    assert checks["red_override_enforced"]["detail"].startswith("RED veto active")


def test_packets_endpoint_tracks_history() -> None:
    svc = EngineApiService()
    created = svc.create_session(family="safety")
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True})
    svc.step_session(sid, sign={"critical_signal": False})
    packets = svc.get_packets(sid)
    assert packets["count"] == 2
    assert len(packets["packets"]) == 2
    assert packets["packets"][1]["meta"]["parent_packet_id"] == packets["packets"][0]["meta"]["packet_id"]


def test_invalid_sign_payload_raises_value_error() -> None:
    svc = EngineApiService()
    created = svc.create_session(family="clinical")
    sid = created["session_id"]
    with pytest.raises(ValueError):
        svc.step_session(sid, sign={"radicular_pain": True})


def test_string_booleans_are_parsed_safely() -> None:
    svc = EngineApiService()
    created = svc.create_session(family="safety")
    sid = created["session_id"]
    step = svc.step_session(
        sid,
        sign={"critical_signal": "false", "policy_violation": "false"},
    )
    assert step["manifold"] == "blue_channel"
    assert step["is_ruin"] is False


def test_invalid_boolean_string_raises_value_error() -> None:
    svc = EngineApiService()
    created = svc.create_session(family="safety")
    sid = created["session_id"]
    with pytest.raises(ValueError):
        svc.step_session(
            sid,
            sign={"critical_signal": "not-a-bool"},
        )


def test_delete_session_removes_from_registry() -> None:
    svc = EngineApiService()
    created = svc.create_session(family="safety")
    sid = created["session_id"]
    result = svc.delete_session(sid)
    assert result["deleted"] is True
    assert result["session_id"] == sid
    with pytest.raises(KeyError):
        svc.get_session(sid)


def test_sessions_persist_and_restore_from_disk(tmp_path) -> None:
    store_path = tmp_path / "engine_sessions.json"
    svc = EngineApiService(store_path=str(store_path))
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={"text": "Initial persisted frame"},
    )
    sid = created["session_id"]

    first = svc.step_session(sid, sign={"critical_signal": True})
    original_packet = first["iteration_packet"]
    svc.reframe_session(
        sid,
        frame={
            "text": "Persisted reframe",
            "rationale_for_change": "test restore",
        },
    )

    restored = EngineApiService(store_path=str(store_path))
    session = restored.get_session(sid)
    packets = restored.get_packets(sid)
    assert session["storage"] == "disk"
    assert session["steps"] == 1
    assert session["frame"]["frame_version"] == 2
    assert packets["count"] == 1
    assert session["governance_policy_version"] == created["governance_policy_version"]
    assert session["evidence_policy_version"] == created["evidence_policy_version"]
    assert session["manifest_digest"] == created["manifest_digest"]
    assert session["replay_contract_version"] == "nepsis.session_replay@0.3.0"
    assert packets["packets"][0]["meta"]["registry_version"] == session["manifest_digest"]
    assert packets["packets"][0] == original_packet

    continued = restored.step_session(
        sid,
        sign={"critical_signal": False, "policy_violation": False},
    )
    continued_meta = continued["iteration_packet"]["meta"]
    assert continued_meta["iteration"] == 1
    assert continued_meta["parent_packet_id"] == original_packet["meta"]["packet_id"]


@pytest.mark.parametrize("suffix", [".json", ".db"])
def test_empty_clinical_session_checkpoint_round_trips(tmp_path, suffix) -> None:
    store_path = tmp_path / f"empty-clinical{suffix}"
    svc = EngineApiService(store_path=str(store_path))
    created = svc.create_session(family="clinical")

    restored = EngineApiService(store_path=str(store_path))
    session = restored.get_session(created["session_id"])

    assert session["family"] == "clinical"
    assert session["steps"] == 0
    assert restored.get_packets(created["session_id"])["packets"] == []
    posterior = restored._sessions[created["session_id"]].navigation.manager.posterior()
    assert sum(posterior.values()) == pytest.approx(1.0)


def test_restore_rejects_semantically_tampered_packet(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_DATA_KEY", raising=False)
    store_path = tmp_path / "tampered-session.json"
    svc = EngineApiService(store_path=str(store_path))
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={"text": "Pinned replay frame"},
    )
    svc.step_session(
        created["session_id"],
        sign={"critical_signal": False, "policy_violation": False},
    )

    stored = json.loads(store_path.read_text(encoding="utf-8"))
    stored["sessions"][0]["packets"][0]["result"]["decision"] = "tampered"
    store_path.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(ValueError, match="packet artifacts failed integrity validation"):
        EngineApiService(store_path=str(store_path))


def test_calibration_payload_changes_governance_probability() -> None:
    svc = EngineApiService()
    low = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        governance_calibration={
            "prior_pi": 0.01,
            "intercept": -8.0,
            "slope": 1.0,
            "w_violation_pressure": 0.0,
            "w_ambiguity_pressure": 0.0,
            "w_contradiction_density": 0.0,
            "w_entropy": 0.0,
            "w_margin_collapse": 0.0,
        },
    )
    high = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        governance_calibration={
            "prior_pi": 0.5,
            "intercept": 8.0,
            "slope": 1.0,
            "w_violation_pressure": 0.0,
            "w_ambiguity_pressure": 0.0,
            "w_contradiction_density": 0.0,
            "w_entropy": 0.0,
            "w_margin_collapse": 0.0,
        },
    )
    low_step = svc.step_session(low["session_id"], sign={"critical_signal": False, "policy_violation": False})
    high_step = svc.step_session(high["session_id"], sign={"critical_signal": False, "policy_violation": False})
    assert "governance" in low_step
    assert "governance" in high_step
    assert low_step["governance"]["p_bad"] < high_step["governance"]["p_bad"]


def test_calibration_version_allowlist_enforced(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOWED_CALIBRATION_VERSIONS", "logit-v1")
    svc = EngineApiService()
    with pytest.raises(ValueError):
        svc.create_session(
            family="safety",
            governance_costs={"c_fp": 1, "c_fn": 9},
            governance_calibration={"version": "unknown-v2"},
        )


def test_default_calibration_uses_v2_without_uncertainty_as_badness() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        governance_calibration={},
    )

    calibration = svc._sessions[created["session_id"]].governance_calibration
    assert calibration is not None
    assert calibration.version == "logit-v2"
    assert calibration.w_ambiguity_pressure == 0.0
    assert calibration.w_contradiction_density == 0.0
    assert calibration.w_entropy == 0.0
    assert calibration.w_margin_collapse == 0.0


def test_explicit_v1_calibration_preserves_legacy_default_weights() -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        governance_calibration={"version": "logit-v1"},
    )

    calibration = svc._sessions[created["session_id"]].governance_calibration
    assert calibration is not None
    assert calibration.version == "logit-v1"
    assert calibration.w_ambiguity_pressure == 1.0
    assert calibration.w_contradiction_density == 0.8
    assert calibration.w_entropy == 0.4
    assert calibration.w_margin_collapse == 0.6


def test_purge_sessions_by_ttl_removes_only_old_sessions() -> None:
    svc = EngineApiService()
    old = svc.create_session(family="safety")
    new = svc.create_session(family="safety")

    old_id = old["session_id"]
    new_id = new["session_id"]
    svc._sessions[old_id].created_at = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    svc._sessions[new_id].created_at = datetime.now(timezone.utc).isoformat()

    result = svc.purge_sessions(max_age_seconds=60 * 60 * 24)
    assert result["purged_count"] == 1
    assert any(item["session_id"] == old_id for item in result["purged_sessions"])
    with pytest.raises(KeyError):
        svc.get_session(old_id)
    assert svc.get_session(new_id)["session_id"] == new_id


def test_purge_sessions_dry_run_does_not_delete() -> None:
    svc = EngineApiService()
    created = svc.create_session(family="safety")
    sid = created["session_id"]
    svc._sessions[sid].created_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    result = svc.purge_sessions(max_age_seconds=60, dry_run=True)
    assert result["purged_count"] == 1
    assert svc.get_session(sid)["session_id"] == sid


def test_sqlite_store_round_trip(tmp_path) -> None:
    db_path = tmp_path / "engine_sessions.db"
    svc = EngineApiService(store_path=str(db_path))
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    sid = created["session_id"]
    original = svc.step_session(sid, sign={"critical_signal": True})[
        "iteration_packet"
    ]
    restored = EngineApiService(store_path=str(db_path))
    session = restored.get_session(sid)
    assert session["steps"] == 1
    assert session["storage"] == "disk"
    assert session["lineage_version"] >= 1
    assert isinstance(session["branch_id"], str)
    assert restored.get_packets(sid)["packets"] == [original]


def test_corrupt_json_store_is_recovered(tmp_path) -> None:
    store_path = tmp_path / "engine_sessions.json"
    store_path.write_text("{not-json", encoding="utf-8")
    svc = EngineApiService(store_path=str(store_path))
    assert svc.list_sessions()["sessions"] == []
    backups = list(tmp_path.glob("engine_sessions.json.corrupt.*"))
    assert backups


def test_list_sessions_and_packets_support_pagination() -> None:
    svc = EngineApiService()
    a = svc.create_session(family="safety")
    b = svc.create_session(family="safety")
    c = svc.create_session(family="safety")
    del b, c
    sid = a["session_id"]
    svc.step_session(sid, sign={"critical_signal": True})
    svc.step_session(sid, sign={"critical_signal": False})

    page = svc.list_sessions(limit=2, offset=1)
    assert page["pagination"]["limit"] == 2
    assert page["pagination"]["offset"] == 1
    assert len(page["sessions"]) >= 1

    packets_page = svc.get_packets(sid, limit=1, offset=1)
    assert packets_page["pagination"]["limit"] == 1
    assert packets_page["pagination"]["offset"] == 1
    assert len(packets_page["packets"]) == 1
