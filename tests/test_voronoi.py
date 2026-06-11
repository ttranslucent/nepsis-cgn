from __future__ import annotations

import math

import pytest

from nepsis.geometry import NepsisVoronoi, VoronoiSeed


def test_ruin_metric_exception_fails_closed() -> None:
    def broken_ruin_metric(candidate: dict[str, object]) -> float:  # noqa: ARG001
        raise RuntimeError("bad hazard shape")

    engine = NepsisVoronoi(
        [
            VoronoiSeed("SAFE", lambda candidate: 0.0, is_ruin=False),
            VoronoiSeed("RUIN_BROKEN", broken_ruin_metric, is_ruin=True),
        ]
    )

    result = engine.evaluate({"text": "candidate"})

    assert result.is_ruin_region is True
    assert result.collapsed is True
    assert result.dominant_seed == "RUIN_BROKEN"
    assert result.raw_metrics["RUIN_BROKEN"] == 0.0


def test_ruin_seed_wins_tie_against_safe_seed() -> None:
    engine = NepsisVoronoi(
        [
            VoronoiSeed("SAFE", lambda candidate: 1.0, is_ruin=False),
            VoronoiSeed("RUIN_TIE", lambda candidate: 1.0, is_ruin=True),
        ]
    )

    result = engine.evaluate({})

    assert result.dominant_seed == "RUIN_TIE"
    assert result.is_ruin_region is True


def test_seed_scale_normalizes_metric_before_weighting() -> None:
    engine = NepsisVoronoi(
        [
            VoronoiSeed("SAFE_NORMALIZED", lambda candidate: 50.0, scale=100.0),
            VoronoiSeed("UTILITY_RAW", lambda candidate: 1.0, scale=1.0),
        ]
    )

    result = engine.evaluate({})

    assert result.raw_metrics["SAFE_NORMALIZED"] == 50.0
    assert result.per_seed_values["SAFE_NORMALIZED"] == pytest.approx(0.5)
    assert result.per_seed_values["UTILITY_RAW"] == pytest.approx(1.0)
    assert result.dominant_seed == "SAFE_NORMALIZED"


@pytest.mark.parametrize("bad_value", [-0.1, math.inf, math.nan])
def test_non_ruin_metric_must_be_finite_and_non_negative(bad_value: float) -> None:
    engine = NepsisVoronoi([VoronoiSeed("SAFE_BAD", lambda candidate: bad_value)])

    with pytest.raises(ValueError, match="SAFE_BAD"):
        engine.evaluate({})


def test_seed_scale_must_be_finite_and_positive() -> None:
    with pytest.raises(ValueError, match="scale"):
        NepsisVoronoi([VoronoiSeed("BAD_SCALE", lambda candidate: 1.0, scale=0.0)])
