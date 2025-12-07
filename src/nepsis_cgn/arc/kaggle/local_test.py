from __future__ import annotations

import json
from pathlib import Path

from .submission_entry import solve_arc_dataset


def run_sample_task(task_path: str) -> str:
    """
    Run solver on a single ARC task JSON file and write submission.json alongside it.
    Returns the path to the submission file.
    """
    task_file = Path(task_path)
    input_dir = task_file.parent
    output_path = input_dir / "submission.json"
    solve_arc_dataset(str(input_dir), str(output_path))
    return str(output_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run ARC solver on a sample task JSON.")
    parser.add_argument("task_path", help="Path to a single ARC task JSON file.")
    args = parser.parse_args()

    out = run_sample_task(args.task_path)
    print(f"Wrote {out}")
