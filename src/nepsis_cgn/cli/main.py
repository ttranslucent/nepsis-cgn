from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from ..core import (
    NavigationController,
    build_governor_configs,
    build_interpretants_from_spec,
    load_manifest_spec,
)
from ..core.interpretant import WordPuzzleSign
from ..manifolds.clinical import ClinicalSign
from ..manifolds.red_blue import SafetySign
from ..core import InterpretantManager


def _default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "manifests" / "manifest_definitions.yaml"


def build_nav(manifest_path: Optional[str] = None, families: Optional[list[str]] = None) -> NavigationController[Any, Any]:
    path = Path(manifest_path) if manifest_path else _default_manifest_path()
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found at {path}")
    spec = load_manifest_spec(str(path))
    hypotheses = build_interpretants_from_spec(spec, families=families)
    gov_configs = build_governor_configs(spec, families=families)
    manager = InterpretantManager(hypotheses)
    return NavigationController(manager, governor_configs=gov_configs)


def _trace_payload(entry: Any) -> Dict[str, Any]:
    decision = entry.governor_decision
    evaln = entry.manifold_evaluation
    return {
        "manifold": evaln.manifold_id,
        "family": evaln.family,
        "decision": decision.decision,
        "cause": decision.cause,
        "tension": decision.metrics.tension,
        "velocity": decision.metrics.velocity,
        "accel": decision.metrics.accel,
        "posterior": entry.posterior,
        "ruin_hits": evaln.ruin_hits,
        "active_transforms": evaln.active_transforms,
        "is_ruin": evaln.is_ruin,
        "violation_count": len(evaln.result.violations),
    }


def _emit(entry: Any, as_json: bool) -> None:
    payload = _trace_payload(entry)
    if as_json:
        print(json.dumps(payload))
        return
    print(f"manifold={payload['manifold']} family={payload['family']}")
    print(f"decision={payload['decision']} cause={payload['cause']}")
    print(f"tension={payload['tension']} velocity={payload['velocity']} accel={payload['accel']}")
    print(f"posterior={payload['posterior']}")
    if payload["ruin_hits"]:
        print(f"ruin_hits={payload['ruin_hits']}")


def run_puzzle(args: argparse.Namespace) -> int:
    nav = build_nav(args.manifest, families=["puzzle"])
    sign = WordPuzzleSign(letters=args.letters, candidate=args.candidate)
    entry = nav.step(sign)
    _emit(entry, as_json=args.json)
    return 0


def run_clinical(args: argparse.Namespace) -> int:
    nav = build_nav(args.manifest, families=["clinical"])
    sign = ClinicalSign(
        radicular_pain=args.radicular_pain,
        spasm_present=args.spasm_present,
        saddle_anesthesia=args.saddle_anesthesia,
        bladder_dysfunction=args.bladder_dysfunction,
        bilateral_weakness=args.bilateral_weakness,
        progression=args.progression,
        fever=args.fever,
        notes=args.notes,
    )
    entry = nav.step(sign)
    _emit(entry, as_json=args.json)
    return 0


def run_safety(args: argparse.Namespace) -> int:
    nav = build_nav(args.manifest, families=["safety"])
    sign = SafetySign(
        critical_signal=args.critical_signal,
        policy_violation=args.policy_violation,
        notes=args.notes,
    )
    entry = nav.step(sign)
    _emit(entry, as_json=args.json)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="nepsiscgn", description="Nepsis Constraint Geometry Navigator")
    parser.add_argument(
        "--manifest",
        help="Path to manifest_definitions.yaml (defaults to repo data/manifests).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON trace.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_puzzle = subparsers.add_parser("puzzle", help="Run word puzzle manifold selection.")
    p_puzzle.add_argument("--letters", required=True, help="Source letter multiset, e.g. JAIILUNG.")
    p_puzzle.add_argument("--candidate", required=True, help="Candidate word.")
    p_puzzle.set_defaults(func=run_puzzle)

    p_clin = subparsers.add_parser("clinical", help="Run clinical manifold selection.")
    p_clin.add_argument("--radicular-pain", action="store_true", dest="radicular_pain", help="Radicular pain present.")
    p_clin.add_argument("--spasm-present", action="store_true", dest="spasm_present", help="Spasm present.")
    p_clin.add_argument("--saddle-anesthesia", action="store_true", help="Saddle anesthesia present.")
    p_clin.add_argument("--bladder-dysfunction", action="store_true", help="Bladder dysfunction present.")
    p_clin.add_argument("--bilateral-weakness", action="store_true", help="Bilateral weakness present.")
    p_clin.add_argument("--progression", action="store_true", help="Symptoms progressing.")
    p_clin.add_argument("--fever", action="store_true", help="Fever present.")
    p_clin.add_argument("--notes", help="Free-text clinical notes.", default=None)
    p_clin.set_defaults(func=run_clinical)

    p_safety = subparsers.add_parser("safety", help="Run safety red/blue channel selection.")
    p_safety.add_argument("--critical-signal", action="store_true", help="Critical signal detected.")
    p_safety.add_argument("--policy-violation", action="store_true", help="Policy violation detected.")
    p_safety.add_argument("--notes", help="Context notes.", default=None)
    p_safety.set_defaults(func=run_safety)

    args = parser.parse_args(argv)
    return args.func(args)


def entrypoint() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
