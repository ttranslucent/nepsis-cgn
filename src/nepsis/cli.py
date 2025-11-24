import argparse
import json
import sys

from .core import NepsisSupervisor
from .llm import SimulatedWordGameLLM


def main():
    parser = argparse.ArgumentParser(description="Nepsis Supervisor CLI")

    # Mode selection (future expansion)
    parser.add_argument(
        "--mode",
        choices=["word_game", "python", "arc"],
        default="word_game",
        help="Manifold selection",
    )

    # Word Game arguments
    parser.add_argument("--letters", type=str, help="Letters for the word game (e.g., 'J A N I G L L')")

    # Generic arguments
    parser.add_argument("--query", type=str, help="Raw query string (for non-word-game modes)")
    parser.add_argument("--verbose", action="store_true", help="Show full JSON traces")

    args = parser.parse_args()

    # 1. Construct raw query
    if args.mode == "word_game":
        if not args.letters:
            print("Error: --letters required for word_game mode.")
            sys.exit(1)
        raw_query = args.letters
    else:
        raw_query = args.query

    if not raw_query:
        print("Error: No input provided.")
        sys.exit(1)

    # 2. Initialize supervisor with a pluggable LLM provider (simulator for now)
    llm_engine = SimulatedWordGameLLM()
    supervisor = NepsisSupervisor(llm_provider=llm_engine)

    # 3. Execute
    print(f"--- Booting Nepsis [Mode: {args.mode}] ---")
    report = supervisor.execute(raw_query, context="cli")

    # 4. Render output
    outcome = report.get("outcome", "UNKNOWN")

    if outcome == "SUCCESS":
        artifact = report.get("final_artifact", "")
        score = report.get("candidate_metrics", {}).get("blue_score", 0)
        print("\nSUCCESS")
        print(f"  Artifact: {artifact}")
        print(f"  Blue Score: {score}")
    elif outcome in {"REJECTED", "FAILURE"}:
        reason = report.get("reason", "Unknown")
        violations = report.get("candidate_metrics", {}).get("red_violations", [])
        print("\nFAILURE")
        print(f"  Reason: {reason}")
        if violations:
            print("  Violations:")
            for v in violations:
                print(f"    - {v}")
    else:
        print("\nUNKNOWN OUTCOME")
        print(json.dumps(report, indent=2))

    # 5. Dump trace if requested
    if args.verbose:
        print("\n--- JSON TRACE ---")
        print(json.dumps(supervisor.trace_log, indent=2))


if __name__ == "__main__":
    main()
