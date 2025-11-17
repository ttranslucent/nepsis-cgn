from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from ..manifolds.proto_puzzle import evaluate_proto_puzzle

PACK_CHOICES = ["jailing_jingall", "utf8_clean", "terminal_bench"]


def parse_state(state_json: str) -> Dict[str, Any]:
    try:
        data = json.loads(state_json)
    except json.JSONDecodeError as exc:  # pragma: no cover - CLI guardrail
        raise SystemExit(f"Invalid JSON for --state-json: {exc}")

    if not isinstance(data, dict):
        raise SystemExit("--state-json must decode to an object/dict")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a Proto Puzzle state via NepsisCGN.")
    parser.add_argument("--pack", required=True, choices=PACK_CHOICES, help="Constraint pack to apply.")
    parser.add_argument(
        "--state-json",
        required=True,
        help="JSON blob describing either the manifold state or a Terminal Bench summary.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON output for automation",
    )
    args = parser.parse_args()

    state_mapping = parse_state(args.state_json)
    report = evaluate_proto_puzzle(args.pack, state_mapping)

    if args.json:
        payload = {
            "pack_id": report.pack_id,
            "pack_name": report.pack_name,
            "state": report.state,
            "is_valid": report.is_valid,
            "distance": report.distance,
            "violations": [
                {
                    "code": violation.code,
                    "severity": violation.severity,
                    "message": violation.message,
                    "metadata": violation.metadata,
                }
                for violation in report.violations
            ],
            "hints": report.hints,
        }
        print(json.dumps(payload))
        return

    print(f"Pack: {args.pack}")
    print(f"Valid: {report.is_valid}")
    print(f"Distance: {report.distance}")
    print(f"State: {json.dumps(report.state)}")
    print(f"Violations ({len(report.violations)}):")
    for violation in report.violations:
        print(
            f"  - [{violation.severity.upper()}] {violation.code}: {violation.message}"
        )


if __name__ == "__main__":
    main()
