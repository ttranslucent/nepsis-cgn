from __future__ import annotations

import numpy as np
from typing import Callable

Grid = np.ndarray


class Program:
    """Thin wrapper around a callable grid-to-grid transform."""

    def __init__(self, fn: Callable[[Grid], Grid], description: str = ""):
        self.fn = fn
        self.description = description

    def __call__(self, grid: Grid) -> Grid:
        return self.fn(grid)
