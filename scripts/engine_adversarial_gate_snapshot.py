#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict

from nepsis_cgn.api.service import EngineApiService


def _check_status_map(checks: list[Dict[str, Any]]) -> Dict[str, str]:
    return {str(check.get("key")): str(check.get("status")) for check in checks}


def scenario_vague_frame() -> Dict[str, Any]:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        frame={"text": "Help?"},
    )
    sid = created["session_id"]
    audit = svc.stage_audit_session(
        sid,
        context={
            "frame": {
                "problem_statement": "Not sure, maybe this?",
            }
        },
    )
    return {
        "id": "S1-vague-frame",
        "label": "Vague frame (underdefined priors)",
        "stage_status": {
            "frame": audit["frame"]["status"],
            "interpretation": audit["interpretation"]["status"],
            "threshold": audit["threshold"]["status"],
        },
        "check_status": {
            "frame": _check_status_map(audit["frame"]["checks"]),
        },
    }


def scenario_contradiction_heavy() -> Dict[str, Any]:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={"text": "Decide escalation path."},
    )
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True, "policy_violation": False})
    audit = svc.stage_audit_session(
        sid,
        context={
            "frame": {
                "problem_statement": "Decide escalation now.",
                "catastrophic_outcome": "Miss critical incident.",
                "optimization_goal": "Protect users while reducing disruption.",
                "decision_horizon": "short",
                "key_uncertainty": "Signal quality from first report.",
                "hard_constraints": ["No policy breach"],
                "soft_constraints": ["Minimize disruption"],
            },
            "interpretation": {
                "report_text": (
                    "obs: signal strongly indicates escalation\n"
                    "obs: signal likely false positive\n"
                    "obs: team reports conflicting timelines"
                ),
                "evidence_count": 3,
                "report_synced": True,
                "contradictions_status": "declared",
                "contradictions_note": "Signal reliability and timeline evidence conflict.",
                "contradiction_density": 0.82,
            },
            "threshold": {
                "loss_treat": 1.0,
                "loss_not_treat": 9.0,
                "warning_level": "yellow",
                "gate_crossed": False,
                "recommendation": "hold",
                "decision": "hold",
                "hold_reason": "Gather one additional discriminator.",
            },
        },
    )
    return {
        "id": "S2-contradiction-heavy",
        "label": "Contradiction-heavy report",
        "stage_status": {
            "frame": audit["frame"]["status"],
            "interpretation": audit["interpretation"]["status"],
            "threshold": audit["threshold"]["status"],
        },
        "check_status": {
            "interpretation": _check_status_map(audit["interpretation"]["checks"]),
        },
    }


def scenario_forced_red_override() -> Dict[str, Any]:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={"text": "Decide escalation path."},
    )
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True, "policy_violation": False})
    audit = svc.stage_audit_session(
        sid,
        context={
            "frame": {
                "problem_statement": "Decide escalation now.",
                "catastrophic_outcome": "Miss critical incident.",
                "optimization_goal": "Protect users while reducing disruption.",
                "decision_horizon": "short",
                "key_uncertainty": "Signal quality from first report.",
                "hard_constraints": ["No policy breach"],
                "soft_constraints": ["Minimize disruption"],
            },
            "interpretation": {
                "report_text": "obs: critical signal present\nobs: no policy violation",
                "evidence_count": 2,
                "report_synced": True,
                "contradictions_status": "none_identified",
                "contradictions_note": "",
            },
            "threshold": {
                "loss_treat": 1.0,
                "loss_not_treat": 9.0,
                "warning_level": "red",
                "gate_crossed": True,
                "recommendation": "escalate",
                "decision": "recommend",
                "hold_reason": "",
            },
        },
    )
    return {
        "id": "S3-red-override-conflict",
        "label": "Forced red-override conflict",
        "stage_status": {
            "frame": audit["frame"]["status"],
            "interpretation": audit["interpretation"]["status"],
            "threshold": audit["threshold"]["status"],
        },
        "check_status": {
            "threshold": _check_status_map(audit["threshold"]["checks"]),
        },
    }


def main() -> None:
    output = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenarios": [
            scenario_vague_frame(),
            scenario_contradiction_heavy(),
            scenario_forced_red_override(),
        ],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
