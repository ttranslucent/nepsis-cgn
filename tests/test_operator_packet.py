from __future__ import annotations

import json

import pytest

from nepsis_cgn.api.operator_packet import (
    abandon_packet,
    commit_iteration,
    lock_frame,
    lock_report,
    run_report,
    set_threshold_decision,
    start_operator_packet,
)


def _operator_frame() -> dict[str, object]:
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


def _report_interpretation() -> dict[str, object]:
    return {
        "report_text": "obs: critical signal present\nobs: no policy violation",
        "evidence_count": 2,
        "report_synced": True,
        "contradictions_status": "none_identified",
        "contradictions_note": "",
        "contradiction_density": 0.0,
    }


def test_stateless_operator_packet_valid_flow_commits_and_cycles() -> None:
    packet = start_operator_packet()

    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    reported = run_report(
        packet=locked,
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_report_interpretation(),
    )
    report_locked = lock_report(packet=reported)
    threshold = set_threshold_decision(
        packet=report_locked,
        decision="hold",
        hold_reason="Collect one additional discriminator before recommendation.",
    )
    committed = commit_iteration(
        packet=threshold,
        carry_forward_frame={
            "text": "Continue escalation assessment after the next discriminator.",
            "rationale_for_change": "Carry forward held threshold decision.",
        },
    )

    assert committed["schema_id"] == "nepsis.operator_packet"
    assert committed["schema_version"] == "2.1.0"
    assert committed["integrity"]["seal_version"] == "hmac-sha256:v1"
    assert committed["integrity"]["seal"]
    assert committed["phase"] == "frame_draft"
    assert committed["legal_next_tools"] == ["start_operator_packet", "lock_frame", "abandon_packet"]
    assert committed["audit_trace"] == []
    assert committed["last_commit_packet"]["schema_id"] == "nepsis.operator_audit_packet"
    assert committed["last_commit_packet"]["phase_events"] == [
        "LOCK_FRAME",
        "RUN_REPORT",
        "LOCK_REPORT",
        "SET_THRESHOLD_DECISION",
        "COMMIT_ITERATION",
    ]
    assert committed["frame"]["text"].startswith("Continue escalation")


def test_stateless_operator_packet_rejects_report_before_frame_lock() -> None:
    packet = start_operator_packet()

    result = run_report(
        packet=packet,
        report_text="obs: critical signal present",
        sign={"critical_signal": True, "policy_violation": False},
    )

    assert result["schema_id"] == "nepsis.phase_rejection"
    assert result["attempted_tool"] == "run_report"
    assert result["current_phase"] == "frame_draft"
    assert result["legal_next_tools"] == ["start_operator_packet", "lock_frame", "abandon_packet"]


def test_stateless_operator_packet_rejects_commit_before_threshold() -> None:
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    reported = run_report(
        packet=locked,
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_report_interpretation(),
    )
    report_locked = lock_report(packet=reported)

    result = commit_iteration(packet=report_locked)

    assert result["schema_id"] == "nepsis.phase_rejection"
    assert result["attempted_tool"] == "commit_iteration"
    assert result["current_phase"] == "report_locked"
    assert result["failed_precondition"] == "threshold_decision_required"


def test_stateless_operator_packet_rejects_commit_when_trace_does_not_prove_gates() -> None:
    packet = start_operator_packet()
    packet["phase"] = "threshold_set"
    packet["audit_trace"] = []

    result = commit_iteration(packet=packet)

    assert result["schema_id"] == "nepsis.phase_rejection"
    assert result["attempted_tool"] == "commit_iteration"
    assert result["current_phase"] == "threshold_set"
    assert result["failed_precondition"] == "audit_trace_required"
    assert result["missing"] == ["LOCK_FRAME", "RUN_REPORT", "LOCK_REPORT", "SET_THRESHOLD_DECISION"]


def test_serialized_operator_packet_continues_without_server_memory() -> None:
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    restored = json.loads(json.dumps(locked))

    reported = run_report(
        packet=restored,
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_report_interpretation(),
    )

    assert reported["schema_id"] == "nepsis.operator_packet"
    assert reported["phase"] == "report_evaluated"
    assert [entry["event"] for entry in reported["audit_trace"]] == ["LOCK_FRAME", "RUN_REPORT"]


def test_stateless_operator_packet_seals_output_and_accepts_valid_sealed_flow(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-packet-seal-secret")
    packet = start_operator_packet()

    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    reported = run_report(
        packet=locked,
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_report_interpretation(),
    )

    assert packet["integrity"]["seal_version"] == "hmac-sha256:v1"
    assert locked["integrity"]["counter"] == 1
    assert reported["integrity"]["counter"] == 2
    assert reported["schema_id"] == "nepsis.operator_packet"
    assert reported["phase"] == "report_evaluated"


def test_stateless_operator_packet_rejects_tampered_seal(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-packet-seal-secret")
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    locked["phase"] = "threshold_set"

    with pytest.raises(ValueError, match="integrity"):
        run_report(
            packet=locked,
            report_text="obs: critical signal present",
            sign={"critical_signal": True, "policy_violation": False},
        )


def test_stateless_operator_packet_rejects_trace_over_configured_cap(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-packet-seal-secret")
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_MAX_TRACE_EVENTS", "1")
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    reported = run_report(
        packet=locked,
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_report_interpretation(),
    )

    with pytest.raises(ValueError, match="audit_trace"):
        lock_report(packet=reported)


def test_operator_packet_requires_configured_seal_secret_in_operator_mode(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", raising=False)
    monkeypatch.setenv("NEPSIS_DEPLOYMENT_MODE", "operator")

    with pytest.raises(ValueError, match="NEPSIS_OPERATOR_PACKET_SEAL_SECRET"):
        start_operator_packet()


def test_stateless_operator_packet_abandon_returns_noncommitted_fragment() -> None:
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )

    abandoned = abandon_packet(packet=locked, reason="Frame was too broad.")

    assert abandoned["schema_id"] == "nepsis.operator_packet"
    assert abandoned["phase"] == "frame_draft"
    assert abandoned["audit_trace"] == []
    assert abandoned["last_abandoned_packet"]["schema_id"] == "nepsis.operator_abandoned_loop"
    assert abandoned["last_abandoned_packet"]["reason"] == "Frame was too broad."
