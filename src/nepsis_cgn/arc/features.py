from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass
class ArcFeatures:
    """Placeholder feature bundle for ARC routing."""

    same_shape: bool
    input_shape: Tuple[int, ...]
    output_shape: Tuple[int, ...]
    num_colors_input: int
    num_colors_output: int


def extract_task_features(task_json: Dict[str, Any]) -> ArcFeatures:
    """
    Extract coarse features from the first train pair of an ARC task JSON blob.
    """

    train_pairs = task_json.get("train", [])
    if not train_pairs:
        return ArcFeatures(
            same_shape=False,
            input_shape=(),
            output_shape=(),
            num_colors_input=0,
            num_colors_output=0,
        )

    first = train_pairs[0]
    gx = np.array(first["input"], dtype=int)
    gy = np.array(first["output"], dtype=int)

    same_shape = gx.shape == gy.shape
    colors_x = np.unique(gx)
    colors_y = np.unique(gy)

    return ArcFeatures(
        same_shape=same_shape,
        input_shape=gx.shape,
        output_shape=gy.shape,
        num_colors_input=len(colors_x),
        num_colors_output=len(colors_y),
    )
