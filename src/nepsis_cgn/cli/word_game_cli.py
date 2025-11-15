from __future__ import annotations

import argparse

from ..core.solver import CGNSolver
from ..puzzles.word_game import (
    WordGameState,
    build_word_game_constraint_set,
    suggest_repair,
    compute_distance_from_validity,
    compute_quality_score,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="NepsisCGN word puzzle constraint checker."
    )
    parser.add_argument(
        "--letters",
        type=str,
        required=True,
        help="Available letters, e.g. GINGALJ",
    )
    parser.add_argument(
        "--candidate",
        type=str,
        required=True,
        help="Candidate word to evaluate, e.g. GINGAL",
    )
    args = parser.parse_args()

    state = WordGameState(letters=args.letters, candidate=args.candidate)
    constraint_set = build_word_game_constraint_set()
    solver = CGNSolver(constraint_set=constraint_set)

    result = solver.evaluate_state(state)
    distance = compute_distance_from_validity(state)
    quality = compute_quality_score(state)

    print(f"State: {result.state_description}")
    print(f"Constraint set: {result.metadata['constraint_set']}")
    print(f"Valid: {result.is_valid}")
    print(f"Distance from validity: {distance}")
    print(f"Quality score: {quality:.3f}")
    print(f"Violations ({len(result.violations)}):")
    for v in result.violations:
        print(f"  - [{v.severity.upper()}] {v.code}: {v.message}")

    if not result.is_valid:
        hints = suggest_repair(state)
        if hints:
            print("\nRepair hints:")
            for hint in hints:
                print(f"  * {hint}")
        else:
            print("\nNo repair hints available.")


if __name__ == "__main__":
    main()
