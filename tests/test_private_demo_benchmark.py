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
    assert report["summary"]["total_cases"] == 5
    assert report["summary"]["held_cases"] == 5
    assert report["summary"]["required_events_cases"] == 5
    assert report["summary"]["passing_cases"] == 5
    assert {case["domain"] for case in report["cases"]} == {"medical", "finance"}


def test_authority_suppression_cases_keep_red_open_under_authority_pushback() -> None:
    suite = load_suite(SUITE_PATH)

    report = run_suite(suite)

    for result in report["cases"]:
        assert result["red_channel_held"] is True
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
