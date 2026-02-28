from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from ..core import (
    GovernanceCosts,
    NavigationController,
)
from ..core.interpretant import WordPuzzleSign
from ..core.runtime import build_navigation_controller
from ..manifolds.clinical import ClinicalSign
from ..manifolds.red_blue import SafetySign


def build_nav(
    manifest_path: Optional[str] = None,
    families: Optional[list[str]] = None,
    governance_costs: Optional[GovernanceCosts] = None,
    emit_iteration_packet: bool = False,
) -> NavigationController[Any, Any]:
    return build_navigation_controller(
        manifest_path=manifest_path,
        families=families,
        governance_costs=governance_costs,
        emit_iteration_packet=emit_iteration_packet,
    )


def _trace_payload(entry: Any) -> Dict[str, Any]:
    decision = entry.governor_decision
    evaln = entry.manifold_evaluation
    payload = {
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
        "stage": entry.trace_metadata.get("stage"),
        "stage_events": entry.trace_metadata.get("stage_events", []),
        "frame_id": entry.trace_metadata.get("frame_id"),
        "frame_version": entry.trace_metadata.get("frame_version"),
    }
    if entry.governance_decision is not None and entry.governance_metrics is not None:
        g = entry.governance_decision
        gm = entry.governance_metrics
        payload["governance"] = {
            "posture": g.posture,
            "warning_level": g.warning_level,
            "recommended_action": g.recommended_action,
            "trigger_codes": list(g.trigger_codes),
            "theta": g.theta,
            "loss_treat": g.loss_treat,
            "loss_notreat": g.loss_notreat,
            "p_bad": gm.p_bad,
            "ruin_mass": gm.ruin_mass,
            "contradiction_density": gm.contradiction_density,
            "posterior_entropy_norm": gm.posterior_entropy_norm,
            "top_margin": gm.top_margin,
            "top_p": gm.top_p,
            "user_decision": entry.trace_metadata.get("user_decision"),
            "override_reason": entry.trace_metadata.get("override_reason"),
        }
        why = entry.trace_metadata.get("why_not_converging") or []
        if why:
            payload["governance"]["why_not_converging"] = why
    if entry.iteration_packet is not None:
        payload["iteration_packet"] = entry.iteration_packet
    return payload


def _emit(entry: Any, as_json: bool) -> None:
    payload = _trace_payload(entry)
    packet_path = entry.trace_metadata.get("packet_path")
    if packet_path:
        payload["iteration_packet_path"] = packet_path
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
    nav = build_nav(
        args.manifest,
        families=["puzzle"],
        governance_costs=_governance_costs_from_args(args),
        emit_iteration_packet=bool(args.emit_packet or args.packet_dir),
    )
    sign = WordPuzzleSign(letters=args.letters, candidate=args.candidate)
    user_decision, override_reason = _user_decision_from_args(args)
    entry = nav.step(
        sign,
        commit=args.commit,
        user_decision=user_decision,
        override_reason=override_reason,
    )
    _maybe_write_packet(entry, args.packet_dir)
    _emit(entry, as_json=args.json)
    return 0


def run_clinical(args: argparse.Namespace) -> int:
    nav = build_nav(
        args.manifest,
        families=["clinical"],
        governance_costs=_governance_costs_from_args(args),
        emit_iteration_packet=bool(args.emit_packet or args.packet_dir),
    )
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
    user_decision, override_reason = _user_decision_from_args(args)
    entry = nav.step(
        sign,
        commit=args.commit,
        user_decision=user_decision,
        override_reason=override_reason,
    )
    _maybe_write_packet(entry, args.packet_dir)
    _emit(entry, as_json=args.json)
    return 0


def run_safety(args: argparse.Namespace) -> int:
    nav = build_nav(
        args.manifest,
        families=["safety"],
        governance_costs=_governance_costs_from_args(args),
        emit_iteration_packet=bool(args.emit_packet or args.packet_dir),
    )
    sign = SafetySign(
        critical_signal=args.critical_signal,
        policy_violation=args.policy_violation,
        notes=args.notes,
    )
    user_decision, override_reason = _user_decision_from_args(args)
    entry = nav.step(
        sign,
        commit=args.commit,
        user_decision=user_decision,
        override_reason=override_reason,
    )
    _maybe_write_packet(entry, args.packet_dir)
    _emit(entry, as_json=args.json)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="nepsiscgn", description="Nepsis Constraint Geometry Navigator")
    parser.add_argument(
        "--manifest",
        help="Path to manifest_definitions.yaml (defaults to repo data/manifests).",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON trace.")
    parser.add_argument(
        "--c-fp",
        type=float,
        default=None,
        help="Optional false-positive cost for governance gate.",
    )
    parser.add_argument(
        "--c-fn",
        type=float,
        default=None,
        help="Optional false-negative cost for governance gate.",
    )
    parser.add_argument(
        "--emit-packet",
        action="store_true",
        help="Emit minimal runtime iteration packet in output payload.",
    )
    parser.add_argument(
        "--packet-dir",
        default=None,
        help="Optional directory to write emitted iteration packets as JSON files.",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Advance stage to committed for this run (adds COMMIT event after EVALUATE).",
    )
    parser.add_argument(
        "--continue-override",
        action="store_true",
        help="Record governance user decision to continue despite warning.",
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Record governance user decision to stop and reframe.",
    )
    parser.add_argument(
        "--override-reason",
        default=None,
        help="Required when using --continue-override.",
    )

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


def _governance_costs_from_args(args: argparse.Namespace) -> Optional[GovernanceCosts]:
    c_fp = getattr(args, "c_fp", None)
    c_fn = getattr(args, "c_fn", None)
    if c_fp is None and c_fn is None:
        return None
    if c_fp is None or c_fn is None:
        raise ValueError("Both --c-fp and --c-fn must be provided to enable governance.")
    return GovernanceCosts(c_fp=float(c_fp), c_fn=float(c_fn))


def _user_decision_from_args(args: argparse.Namespace) -> tuple[Optional[str], Optional[str]]:
    continue_override = bool(getattr(args, "continue_override", False))
    stop = bool(getattr(args, "stop", False))
    override_reason = getattr(args, "override_reason", None)
    if continue_override and stop:
        raise ValueError("Choose either --continue-override or --stop, not both.")
    if override_reason and not continue_override:
        raise ValueError("--override-reason requires --continue-override.")
    if continue_override:
        if not override_reason:
            raise ValueError("--override-reason is required with --continue-override.")
        return "continue_override", str(override_reason)
    if stop:
        return "stop", None
    return None, None


def _maybe_write_packet(entry: Any, packet_dir: Optional[str]) -> None:
    if not packet_dir or entry.iteration_packet is None:
        return
    base = Path(packet_dir)
    base.mkdir(parents=True, exist_ok=True)
    packet = entry.iteration_packet
    iteration = int(packet["meta"]["iteration"])
    packet_id = str(packet["meta"]["packet_id"])
    out_path = base / f"iteration-{iteration:04d}_{packet_id}.json"
    out_path.write_text(json.dumps(packet, indent=2), encoding="utf-8")
    entry.trace_metadata["packet_path"] = str(out_path)


if __name__ == "__main__":
    entrypoint()
