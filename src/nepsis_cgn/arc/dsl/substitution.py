from __future__ import annotations

import numpy as np
from typing import Iterable, List, Dict

from .base import Program, Grid


def candidate_programs_from_train_pairs(train_pairs) -> Iterable[Program]:
    """
    Generate simple color remap programs inferred from training pairs.

    Strategy: build a mapping from input colors to output colors based on the
    first train pair; if shapes differ, yield nothing.
    """
    if not train_pairs:
        return []

    first = train_pairs[0]
    gx = np.array(first["input"], dtype=int)
    gy = np.array(first["output"], dtype=int)

    if gx.shape != gy.shape:
        return []

    in_colors = np.unique(gx).tolist()
    mapping: Dict[int, int] = {}

    # Naive heuristic: map each input color to the most common output color at the same positions
    for c in in_colors:
        mask = gx == c
        if mask.sum() == 0:
            continue
        out_vals = gy[mask]
        values, counts = np.unique(out_vals, return_counts=True)
        top_idx = int(np.argmax(counts))
        mapping[c] = int(values[top_idx])

    if not mapping:
        return []

    def remap(grid: Grid) -> Grid:
        out = grid.copy()
        for src, dst in mapping.items():
            out[grid == src] = dst
        return out

    yield Program(remap, description=f"color_map({mapping})")
