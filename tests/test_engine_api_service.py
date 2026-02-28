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
