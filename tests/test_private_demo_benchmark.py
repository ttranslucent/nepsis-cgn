from __future__ import annotations

from pathlib import Path

from scripts.run_private_demo_benchmark import load_suite, run_suite


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "data" / "private_demo_cases" / "authority_suppressed_red_channel.json"


def test_authority_suppressed_red_channel_suite_runs_all_cases() -> None:
    suite = load_suite(SUITE_PATH)

    report = run_suite(suite)

    assert report["schema_id"] == "nepsis.private_demo_benchmark_report"
    assert report["suite_id"] == "authority_suppressed_red_channel"
    assert report["summary"]["total_cases"] == 6
    assert report["summary"]["held_cases"] == 5
    assert report["summary"]["required_events_cases"] == 6
    assert report["summary"]["passing_cases"] == 6
    assert {case["domain"] for case in report["cases"]} == {"medical", "finance"}


def test_authority_suppression_cases_keep_red_open_under_authority_pushback() -> None:
    suite = load_suite(SUITE_PATH)

    report = run_suite(suite)

    open_cases = [case for case in report["cases"] if case["expected_red_status"] == "open"]

    for result in open_cases:
        assert result["compiler_valid"] is True
        assert result["compiler_red_status"] == "open"
        assert result["recommended_threshold_action"] == "escalate_red"
        assert result["runtime_red_veto_active"] is True
        assert result["required_events_present"] is True
        assert result["threshold_decision"] == "hold"
        assert result["operator_phase"] == "threshold_set"
        assert result["latest_audit_statuses"] == {
            "frame": "PASS",
            "interpretation": "PASS",
            "threshold": "PASS",
        }
        assert result["audit_events"] == [
            "LOCK_FRAME",
            "RUN_REPORT",
            "LOCK_REPORT",
            "SET_THRESHOLD_DECISION",
        ]


def test_true_closure_case_deescalates_instead_of_always_red() -> None:
    suite = load_suite(SUITE_PATH)

    report = run_suite(suite)
    closure = next(case for case in report["cases"] if case["expected_red_status"] == "closed")

    assert closure["compiler_valid"] is True
    assert closure["compiler_red_status"] == "closed"
    assert closure["recommended_threshold_action"] == "deescalate"
    assert closure["threshold_decision"] == "recommend"
    assert closure["threshold_recommendation"] == "deescalate"
    assert closure["threshold_recommendation"] != "escalate_red"
    assert closure["runtime_red_veto_active"] is False


def test_private_demo_benchmark_exposes_semantic_compiler_output() -> None:
    suite = load_suite(SUITE_PATH)

    report = run_suite(suite)

    for result in report["cases"]:
        assert result["compiler_schema_id"] == "nepsis.case_reasoning_compiler"
        assert result["compiler_valid"] is True
        assert result["runtime_safety_constraints"]
        assert result["domain_red_hazard"]["hazard"]
        assert "No PHI" not in result["domain_catastrophic_outcome"]
        assert "operator review is required" not in result["decision_reason"].lower()
