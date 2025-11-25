import re
from typing import Any, Dict, List

from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult


class UTF8HiddenManifold(BaseManifold):
    """
    Adversarial manifold enforcing invisible UTF-8 structure (e.g., zero-width markers).
    """

    name = "reasoning.utf8_hidden"

    def __init__(self, target_phrase: str = "NEPSIS", marker: str = "\u200b"):
        self.target_phrase = target_phrase.upper()
        self.marker = marker

    def triage(self, raw_query: str, context: str) -> TriageResult:
        phrase = (raw_query or "").strip().upper() or self.target_phrase
        hard_red = [
            f"Output must contain the target phrase '{phrase}'.",
            f"Output must include hidden marker U+200B (ZWSP) after the target phrase.",
        ]
        hard_blue = ["Prefer concise output.", "Avoid explanations."]
        manifold_meta = {"target_phrase": phrase, "marker": self.marker}
        return TriageResult(
            detected_manifold=self.name,
            confidence=0.95,
            is_well_posed=True,
            hard_red=hard_red,
            hard_blue=hard_blue,
            soft_blue=[],
            manifold_meta=manifold_meta,
        )

    def project(self, triage: TriageResult) -> ProjectionSpec:
        phrase = triage.manifold_meta.get("target_phrase", self.target_phrase)
        marker = triage.manifold_meta.get("marker", self.marker)
        return ProjectionSpec(
            system_instruction="Produce exactly one line of text respecting the hidden UTF-8 constraint. Do not explain.",
            manifold_context={
                "domain": self.name,
                "target_phrase": phrase,
                "marker": repr(marker),
            },
            invariants=[
                f"Include the exact phrase '{phrase}'.",
                f"Immediately follow the phrase with the hidden marker U+200B (zero-width space).",
                "Do not add explanations or multiple lines.",
            ],
            objective_function={
                "primary": "Satisfy all invariants.",
                "secondary": "Keep output minimal.",
            },
            trace={"manifold": self.name},
        )

    def validate(self, projection: ProjectionSpec, artifact: Any) -> ValidationResult:
        candidate = self._normalize_artifact(artifact)
        phrase = projection.manifold_context.get("target_phrase", self.target_phrase)
        marker = self.marker

        violations: List[str] = []
        repair_hints: List[str] = []

        if not candidate:
            violations.append("Empty candidate.")
            repair_hints.append("Provide non-empty output.")

        if phrase not in candidate:
            violations.append(f"Missing target phrase '{phrase}'.")
            repair_hints.append(f"Include the exact phrase '{phrase}'.")

        expected = f"{phrase}{marker}"
        if expected not in candidate:
            violations.append("Missing hidden marker after target phrase.")
            repair_hints.append("Insert U+200B immediately after the target phrase.")

        success = not violations
        blue_score = 1.0 if success else 0.0

        if not success:
            delta = " | ".join(repair_hints)
            next_projection_delta = f"PREVIOUS ATTEMPT REJECTED. {delta}. RETRY with hidden marker."
            return ValidationResult(
                outcome="REJECTED",
                metrics={
                    "red_violations": violations,
                    "blue_score": 0.0,
                    "drift_detected": True,
                },
                final_artifact=candidate,
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
            },
            final_artifact=candidate,
            repair={"needed": False},
        )

    @staticmethod
    def _normalize_artifact(artifact: Any) -> str:
        text = (artifact or "").strip()
        # Strip common code fences if the model adds them.
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
            text = text.rstrip("`").strip()
        return text
