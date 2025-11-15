from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from ..core.solver import CGNSolver
from ..puzzles.word_game import (
    WordGameState,
    build_word_game_constraint_set,
    compute_distance_from_validity,
    compute_quality_score,
    suggest_repair,
)


class LLMClient(Protocol):
    """
    Minimal interface for an LLM backend.

    Implement this for whatever you use:
      - OpenAI, Anthropic, Grok, local llama, etc.

    The sidecar doesn't care *how* you get a response,
    only that generate() returns a string.
    """

    def generate(self, prompt: str, **kwargs: Any) -> str:
        ...


@dataclass
class WordGameAttempt:
    attempt: int
    candidate: str
    distance: int
    quality: float
    valid: bool
    repair_hints: List[str]


@dataclass
class WordGameLLMSession:
    """
    Orchestrates an interactive session between an LLM and NepsisCGN
    for the 7-letter word puzzle.

    The flow:
      1. Build a prompt from letters + any previous attempts/hints.
      2. Ask the LLM for a candidate word.
      3. Evaluate via NepsisCGN.
      4. If invalid and attempts remain, feed repair hints into next prompt.
    """

    letters: str
    llm: LLMClient
    max_attempts: int = 3
    stop_on_quality: float = 1.0  # 1.0 = only accept perfect
    history: List[WordGameAttempt] = field(default_factory=list)

    def __post_init__(self) -> None:
        constraint_set = build_word_game_constraint_set()
        self.solver = CGNSolver(constraint_set=constraint_set)

    def build_prompt(self, previous_attempt: Optional[WordGameAttempt]) -> str:
        """
        Construct a system/user-style prompt string for the LLM.

        This is deliberately simple. You can tweak tone later.
        """

        base = [
            "You are solving a 7-letter word puzzle.",
            "You are given a multiset of letters.",
            "Your task is to propose a SINGLE English-looking word",
            "that uses ALL of the letters EXACTLY once.",
            "",
            f"Available letters (multiset): {self.letters}",
            "",
        ]

        if not self.history:
            base.append(
                "Reply with ONLY the candidate word, no explanations, "
                "no punctuation, no quotes."
            )
        else:
            base.append("Previous attempts and feedback:")

            for attempt in self.history:
                status = "VALID" if attempt.valid else "INVALID"
                base.append(
                    f"- Attempt {attempt.attempt}: '{attempt.candidate}' → {status}, "
                    f"distance={attempt.distance}, quality={attempt.quality:.3f}"
                )
                if attempt.repair_hints and not attempt.valid:
                    base.append("  Repair hints:")
                    for hint in attempt.repair_hints:
                        base.append(f"    • {hint}")

            base.extend(
                [
                    "",
                    "Use this feedback to adjust your next candidate.",
                    "Try to move toward distance 0 and quality 1.0.",
                    "Again, reply with ONLY the candidate word.",
                ]
            )

        return "\n".join(base)

    def run(self) -> WordGameAttempt:
        """
        Run up to max_attempts. Returns the final attempt (valid or not).

        This is your basic LLM+NepsisCGN sidecar loop.
        """

        last_attempt: Optional[WordGameAttempt] = None

        for attempt_idx in range(1, self.max_attempts + 1):
            prompt = self.build_prompt(last_attempt)
            raw_response = self.llm.generate(prompt)

            candidate = raw_response.strip()
            state = WordGameState(letters=self.letters, candidate=candidate)
            result = self.solver.evaluate_state(state)

            distance = compute_distance_from_validity(state)
            quality = compute_quality_score(state)
            hints: List[str] = []

            if not result.is_valid:
                hints = suggest_repair(state)

            current = WordGameAttempt(
                attempt=attempt_idx,
                candidate=candidate,
                distance=distance,
                quality=quality,
                valid=result.is_valid,
                repair_hints=hints,
            )
            self.history.append(current)
            last_attempt = current

            if current.valid or current.quality >= self.stop_on_quality:
                break

        if last_attempt is None:
            return WordGameAttempt(
                attempt=0,
                candidate="",
                distance=0,
                quality=0.0,
                valid=False,
                repair_hints=[],
            )

        return last_attempt
