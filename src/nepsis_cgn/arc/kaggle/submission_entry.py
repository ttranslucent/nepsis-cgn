from __future__ import annotations

import json
import sys
from pathlib import Path

from ..router import LocalManifoldRouter
from ..solver import solve_task_with_manifold


def solve_arc_dataset(input_dir: str, output_path: str = "submission.json"):
    """
    Offline ARC entrypoint:
    - input_dir: directory containing ARC task JSON files
    - output_path: where to write submission.json
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        raise SystemExit(f"[ERROR] Input dir does not exist: {input_path}")

    router = LocalManifoldRouter()
    solutions = {}

    files = sorted(input_path.glob("*.json"))
    print(f"[ARC] Loading tasks from {input_path} (found {len(files)} json files)")

    for idx, json_file in enumerate(files, 1):
        print(f"[ARC] [{idx}/{len(files)}] Solving {json_file.name}...")
        with json_file.open() as f:
            task = json.load(f)

        manifolds = router.route(task)
        best_output = None

        for m in manifolds:
            print(f"    -> Trying manifold '{m.id}'...")
            out = solve_task_with_manifold(m, task)
            if out is not None:
                best_output = out
                print(f"       ✓ Manifold '{m.id}' produced a solution")
                break
            else:
                print(f"       ✗ Manifold '{m.id}' failed")

        if best_output is None:
            print("    !! No solution found, using fallback (copying inputs)")
            best_output = [case["input"] for case in task["test"]]

        solutions[json_file.stem] = best_output

    with open(output_path, "w") as f:
        json.dump(solutions, f)

    print(f"[ARC] Wrote submission with {len(solutions)} tasks to {output_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m nepsis_cgn.arc.kaggle.submission_entry <input_dir> [output_path]")
        raise SystemExit(1)

    input_dir = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "submission.json"
    solve_arc_dataset(input_dir, output_path)

