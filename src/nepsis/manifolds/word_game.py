import collections
import re
from typing import Any, Dict, List

from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult


class WordGameManifold(BaseManifold):
    """
    Jingall-style letter multiset manifold.
    """

    name = "word_game.letter_multiset"

    def __init__(self, dictionary: List[str] | None = None):
        # Tiny prototype dictionary; swap with a real lexicon in production.
        self.dictionary = set(dictionary or ["JINGALL", "JINGLE", "GILL", "NAIL", "GALL", "LAG", "JAILING"])

    def triage(self, raw_query: str, context: str) -> TriageResult:
        """
        Detect the letter multiset and declare constraints.
        """
        letters = self._extract_letters(raw_query)
        is_well_posed = bool(letters)
        confidence = 0.99 if is_well_posed else 0.2

        hard_red = [
            "candidate must be a dictionary word",
            "candidate must use only provided letters",
            "candidate must not exceed any letter count",
        ]
        hard_blue = [
            "maximize word length",
            "prefer single-word answers",
        ]

        manifold_meta = {"source_letters": letters}

        return TriageResult(
            detected_manifold=self.name if is_well_posed else "unknown",
            confidence=confidence,
            is_well_posed=is_well_posed,
            hard_red=hard_red,
            hard_blue=hard_blue,
            soft_blue=[],
            manifold_meta=manifold_meta,
        )

    def project(self, triage: TriageResult) -> ProjectionSpec:
        """
        Build the jail the worker must stay inside.
        """
        letters = triage.manifold_meta.get("source_letters", [])
        letter_str = "".join(letters)
        letter_list = ", ".join(letters)

        return ProjectionSpec(
            system_instruction="You must propose English words using the given letters. Output only one UPPERCASE word.",
            manifold_context={
                "domain": self.name,
                "letter_multiset": letter_str,
                "letters": letter_list,
            },
            invariants=[
                f"Use only letters from {letter_str}.",
                "Do not repeat any letter more times than it appears in the multiset.",
                "Output must be a real English word.",
            ],
            objective_function={
                "primary": "Satisfy all invariants.",
                "secondary": "Maximize word length.",
                "optimization": "If multiple choices, prefer rarer words.",
            },
            trace={"letters": letter_list},
        )

    def validate(self, projection: ProjectionSpec, artifact: Any) -> ValidationResult:
        """
        Red channel: enforce dictionary + multiset constraints.
        """
        # Normalize artifacts, strip markdown fences and uppercase.
        candidate = (artifact or "").replace("```", "").strip().upper()

        source_letters = projection.manifold_context.get("letters") or projection.manifold_context.get(
            "letter_multiset", ""
        )
        source_letters_list = [c.strip() for c in source_letters.split(",") if c.strip()]
        source_counts = collections.Counter(source_letters_list)
        candidate_counts = collections.Counter(candidate)

        violations: List[str] = []
        repair_hints: List[str] = []

        # Dictionary check
        if not candidate:
            violations.append("Empty candidate")
            repair_hints.append("Provide a non-empty uppercase word.")
        elif candidate not in self.dictionary:
            violations.append(f"Dictionary Violation: '{candidate}' unknown")
            repair_hints.append(f"ERROR: '{candidate}' is not in the valid dictionary.")

        # Multiset check
        for char, count in candidate_counts.items():
            allowed = source_counts.get(char, 0)
            if count > allowed:
                violations.append(f"Multiset Violation: Used '{char}' {count}x (Allowed: {allowed}x)")
                repair_hints.append(
                    f"CONSTRAINT BREACH: You used '{char}' {count} times. The bank only contains it {allowed} times."
                )
            if allowed == 0:
                repair_hints.append(f"CONSTRAINT BREACH: The letter '{char}' is not in the source bank.")

        success = not violations

        if violations:
            delta_message = " | ".join(repair_hints)
            next_projection_delta = (
                f"PREVIOUS ATTEMPT REJECTED. {delta_message}. RETRY and strictly obey letter counts."
            )
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

        # Normalized blue score based on how completely the candidate uses the available letters.
        score = min(1.0, len(candidate) / max(1, len(source_letters_list)))

        return ValidationResult(
            outcome="SUCCESS",
            metrics={
                "red_violations": [],
                "blue_score": score,
                "drift_detected": False,
            },
            final_artifact=candidate,
            repair={"needed": False},
        )

    @staticmethod
    def _extract_letters(raw_query: str) -> List[str]:
        """
        Prefer explicit uppercase blocks; fallback to all alphabetic chars.
        """
        blocks = re.findall(r"[A-Z]{3,}", raw_query)
        if blocks:
            return list(blocks[0])
        return [c.upper() for c in raw_query if c.isalpha()]
