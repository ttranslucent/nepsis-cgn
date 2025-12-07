from __future__ import annotations

import numpy as np

from .dsl.base import Program


def tension_for_program(program: Program, train_pairs) -> int:
    """
    Exact grid comparison against training pairs; returns total mismatch count.
    """
    total = 0
    for pair in train_pairs:
        x = np.array(pair["input"], dtype=int)
        y = np.array(pair["output"], dtype=int)
        y_pred = program(x)
        if y_pred.shape != y.shape:
            return 10**9
        total += (y_pred != y).sum()
    return int(total)


def is_perfect(program: Program, train_pairs) -> bool:
    """True if program matches all train pairs exactly."""
    return tension_for_program(program, train_pairs) == 0
