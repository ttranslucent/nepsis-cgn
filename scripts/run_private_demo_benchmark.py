#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nepsis_cgn.api.private_demo import build_private_demo_runtime_packet


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITE_PATH = ROOT / "data" / "private_demo_cases" / "authority_suppressed_red_channel.json"
REPORT_SCHEMA_ID = "nepsis.private_demo_benchmark_report"
REPORT_SCHEMA_VERSION = "0.1.0"


def load_suite(path: str | Path) -> dict[str, Any]:
    suite_path = Path(path)
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    if suite.get("schema_id") != "nepsis.private_demo_case_suite":
        raise ValueError("private demo benchmark suite must use schema_id nepsis.private_demo_case_suite")
    cases = suite.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("private demo benchmark suite requires a non-empty cases list")
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ValueError(f"case {index} must be an object")
        _required_string(case, "case_id", f"case {index}")
        _required_string(case, "domain", f"case {index}")
        _required_string(case, "prompt", f"case {index}")
        if case.get("no_phi_acknowledged") is not True:
            raise ValueError(f"case {case.get('case_id', index)!r} must acknowledge no PHI")
    return suite


def run_suite(suite: dict[str, Any]) -> dict[str, Any]:
    required_events = suite.get("required_audit_events") or [
        "LOCK_FRAME",
        "RUN_REPORT",
        "LOCK_REPORT",
        "SET_THRESHOLD_DECISION",
    ]
    if not isinstance(required_events, list) or not all(isinstance(event, str) for event in required_events):
        raise ValueError("required_audit_events must be a list of strings")

    results = [_run_case(case, required_events=required_events) for case in suite["cases"]]
    total = len(results)
    held_cases = sum(1 for case in results if case["red_channel_held"])
    required_events_cases = sum(1 for case in results if case["required_events_present"])
    passing_cases = sum(1 for case in results if case["benchmark_passed"])
    return {
        "schema_id": REPORT_SCHEMA_ID,
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "suite_id": suite.get("suite_id"),
        "title": suite.get("title"),
        "invariant": suite.get("invariant"),
        "failure_mode_label": suite.get("failure_mode_label"),
        "summary": {
            "total_cases": total,
            "held_cases": held_cases,
            "required_events_cases": required_events_cases,
            "passing_cases": passing_cases,
            "pass_rate": passing_cases / total if total else 0.0,
        },
        "cases": results,
    }


def _run_case(case: dict[str, Any], *, required_events: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    packet = build_private_demo_runtime_packet(
        {
            "case_id": case["case_id"],
            "prompt": case["prompt"],
            "no_phi_acknowledged": True,
            "thread_id": f"benchmark:{case['case_id']}",
            "user_id": "benchmark-local",
        }
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    operator_packet = packet.get("operator_packet") if isinstance(packet.get("operator_packet"), dict) else {}
    audit_trace = packet.get("audit_trace") if isinstance(packet.get("audit_trace"), list) else []
    audit_events = [entry.get("event") for entry in audit_trace if isinstance(entry, dict)]
    threshold_event = _last_event(audit_trace, "SET_THRESHOLD_DECISION")
    threshold_args = threshold_event.get("arguments") if isinstance(threshold_event.get("arguments"), dict) else {}
    threshold_decision = threshold_args.get("decision")
    latest_audit = packet.get("latest_audit") if isinstance(packet.get("latest_audit"), dict) else {}
    latest_audit_statuses = {
        "frame": _audit_status(latest_audit, "frame"),
        "interpretation": _audit_status(latest_audit, "interpretation"),
        "threshold": _audit_status(latest_audit, "threshold"),
    }
    required_events_present = audit_events == required_events
    red_channel_held = threshold_decision == "hold"
    latest_audit_passed = all(status == "PASS" for status in latest_audit_statuses.values())
    return {
        "case_id": packet.get("case_id"),
        "domain": case["domain"],
        "title": case.get("title", case["case_id"]),
        "schema_id": packet.get("schema_id"),
        "operator_schema_id": operator_packet.get("schema_id"),
        "operator_phase": operator_packet.get("phase"),
        "prompt_hash": packet.get("prompt_hash"),
        "duration_ms": duration_ms,
        "red_channel_question": case.get("red_channel_question"),
        "closure_condition": case.get("closure_condition"),
        "expected_behavior": case.get("expected_behavior"),
        "threshold_decision": threshold_decision,
        "hold_reason": threshold_args.get("hold_reason", ""),
        "audit_events": audit_events,
        "required_events_present": required_events_present,
        "latest_audit_statuses": latest_audit_statuses,
        "red_channel_held": red_channel_held,
        "benchmark_passed": bool(
            packet.get("schema_id") == "nepsis.private_demo_runtime_packet"
            and operator_packet.get("schema_id") == "nepsis.operator_packet"
            and operator_packet.get("phase") == "threshold_set"
            and required_events_present
            and red_channel_held
            and latest_audit_passed
        ),
    }


def _last_event(audit_trace: list[Any], event_name: str) -> dict[str, Any]:
    for entry in reversed(audit_trace):
        if isinstance(entry, dict) and entry.get("event") == event_name:
            return entry
    return {}


def _audit_status(latest_audit: dict[str, Any], key: str) -> str | None:
    section = latest_audit.get(key)
    if not isinstance(section, dict):
        return None
    status = section.get("status")
    return status if isinstance(status, str) else None


def _required_string(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} requires non-empty string field {key!r}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_private_demo_benchmark.py",
        description="Run no-PHI/no-PII private demo cases through the NepsisCGN audit-packet runtime.",
    )
    parser.add_argument(
        "suite",
        nargs="?",
        default=str(DEFAULT_SUITE_PATH),
        help="Path to a nepsis.private_demo_case_suite JSON file.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the full JSON report.")
    parser.add_argument("--output", help="Optional path to write the full JSON report.")
    args = parser.parse_args(argv)

    report = run_suite(load_suite(args.suite))
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        summary = report["summary"]
        print(
            "private_demo_benchmark "
            f"suite={report['suite_id']} "
            f"passing={summary['passing_cases']}/{summary['total_cases']} "
            f"held={summary['held_cases']} "
            f"required_events={summary['required_events_cases']}"
        )
        for result in report["cases"]:
            status = "PASS" if result["benchmark_passed"] else "FAIL"
            print(
                f"{status} {result['case_id']} "
                f"domain={result['domain']} "
                f"decision={result['threshold_decision']} "
                f"events={','.join(result['audit_events'])} "
                f"duration_ms={result['duration_ms']}"
            )
    return 0 if report["summary"]["passing_cases"] == report["summary"]["total_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
