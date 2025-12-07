from __future__ import annotations

import importlib
from typing import Any, Iterable, List

import numpy as np

from .dsl.base import Program
from .governor import tension_for_program, is_perfect


def enumerate_programs_for_manifold(manifold_cfg, train_pairs) -> Iterable[Program]:
    """
    Import the manifold module and yield candidate programs.
    """
    module = importlib.import_module(manifold_cfg.dsl_module)
    gen = getattr(module, "candidate_programs_from_train_pairs", None)
    if gen is None:
        return []
    return gen(train_pairs)


def solve_task_with_manifold(manifold_cfg, task_json: dict[str, Any]):
    """
    Iterate candidate programs, pick the best (lowest tension), and produce outputs.
    Returns a list of predicted outputs for test cases, or None if no program fits.
    """
    train_pairs = task_json.get("train", [])
    best_prog = None
    best_tension = 10**9

    for prog in enumerate_programs_for_manifold(manifold_cfg, train_pairs):
        t = tension_for_program(prog, train_pairs)
        if t < best_tension:
            best_tension = t
            best_prog = prog
        if t == 0:
            break

    if best_prog is None:
        return None

    outputs: List[Any] = []
    for test_case in task_json.get("test", []):
        x = np.array(test_case["input"], dtype=int)
        y_pred = best_prog(x)
        outputs.append(y_pred.tolist())

    return outputs
