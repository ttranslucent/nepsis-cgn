#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from engine_adversarial_gate_snapshot import (
    scenario_contradiction_heavy,
    scenario_forced_red_override,
    scenario_vague_frame,
)


def _build_observed_snapshot() -> Dict[str, Any]:
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenarios": [
            scenario_vague_frame(),
            scenario_contradiction_heavy(),
            scenario_forced_red_override(),
        ],
    }


def _stage_status_string(stage_status: Dict[str, Any]) -> str:
    frame = stage_status.get("frame", "n/a")
    interpretation = stage_status.get("interpretation", "n/a")
    threshold = stage_status.get("threshold", "n/a")
    return f"frame={frame}, interpretation={interpretation}, threshold={threshold}"


def _load_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def _scenario_map(snapshot: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    scenarios = snapshot.get("scenarios", [])
    if not isinstance(scenarios, list):
        raise ValueError("snapshot.scenarios must be a list.")
    out: Dict[str, Dict[str, Any]] = {}
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            continue
        scenario_id = scenario.get("id")
        if isinstance(scenario_id, str) and scenario_id:
            out[scenario_id] = scenario
    return out


def _compare_snapshots(
    expected: Dict[str, Any],
    observed: Dict[str, Any],
) -> Tuple[List[str], Dict[str, List[str]]]:
    expected_map = _scenario_map(expected)
    observed_map = _scenario_map(observed)
    mismatches: List[str] = []
    per_scenario: Dict[str, List[str]] = {}

    all_ids = sorted(set(expected_map.keys()) | set(observed_map.keys()))
    for scenario_id in all_ids:
        scenario_mismatches: List[str] = []
        expected_scenario = expected_map.get(scenario_id)
        observed_scenario = observed_map.get(scenario_id)
        if expected_scenario is None:
            scenario_mismatches.append("Unexpected observed scenario (missing from expected snapshot).")
        elif observed_scenario is None:
            scenario_mismatches.append("Missing observed scenario.")
        else:
            expected_stage = expected_scenario.get("stage_status", {})
            observed_stage = observed_scenario.get("stage_status", {})
            for stage_key in ("frame", "interpretation", "threshold"):
                exp = expected_stage.get(stage_key)
                got = observed_stage.get(stage_key)
                if exp != got:
                    scenario_mismatches.append(
                        f"Stage status mismatch for '{stage_key}': expected={exp!r}, observed={got!r}."
                    )

            expected_checks = expected_scenario.get("check_status", {})
            observed_checks = observed_scenario.get("check_status", {})
            if isinstance(expected_checks, dict) and isinstance(observed_checks, dict):
                for section_name, section_expected in expected_checks.items():
                    section_observed = observed_checks.get(section_name)
                    if not isinstance(section_expected, dict):
                        continue
                    if not isinstance(section_observed, dict):
                        scenario_mismatches.append(
                            f"Missing check status section '{section_name}'."
                        )
                        continue
                    for check_key, expected_value in section_expected.items():
                        observed_value = section_observed.get(check_key)
                        if observed_value != expected_value:
                            scenario_mismatches.append(
                                f"Check mismatch {section_name}.{check_key}: expected={expected_value!r}, observed={observed_value!r}."
                            )

        if scenario_mismatches:
            mismatches.extend([f"{scenario_id}: {item}" for item in scenario_mismatches])
        per_scenario[scenario_id] = scenario_mismatches

    return mismatches, per_scenario


def _build_markdown_report(
    *,
    expected_path: Path,
    observed_snapshot: Dict[str, Any],
    expected_snapshot: Dict[str, Any],
    mismatches: List[str],
    per_scenario: Dict[str, List[str]],
) -> str:
    observed_map = _scenario_map(observed_snapshot)
    expected_map = _scenario_map(expected_snapshot)
    scenario_ids = sorted(set(expected_map.keys()) | set(observed_map.keys()))
    status = "PASS" if not mismatches else "FAIL"
    lines = [
        "# Engine Adversarial QA Verification",
        "",
        f"- Executed at (UTC): {observed_snapshot.get('generated_at_utc', 'unknown')}",
        f"- Expected snapshot: `{expected_path}`",
        f"- Result: **{status}**",
        "",
    ]

    if mismatches:
        lines.append("## Mismatches")
        for mismatch in mismatches:
            lines.append(f"- {mismatch}")
        lines.append("")

    lines.append("## Scenario Summary")
    for scenario_id in scenario_ids:
        expected_scenario = expected_map.get(scenario_id, {})
        observed_scenario = observed_map.get(scenario_id, {})
        label = (
            observed_scenario.get("label")
            if isinstance(observed_scenario.get("label"), str)
            else expected_scenario.get("label", scenario_id)
        )
        expected_stage = expected_scenario.get("stage_status", {})
        observed_stage = observed_scenario.get("stage_status", {})
        lines.append(f"### {scenario_id} - {label}")
        lines.append(f"- Expected: `{_stage_status_string(expected_stage if isinstance(expected_stage, dict) else {})}`")
        lines.append(f"- Observed: `{_stage_status_string(observed_stage if isinstance(observed_stage, dict) else {})}`")
        scenario_mismatches = per_scenario.get(scenario_id, [])
        if scenario_mismatches:
            lines.append("- Status: mismatch")
        else:
            lines.append("- Status: pass")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify adversarial /engine stage-gate scenarios against expected snapshot.")
    parser.add_argument(
        "--expected",
        default="briefs/2026-03-10_engine_adversarial_gate_expected.json",
        help="Path to expected adversarial gate snapshot JSON.",
    )
    parser.add_argument(
        "--report-out",
        default="briefs/2026-03-11_engine_adversarial_qa_report.md",
        help="Path to write Markdown verification report.",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Do not return a non-zero exit code when mismatches are found.",
    )
    args = parser.parse_args()

    expected_path = Path(args.expected)
    if not expected_path.exists():
        raise FileNotFoundError(f"Expected snapshot not found: {expected_path}")

    expected_snapshot = _load_json(expected_path)
    observed_snapshot = _build_observed_snapshot()
    mismatches, per_scenario = _compare_snapshots(expected_snapshot, observed_snapshot)
    report = _build_markdown_report(
        expected_path=expected_path,
        observed_snapshot=observed_snapshot,
        expected_snapshot=expected_snapshot,
        mismatches=mismatches,
        per_scenario=per_scenario,
    )

    report_path = Path(args.report_out)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(report, end="")

    if mismatches and not args.no_fail:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
