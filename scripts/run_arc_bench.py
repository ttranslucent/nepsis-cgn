#!/usr/bin/env python
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, List


def run_nepsis_arc_attach(task_json: str, model: str = "openai") -> Any:
    """
    Call the Nepsis CLI in arc_attach mode and capture the final JSON grid.
    Requires the CLI to support --quiet-json (final artifact only).
    """
    cmd = [
        sys.executable,
        "-m",
        "nepsis.cli",
        "--mode",
        "arc_attach",
        "--model",
        model,
        "--query",
        task_json,
        "--quiet-json",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        print("Nepsis CLI failed:", proc.stderr, file=sys.stderr)
        return None

    lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()]
    if not lines:
        return None
    last = lines[-1]
    try:
        obj = json.loads(last)
        if isinstance(obj, dict) and "grid" in obj:
            return obj["grid"]
        return obj
    except Exception:
        print("Failed to parse Nepsis output as JSON:", last, file=sys.stderr)
        return None


def hamming_distance_grid(a: List[List[int]], b: List[List[int]]) -> int:
    if len(a) != len(b) or len(a[0]) != len(b[0]):
        return max(len(a), len(b)) * max(len(a[0]), len(b[0]))
    dist = 0
    for ra, rb in zip(a, b):
        for ca, cb in zip(ra, rb):
            if ca != cb:
                dist += 1
    return dist


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/run_arc_bench.py data/arc/1f642eb9.json", file=sys.stderr)
        return 1

    task_path = Path(sys.argv[1])
    if not task_path.exists():
        print(f"File not found: {task_path}", file=sys.stderr)
        return 1

    data = json.loads(task_path.read_text())

    test_cases = data.get("test", [])
    if not test_cases:
        print("No test cases found in JSON.")
        return 1

    test0 = test_cases[0]
    ground_truth = test0.get("output")
    if ground_truth is not None:
        print(f"Ground truth shape: {len(ground_truth)} x {len(ground_truth[0])}")
    else:
        print("No ground truth provided; structural run only.")

    task_json = task_path.read_text()
    pred_grid = run_nepsis_arc_attach(task_json, model="openai")
    if pred_grid is None:
        print("Nepsis produced no valid grid.")
        return 1

    print(f"Nepsis grid shape: {len(pred_grid)} x {len(pred_grid[0])}")

    if ground_truth is not None:
        dist = hamming_distance_grid(pred_grid, ground_truth)
        exact = dist == 0
        print(f"Hamming distance: {dist}")
        print(f"Exact match: {exact}")
    else:
        print("Structural pass only (no ground truth to compare).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
