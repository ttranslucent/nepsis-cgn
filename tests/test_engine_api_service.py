from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from nepsis_cgn.api.service import EngineApiService


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
    assert step["governance"]["user_decision"] == "continue_override"
    assert "iteration_packet" in step
    assert step["iteration_packet"]["schema_id"] == "nepsis.iteration_packet"
    assert step["iteration_packet"]["meta"]["session_id"] == sid
    assert step["session"]["packet_count"] == 1


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
    assert checks["red_override_enforced"]["detail"].startswith("Red gate crossed")


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

    svc.step_session(sid, sign={"critical_signal": True})
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
    svc.step_session(sid, sign={"critical_signal": True})
    restored = EngineApiService(store_path=str(db_path))
    session = restored.get_session(sid)
    assert session["steps"] == 1
    assert session["storage"] == "disk"
    assert session["lineage_version"] >= 1
    assert isinstance(session["branch_id"], str)


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
