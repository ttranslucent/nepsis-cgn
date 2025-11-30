import argparse
import json
import sys

from .core import NepsisSupervisor
from .llm import get_llm_provider
from .manifolds import UTF8HiddenManifold, WordGameManifold


def main():
    parser = argparse.ArgumentParser(description="Nepsis Supervisor CLI")

    # Mode selection (future expansion)
    parser.add_argument(
        "--mode",
        choices=["word_game", "utf8", "seed", "arc", "arc_attach", "python"],
        default="word_game",
        help="Manifold selection",
    )

    # Word Game arguments
    parser.add_argument("--letters", type=str, help="Letters for the word game (e.g., 'J A N I G L L')")
    # UTF8 arguments
    parser.add_argument("--target", type=str, help="Target phrase for utf8 hidden mode (default: NEPSIS)")
    parser.add_argument("--candidate", type=str, help="Raw candidate text for seed manifold (default: OK)")

    # Generic arguments
    parser.add_argument("--query", type=str, help="Raw query string (for non-word-game modes)")
    parser.add_argument(
        "--model",
        type=str,
        choices=["simulated", "openai"],
        default="simulated",
        help="Model provider name (e.g., simulated, openai)",
    )
    parser.add_argument("--verbose", action="store_true", help="Show full JSON traces")

    args = parser.parse_args()

    # 1. Construct raw query
    if args.mode == "word_game":
        if not args.letters:
            print("Error: --letters required for word_game mode.")
            sys.exit(1)
        raw_query = args.letters
    elif args.mode == "utf8":
        raw_query = args.target or "NEPSIS"
    elif args.mode == "seed":
        raw_query = args.candidate or "OK"
    elif args.mode == "arc":
        raw_query = args.query or "[[0,0,0],[0,1,0],[0,0,0],[2,2,2]]"
    elif args.mode == "arc_attach":
        raw_query = args.query
    else:
        raw_query = args.query

    if not raw_query:
        print("Error: No input provided.")
        sys.exit(1)

    # 2. Initialize manifold
    if args.mode == "word_game":
        manifold = WordGameManifold()
    elif args.mode == "utf8":
        manifold = UTF8HiddenManifold(target_phrase=raw_query)
    elif args.mode == "seed":
        from .manifolds import SeedManifold

        manifold = SeedManifold()
    elif args.mode == "arc":
        from .manifolds import GravityRoomManifold

        manifold = GravityRoomManifold()
    elif args.mode == "arc_attach":
        from .manifolds import ArcAttachManifold

        manifold = ArcAttachManifold()
    else:
        print(f"Error: Mode '{args.mode}' not yet implemented.")
        sys.exit(1)

    # 3. Initialize LLM provider (credentialed via env)
    try:
        llm_engine = get_llm_provider(args.model)
    except Exception as exc:
        print(f"Error initializing model '{args.model}': {exc}")
        sys.exit(1)

    supervisor = NepsisSupervisor(default_manifold=manifold, llm_provider=llm_engine)

    # 4. Execute
    print(f"--- Booting Nepsis [Mode: {args.mode}] ---")
    report = supervisor.execute(raw_query, context="cli")

    # 5. Render output
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

    # 6. Dump trace if requested
    if args.verbose:
        print("\n--- JSON TRACE ---")
        print(json.dumps(supervisor.trace_log, indent=2))


if __name__ == "__main__":
    main()
