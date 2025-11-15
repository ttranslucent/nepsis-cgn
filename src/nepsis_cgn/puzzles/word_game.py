from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List

from ..core.constraints import (
    CGNState,
    Constraint,
    ConstraintSet,
    ConstraintViolation,
)


@dataclass
class WordGameState:
    """
    State for the 7-letter word puzzle.

    letters: the multiset of allowed letters (e.g. "GINAGJL")
    candidate: the word produced by the LLM or human (e.g. "GINGAL")
    """

    letters: str
    candidate: str

    def letter_counts(self) -> Dict[str, int]:
        return Counter(self.letters.upper())

    def candidate_counts(self) -> Dict[str, int]:
        return Counter(self.candidate.upper())

    def describe(self) -> str:
        return (
            f"Letters: {''.join(sorted(self.letters.upper()))} | "
            f"Candidate: {self.candidate}"
        )


class UsesOnlyAllowedLetters(Constraint):
    name = "uses_only_allowed_letters"

    def check(self, state: WordGameState) -> List[ConstraintViolation]:
        allowed = state.letter_counts()
        cand = state.candidate_counts()
        violations: List[ConstraintViolation] = []

        for letter in cand:
            if letter not in allowed:
                violations.append(
                    ConstraintViolation(
                        message=f"Candidate uses illegal letter '{letter}'.",
                        code="illegal_letter",
                        severity="error",
                        metadata={"letter": letter},
                    )
                )

        return violations


class UsesEachLetterExactlyOnce(Constraint):
    name = "uses_each_letter_exactly_once"

    def check(self, state: WordGameState) -> List[ConstraintViolation]:
        allowed = state.letter_counts()
        cand = state.candidate_counts()
        violations: List[ConstraintViolation] = []

        for letter, allowed_count in allowed.items():
            used = cand.get(letter, 0)
            if used != allowed_count:
                violations.append(
                    ConstraintViolation(
                        message=(
                            f"Letter '{letter}' used {used} times; "
                            f"expected {allowed_count}."
                        ),
                        code="letter_count_mismatch",
                        severity="error",
                        metadata={
                            "letter": letter,
                            "expected": allowed_count,
                            "used": used,
                        },
                    )
                )

        for letter in cand:
            if letter not in allowed:
                violations.append(
                    ConstraintViolation(
                        message=f"Extra illegal letter '{letter}' present.",
                        code="extra_illegal_letter",
                        severity="error",
                        metadata={"letter": letter},
                    )
                )

        return violations


def build_word_game_constraint_set(
    name: str = "word_game_exact_use",
) -> ConstraintSet:
    """
    Constraint set for the basic Gingal/Jingall-style puzzle:
    - Must use only provided letters
    - Must use each letter exactly as many times as provided
    """

    return ConstraintSet(
        name=name,
        constraints=[
            UsesOnlyAllowedLetters(),
            UsesEachLetterExactlyOnce(),
        ],
    )


def compute_letter_deltas(state: WordGameState) -> Dict[str, int]:
    """Return how candidate usage deviates from the allowed pool."""
    allowed = state.letter_counts()
    used = state.candidate_counts()

    deltas: Dict[str, int] = {}
    for letter in set(allowed) | set(used):
        diff = used.get(letter, 0) - allowed.get(letter, 0)
        if diff:
            deltas[letter] = diff
    return deltas


def suggest_repair(state: WordGameState) -> List[str]:
    """Generate human-friendly hints for fixing an invalid candidate."""
    allowed = state.letter_counts()
    deltas = compute_letter_deltas(state)
    hints: List[str] = []

    for letter in sorted(deltas):
        diff = deltas[letter]
        if letter not in allowed:
            hints.append(f"remove all '{letter}' (not in allowed letters)")
        elif diff > 0:
            count = diff
            delta = "1" if count == 1 else str(count)
            hints.append(f"decrease '{letter}' by {delta}")
        else:
            count = -diff
            delta = "1" if count == 1 else str(count)
            hints.append(f"increase '{letter}' by {delta}")

    return hints


def compute_distance_from_validity(state: WordGameState) -> int:
    """Return Manhattan-style distance from the allowed multiset."""
    deltas = compute_letter_deltas(state)
    return sum(abs(diff) for diff in deltas.values())


def compute_quality_score(state: WordGameState) -> float:
    """Map the multiset distance into a [0, 1] quality score."""
    distance = compute_distance_from_validity(state)
    return 1.0 / (1.0 + float(distance))
