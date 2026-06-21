from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from ..core.case_reasoning import compile_case_reasoning
from .operator_packet import (
    lock_frame,
    lock_report,
    run_report,
    set_threshold_decision_from_case_reasoning,
    start_operator_packet,
)

SCHEMA_ID = "nepsis.private_demo_runtime_packet"
SCHEMA_VERSION = "0.1.0"
RUNTIME = "nepsis-cgn.operator_packet"


def build_private_demo_runtime_packet(body: dict[str, Any]) -> dict[str, Any]:
    prompt = _prompt_text(body)
    case_id = _case_id(body)
    no_phi_acknowledged = _no_phi_acknowledged(body)

    if not no_phi_acknowledged:
        raise ValueError("no_phi_acknowledged must be true for private demo runtime runs")

    started = start_operator_packet(family="safety")
    locked = lock_frame(
        packet=started,
        family="safety",
        frame=_frame(prompt=prompt, case_id=case_id),
        governance_costs={"c_fp": 1.0, "c_fn": 9.0},
    )
    _raise_for_rejection(locked, "lock_frame")

    frame_id = _frame_id(locked)
    case_reasoning = compile_case_reasoning(
        prompt,
        case_id=case_id,
        frame_id=frame_id,
        input_prompt_hash=_prompt_hash(prompt),
    )
    report_text = _report_text(prompt=prompt, case_id=case_id, case_reasoning=case_reasoning)
    reported = run_report(
        packet=locked,
        report_text=report_text,
        sign={
            "critical_signal": True,
            "policy_violation": False,
            "notes": f"Private demo no-PHI prompt hash {_prompt_hash(prompt)}.",
        },
        interpretation=_interpretation(
            prompt=prompt,
            case_id=case_id,
            report_text=report_text,
            case_reasoning=case_reasoning,
        ),
    )
    _raise_for_rejection(reported, "run_report")

    report_locked = lock_report(packet=reported)
    _raise_for_rejection(report_locked, "lock_report")

    threshold = set_threshold_decision_from_case_reasoning(packet=report_locked)
    _raise_for_rejection(threshold, "set_threshold_decision")

    return {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "runtime": RUNTIME,
        "mode": "external-private-runtime",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "case_id": case_id,
        "thread_id": _optional_string(body.get("thread_id", body.get("threadId"))),
        "user_id": _optional_string(body.get("user_id", body.get("userId"))),
        "no_phi_acknowledged": True,
        "prompt_hash": _prompt_hash(prompt),
        "prompt_excerpt": _excerpt(prompt),
        "summary": (
            "NepsisCGN private runtime completed a RED before BLUE operator-packet "
            "pass and thresholded a validated Case Reasoning Compiler packet."
        ),
        "case_reasoning_compiler": _latest_case_reasoning(threshold) or case_reasoning,
        "operator_packet": threshold,
        "audit_trace": threshold.get("audit_trace", []),
        "latest_audit": threshold.get("latest_audit", {}),
    }


def _prompt_text(body: dict[str, Any]) -> str:
    value = body.get("prompt", body.get("input_text", body.get("inputText")))

    if not isinstance(value, str):
        raise ValueError("private demo runtime requires string field 'prompt' or 'input_text'")

    prompt = value.strip()

    if len(prompt) < 3:
        raise ValueError("private demo runtime prompt must be at least 3 characters")

    if len(prompt) > 12000:
        raise ValueError("private demo runtime prompt must be 12000 characters or fewer")

    return prompt


def _case_id(body: dict[str, Any]) -> str:
    value = body.get("case_id", body.get("caseId", "custom"))

    if value is None:
        return "custom"

    if not isinstance(value, str):
        raise ValueError("case_id must be a string when provided")

    case_id = value.strip().lower()
    return case_id or "custom"


def _no_phi_acknowledged(body: dict[str, Any]) -> bool:
    value = body.get("no_phi_acknowledged", body.get("noPhiAcknowledged", False))
    return value is True


