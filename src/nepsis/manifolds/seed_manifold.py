from typing import Any, Dict, List

from ..geometry import NepsisVoronoi, VoronoiSeed
from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult


def _contains_token_metric(token: str, penalty: float = 10.0):
    """
    Distance metric: 0 if token present, penalty otherwise.
    """

    def metric(candidate: Dict[str, Any]) -> float:
        text = (candidate.get("text") or "").upper()
        return 0.0 if token.upper() in text else penalty

    return metric


def _length_metric(candidate: Dict[str, Any]) -> float:
    """
    Favor shorter outputs: distance is length.
    """
    text = candidate.get("text") or ""
    return float(len(text))


class SeedManifold(BaseManifold):
    """
    Domain-agnostic seed-based manifold using additive Voronoi geometry.
    """

    name = "reasoning.seed_voronoi"

    def __init__(self):
        # Default toy seed set: forbid "FORBID"; require "OK".
        seeds = [
            VoronoiSeed(
                name="RUIN_FORBIDDEN_TOKEN",
                metric=_contains_token_metric("FORBID", penalty=10.0),
                weight=5.0,
                is_ruin=True,
            ),
            VoronoiSeed(name="VALID_OK_TOKEN", metric=_contains_token_metric("OK", penalty=5.0), weight=0.0, is_ruin=False),
            VoronoiSeed(name="UTILITY_SHORTEST", metric=_length_metric, weight=0.0, is_ruin=False),
        ]
        self.engine = NepsisVoronoi(seeds)

    def triage(self, raw_query: str, context: str) -> TriageResult:
        hard_red = [
            "Output must not contain forbidden token 'FORBID'.",
            "If any ruin seed dominates, reject.",
        ]
        hard_blue = [
            "Prefer including 'OK' token.",
            "Prefer shorter outputs.",
        ]
        manifold_meta: Dict[str, Any] = {"query": raw_query}
        return TriageResult(
            detected_manifold=self.name,
            confidence=0.9,
            is_well_posed=True,
            hard_red=hard_red,
            hard_blue=hard_blue,
            soft_blue=[],
            manifold_meta=manifold_meta,
        )

    def project(self, triage: TriageResult) -> ProjectionSpec:
        return ProjectionSpec(
            system_instruction="Produce a concise answer obeying the constraints. Do not explain.",
            manifold_context={
                "domain": self.name,
                "forbidden_token": "FORBID",
                "preferred_token": "OK",
            },
            invariants=[
                "Do not include the token 'FORBID'.",
                "Prefer including the token 'OK'.",
                "Keep the output short.",
            ],
            objective_function={
                "primary": "Avoid ruin seeds.",
                "secondary": "Satisfy utility seeds.",
            },
            trace={"manifold": self.name},
        )

    def validate(self, projection: ProjectionSpec, artifact: Any) -> ValidationResult:
        text = (artifact or "").strip()
        candidate = {"text": text}
        result = self.engine.evaluate(candidate)

        violations: List[str] = []
        repair_hints: List[str] = []

        if result.is_ruin_region:
            violations.append(f"Ruin seed dominated: {result.dominant_seed}")
            repair_hints.append("Remove forbidden tokens and satisfy required tokens.")

        # Basic utility scoring: inverse of dominant value if not ruin
        blue_score = 0.0
        if not result.is_ruin_region:
            blue_score = max(0.0, 1.0 / (1.0 + max(result.dominant_value, 0.0)))
            if "VALID_OK_TOKEN" not in result.per_seed_values:
                repair_hints.append("Include token 'OK' to satisfy utility.")

        success = not violations
        if not success:
            delta = " | ".join(repair_hints) if repair_hints else "Fix constraint violations."
            next_projection_delta = f"PREVIOUS ATTEMPT REJECTED. {delta}"
            return ValidationResult(
                outcome="REJECTED",
                metrics={
                    "red_violations": violations,
                    "blue_score": blue_score,
                    "drift_detected": True,
                    "dominant_seed": result.dominant_seed,
                },
                final_artifact=text,
                repair={
                    "needed": True,
                    "hints": repair_hints,
                    "next_projection_delta": next_projection_delta,
                    "tactic": "constraint_injection",
                },
            )

        return ValidationResult(
            outcome="SUCCESS",
            metrics={
                "red_violations": [],
                "blue_score": blue_score,
                "drift_detected": False,
                "dominant_seed": result.dominant_seed,
            },
            final_artifact=text,
            repair={"needed": False},
        )
