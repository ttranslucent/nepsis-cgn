from __future__ import annotations

import argparse
from typing import Any, List

from ..integration.llm_word_sidecar import LLMClient, WordGameLLMSession


class DummyLLM(LLMClient):
    """Fake LLM that cycles through a fixed list of candidates."""

    def __init__(self, candidates: List[str]):
        self.candidates = candidates
        self.index = 0

    def generate(self, prompt: str, **kwargs: Any) -> str:
        # Real LLMs would ignore this and hit an API.
        candidate = (
            self.candidates[self.index]
            if self.index < len(self.candidates)
            else self.candidates[-1]
        )
        self.index += 1

        print("\n=== DummyLLM prompt ===")
        print(prompt)
        print("=== DummyLLM response ===")
        print(candidate)
        print("========================\n")

        return candidate


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NepsisCGN word puzzle LLM sidecar demo."
    )
    parser.add_argument(
        "--letters",
        type=str,
        required=True,
        help="Available letters, e.g. JANIGLL",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum number of LLM attempts.",
    )
    args = parser.parse_args()

    dummy_llm = DummyLLM(candidates=["JAILING", "GINGAL", "JINGALL"])

    session = WordGameLLMSession(
        letters=args.letters,
        llm=dummy_llm,
        max_attempts=args.max_attempts,
        stop_on_quality=1.0,
    )

    final = session.run()

    print("=== Final Attempt ===")
    print(f"Attempt #: {final.attempt}")
    print(f"Candidate: {final.candidate}")
    print(f"Valid:     {final.valid}")
    print(f"Distance:  {final.distance}")
    print(f"Quality:   {final.quality:.3f}")
    if final.repair_hints:
        print("Repair hints:")
        for hint in final.repair_hints:
            print(f"  * {hint}")

    print("\n=== Full History ===")
    for attempt in session.history:
        print(
            f"[{attempt.attempt}] '{attempt.candidate}' → valid={attempt.valid}, "
            f"distance={attempt.distance}, quality={attempt.quality:.3f}"
        )
        if attempt.repair_hints and not attempt.valid:
            for hint in attempt.repair_hints:
                print(f"   - {hint}")


if __name__ == "__main__":
    main()
