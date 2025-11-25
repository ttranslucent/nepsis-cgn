from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

# Metric function: consumes a candidate dict/state and returns a distance (lower is better).
MetricFn = Callable[[Dict[str, Any]], float]


@dataclass
class VoronoiSeed:
    """
    A single constraint center in Nepsis geometry.

    - metric(candidate) -> float: lower is 'closer' / better fit.
    - weight: additive weight; higher = more gravitational pull.
    - is_ruin: True = this is a catastrophic / Red region.
    """

    name: str
    metric: MetricFn
    weight: float = 0.0
    is_ruin: bool = False


@dataclass
class VoronoiResult:
    """
    Outcome of evaluating a candidate against a set of weighted seeds.
    """

    dominant_seed: Optional[str]
    dominant_value: float
    is_ruin_region: bool
    per_seed_values: Dict[str, float]
    raw_metrics: Dict[str, float]
    weights: Dict[str, float]
    collapsed: bool


class NepsisVoronoi:
    """
    Minimal additive-weighted Voronoi engine for Nepsis.

    Domain-agnostic: does not know about puzzles, configs, or clinical logic.
    """

    def __init__(self, seeds: List[VoronoiSeed]):
        if not seeds:
            raise ValueError("NepsisVoronoi requires at least one seed.")
        self.seeds = seeds

    def evaluate(self, candidate: Dict[str, Any]) -> VoronoiResult:
        """
        Evaluate a candidate state.

        - metric(candidate) -> distance d_i
        - v_i = d_i - weight_i (additive weighted Voronoi)
        - dominant seed = argmin v_i
        """
        per_seed_values: Dict[str, float] = {}
        raw_metrics: Dict[str, float] = {}
        weights: Dict[str, float] = {}

        dominant_name: Optional[str] = None
        dominant_value: float = float("inf")
        dominant_is_ruin: bool = False

        for seed in self.seeds:
            try:
                d = seed.metric(candidate)
            except Exception:
                d = float("inf")

            v = d - seed.weight

            raw_metrics[seed.name] = d
            weights[seed.name] = seed.weight
            per_seed_values[seed.name] = v

            if v < dominant_value:
                dominant_value = v
                dominant_name = seed.name
                dominant_is_ruin = seed.is_ruin

        collapsed = bool(dominant_is_ruin)

        return VoronoiResult(
            dominant_seed=dominant_name,
            dominant_value=dominant_value,
            is_ruin_region=dominant_is_ruin,
            per_seed_values=per_seed_values,
            raw_metrics=raw_metrics,
            weights=weights,
            collapsed=collapsed,
        )

    def add_seed(self, seed: VoronoiSeed) -> None:
        """Dynamically extend the field with a new constraint."""
        self.seeds.append(seed)