def _frame(*, prompt: str, case_id: str) -> dict[str, Any]:
    return {
        "text": f"Private demo case '{case_id}': {prompt}",
        "objective_type": "sensemake",
        "domain": "safety",
        "time_horizon": "short",
        "rationale_for_change": (
            "Red channel: preserve no-PHI boundary, source facts, and must-not-miss constraints | "
            "Blue channel: organize a bounded interpretation only after RED is explicit | "
            "Uncertainty: outside tester input may be incomplete or contain hidden frame errors"
        ),
        "constraints_hard": [
            "No PHI or patient-identifiable data.",
            "Preserve RED before BLUE ordering.",
            "Preserve source facts exactly; do not collapse contradictory tokens.",
            "Do not present the output as clinical advice or an autonomous recommendation.",
        ],
        "constraints_soft": [
            "Keep the packet readable for tester and operator review.",
            "Prefer hold/review when uncertainty remains material.",
        ],
    }


def _report_text(*, prompt: str, case_id: str, case_reasoning: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"case_id: {case_id}",
            f"prompt_hash: {_prompt_hash(prompt)}",
            "input_boundary: user affirmed no PHI before the front-door run",
            f"red_channel_question: {case_reasoning.get('red_channel_question', '')}",
            f"domain_red_hazard: {_domain_hazard_label(case_reasoning)}",
            f"red_status: {case_reasoning.get('current_red_status', '')}",
            f"decision_reason: {case_reasoning.get('decision_reason', '')}",
        ]
    )


def _interpretation(
    *,
    prompt: str,
    case_id: str,
    report_text: str,
    case_reasoning: dict[str, Any],
) -> dict[str, Any]:
    has_jingall = "jingall" in prompt.lower()
    has_jailing = "jailing" in prompt.lower()
    contradiction_declared = has_jingall and has_jailing

    return {
        "case_id": case_id,
        "case_reasoning_source_text": prompt,
        "input_prompt_hash": _prompt_hash(prompt),
        "case_reasoning": case_reasoning,
        "report_text": report_text,
        "evidence_count": len([line for line in report_text.splitlines() if line.strip()]),
        "report_synced": True,
        "contradictions_status": "declared" if contradiction_declared else "none_identified",
        "contradictions_note": (
            "Prompt includes both JINGALL and JAILING; preserve the source-token mismatch for review."
            if contradiction_declared
            else ""
        ),
        "contradiction_density": 0.2 if contradiction_declared else 0.0,
    }


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]


def _excerpt(prompt: str) -> str:
    normalized = " ".join(prompt.split())

    if len(normalized) <= 240:
        return normalized

    return f"{normalized[:240]}..."


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    resolved = value.strip()
    return resolved or None


def _frame_id(packet: dict[str, Any]) -> str:
    frame = packet.get("frame")
    if isinstance(frame, dict) and isinstance(frame.get("frame_id"), str):
        return frame["frame_id"]
    raise ValueError("private demo runtime lock_frame failed to return frame_id")


def _domain_hazard_label(case_reasoning: dict[str, Any]) -> str:
    hazard = case_reasoning.get("domain_red_hazard")
    if isinstance(hazard, dict) and isinstance(hazard.get("hazard"), str):
        return hazard["hazard"]
    return ""


def _latest_case_reasoning(packet: dict[str, Any]) -> dict[str, Any] | None:
    latest = packet.get("latest_audit")
    if not isinstance(latest, dict):
        return None
    interpretation = latest.get("interpretation")
    if not isinstance(interpretation, dict):
        return None
    stage_packet = interpretation.get("packet")
    if not isinstance(stage_packet, dict):
        return None
    compiler = stage_packet.get("case_reasoning")
    return compiler if isinstance(compiler, dict) else None


def _raise_for_rejection(packet: dict[str, Any], step: str) -> None:
    if packet.get("schema_id") == "nepsis.phase_rejection":
        missing = packet.get("missing")
        reason = ", ".join(str(item) for item in missing) if isinstance(missing, list) else "phase rejection"
        raise ValueError(f"private demo runtime {step} failed: {reason}")
