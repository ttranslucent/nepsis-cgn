from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .service import EngineApiService, Family

SCHEMA_ID = "nepsis.operator_packet"
SCHEMA_VERSION = "2.1.0"
INTEGRITY_SEAL_VERSION = "hmac-sha256:v1"
POLICY = {
    "name": "nepsis_cgn.stateless_operator_packet",
    "version": "2026-05-22",
    "model_cost_owner": "user_model_host",
    "server_retention": "none",
}
_COMMIT_REQUIRED_TRACE_EVENTS = ["LOCK_FRAME", "RUN_REPORT", "LOCK_REPORT", "SET_THRESHOLD_DECISION"]
_DEVELOPMENT_SEAL_SECRET = secrets.token_bytes(32)

_DEFAULT_FRAME = {
    "text": "Operator session draft.",
    "objective_type": "sensemake",
    "domain": "safety",
    "time_horizon": "short",
    "rationale_for_change": (
        "Red channel: keep irreversible bad outcomes explicit | "
        "Blue channel: optimize after red boundaries are controlled | "
        "Uncertainty: the operator has not locked the frame yet"
    ),
    "constraints_hard": ["Maintain RED before BLUE sequencing."],
    "constraints_soft": ["Keep the audit trace concise."],
}
_DEFAULT_GOVERNANCE = {"c_fp": 1.0, "c_fn": 9.0}
_LEGAL_NEXT: dict[str, list[str]] = {
    "frame_draft": ["start_operator_packet", "lock_frame", "abandon_packet"],
    "frame_locked": ["run_report", "abandon_packet"],
    "report_evaluated": ["run_report", "lock_report", "abandon_packet"],
    "report_locked": ["set_threshold_decision", "abandon_packet"],
    "threshold_set": ["commit_iteration", "abandon_packet"],
}
_STATEFUL_TO_STATELESS_TOOL = {
    "get_session_state": "start_operator_packet",
    "abandon_session": "abandon_packet",
}


class PacketReplayError(ValueError):
    pass


def start_operator_packet(
    *,
    family: Family = "safety",
    frame: dict[str, Any] | None = None,
    governance_costs: dict[str, Any] | None = None,
    governance_calibration: dict[str, Any] | None = None,
    manifest_path: str | None = None,
) -> dict[str, Any]:
    if family not in {"puzzle", "clinical", "safety"}:
        raise ValueError("family must be one of: puzzle, clinical, safety")
    resolved_frame = _json_copy(frame) if frame is not None else _json_copy(_DEFAULT_FRAME)
    resolved_governance = (
        _json_copy(governance_costs) if governance_costs is not None else _json_copy(_DEFAULT_GOVERNANCE)
    )
    return _packet(
        loop_id=str(uuid4()),
        phase="frame_draft",
        family=family,
        frame=resolved_frame,
        governance_costs=resolved_governance,
        governance_calibration=_json_copy(governance_calibration),
        manifest_path=manifest_path,
        audit_trace=[],
        latest_audit={},
        latest_step=None,
        last_commit_packet=None,
        last_abandoned_packet=None,
    )


def lock_frame(
    *,
    packet: dict[str, Any],
    frame: dict[str, Any],
    family: Family | None = None,
    governance_costs: dict[str, Any] | None = None,
    governance_calibration: dict[str, Any] | None = None,
    manifest_path: str | None = None,
) -> dict[str, Any]:
    svc = _service_from_packet(packet)
    resolved_family = family or _packet_family(packet)
    resolved_governance = governance_costs if governance_costs is not None else _packet_governance(packet)
    resolved_calibration = (
        governance_calibration if governance_calibration is not None else _packet_calibration(packet)
    )
    resolved_manifest = manifest_path if manifest_path is not None else _packet_manifest_path(packet)
    result = svc.operator_lock_frame(
        family=resolved_family,
        frame=frame,
        governance_costs=resolved_governance,
        governance_calibration=resolved_calibration,
        manifest_path=resolved_manifest,
    )
    if _is_rejection(result):
        return _stateless_rejection(result)
    trace = _append_trace(
        packet,
        "LOCK_FRAME",
        {
            "family": resolved_family,
            "frame": frame,
            "governance_costs": resolved_governance,
            "governance_calibration": resolved_calibration,
            "manifest_path": resolved_manifest,
        },
    )
    return _packet_from_transition(packet, result, trace)


def run_report(
    *,
    packet: dict[str, Any],
    report_text: str,
    sign: dict[str, Any],
    interpretation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    svc = _service_from_packet(packet)
    result = svc.operator_run_report(report_text=report_text, sign=sign, interpretation=interpretation)
    if _is_rejection(result):
        return _stateless_rejection(result)
    trace = _append_trace(
        packet,
        "RUN_REPORT",
        {"report_text": report_text, "sign": sign, "interpretation": interpretation},
    )
    return _packet_from_transition(packet, result, trace)


def lock_report(*, packet: dict[str, Any]) -> dict[str, Any]:
    svc = _service_from_packet(packet)
    result = svc.operator_lock_report()
    if _is_rejection(result):
        return _stateless_rejection(result)
    trace = _append_trace(packet, "LOCK_REPORT", {})
    return _packet_from_transition(packet, result, trace)


def set_threshold_decision(
    *,
    packet: dict[str, Any],
    decision: str,
    hold_reason: str = "",
) -> dict[str, Any]:
    svc = _service_from_packet(packet)
    result = svc.operator_set_threshold_decision(decision=decision, hold_reason=hold_reason)
    if _is_rejection(result):
        return _stateless_rejection(result)
    trace = _append_trace(packet, "SET_THRESHOLD_DECISION", {"decision": decision, "hold_reason": hold_reason})
    return _packet_from_transition(packet, result, trace)


def commit_iteration(
    *,
    packet: dict[str, Any],
    carry_forward_frame: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if _packet_phase(packet) == "threshold_set":
        missing_events = _missing_commit_trace_events(packet)
        if missing_events:
            return _local_rejection(
                attempted_tool="commit_iteration",
                current_phase="threshold_set",
                failed_precondition="audit_trace_required",
                missing=missing_events,
                coach_prompts=["Commit requires the packet trace to prove each prior operator gate."],
            )
    svc = _service_from_packet(packet)
    result = svc.operator_commit_iteration(carry_forward_frame=carry_forward_frame)
    if _is_rejection(result):
        return _stateless_rejection(result)
    trace = _append_trace(packet, "COMMIT_ITERATION", {"carry_forward_frame": carry_forward_frame})
    committed_packet = _json_copy(result.get("packet"))
    session = _transition_session(result)
    return _packet(
        loop_id=_packet_loop_id(packet),
        phase=str(result.get("phase") or "frame_draft"),
        family=str(session.get("family") or _packet_family(packet)),
        frame=_json_copy(session.get("frame") or _packet_frame(packet)),
        governance_costs=_json_copy(session.get("governance") or _packet_governance(packet)),
        governance_calibration=_json_copy(session.get("calibration") or _packet_calibration(packet)),
        manifest_path=session.get("manifest_path") if isinstance(session.get("manifest_path"), str) else _packet_manifest_path(packet),
        audit_trace=[],
        latest_audit=_json_copy(result.get("audit") or {}),
        latest_step=None,
        last_commit_packet=committed_packet,
        last_abandoned_packet=_json_copy(packet.get("last_abandoned_packet")),
        previous_trace=trace,
    )


def abandon_packet(*, packet: dict[str, Any], reason: str = "") -> dict[str, Any]:
    svc = _service_from_packet(packet)
    result = svc.operator_abandon_session(reason=reason)
    abandoned = _json_copy(result.get("packet"))
    started = start_operator_packet(
        family=_packet_family(packet),
        frame=_packet_frame(packet),
        governance_costs=_packet_governance(packet),
        governance_calibration=_packet_calibration(packet),
        manifest_path=_packet_manifest_path(packet),
    )
    started["loop_id"] = _packet_loop_id(packet)
    started["last_commit_packet"] = _json_copy(packet.get("last_commit_packet"))
    started["last_abandoned_packet"] = abandoned
    started["previous_trace"] = _append_trace(packet, "ABANDON_PACKET", {"reason": reason})
    return started


def inspect_operator_packet(packet: dict[str, Any] | None = None) -> dict[str, Any]:
    if packet is None:
        resolved = start_operator_packet()
    else:
        _validate_packet(packet)
        resolved = packet
    return {
        "schema_id": "nepsis.operator_packet_state",
        "loop_id": _packet_loop_id(resolved),
        "phase": _packet_phase(resolved),
        "legal_next_tools": _legal_next_tools(_packet_phase(resolved)),
        "audit_trace": _json_copy(resolved.get("audit_trace")) or [],
        "latest_audit": _json_copy(resolved.get("latest_audit")) or {},
        "packet_hash": packet_hash(resolved),
    }


def packet_hash(packet: dict[str, Any] | None) -> str | None:
    if not isinstance(packet, dict):
        return None
    raw = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _packet(
    *,
    loop_id: str,
    phase: str,
    family: str,
    frame: dict[str, Any] | None,
    governance_costs: dict[str, Any] | None,
    governance_calibration: dict[str, Any] | None,
    manifest_path: str | None,
    audit_trace: list[dict[str, Any]],
    latest_audit: dict[str, Any],
    latest_step: dict[str, Any] | None,
    last_commit_packet: dict[str, Any] | None,
    last_abandoned_packet: dict[str, Any] | None,
    previous_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    packet = {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "packet_id": str(uuid4()),
        "loop_id": loop_id,
        "created_at": _now(),
        "phase": phase,
        "family": family,
        "frame": _json_copy(frame),
        "governance_costs": _json_copy(governance_costs),
        "governance_calibration": _json_copy(governance_calibration),
        "manifest_path": manifest_path,
        "audit_trace": _json_copy(audit_trace) or [],
        "legal_next_tools": _legal_next_tools(phase),
        "latest_audit": _json_copy(latest_audit) or {},
        "latest_step": _json_copy(latest_step),
        "last_commit_packet": _json_copy(last_commit_packet),
        "last_abandoned_packet": _json_copy(last_abandoned_packet),
        "previous_trace": _json_copy(previous_trace) or [],
        "policy": dict(POLICY),
    }
    return _seal_packet(packet)


def _packet_from_transition(
    previous: dict[str, Any],
    result: dict[str, Any],
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    session = _transition_session(result)
    phase = str(result.get("phase") or session.get("operator_phase") or _packet_phase(previous))
    return _packet(
        loop_id=_packet_loop_id(previous),
        phase=phase,
        family=str(session.get("family") or _packet_family(previous)),
        frame=_json_copy(session.get("frame") or _packet_frame(previous)),
        governance_costs=_json_copy(session.get("governance") or _packet_governance(previous)),
        governance_calibration=_json_copy(session.get("calibration") or _packet_calibration(previous)),
        manifest_path=session.get("manifest_path") if isinstance(session.get("manifest_path"), str) else _packet_manifest_path(previous),
        audit_trace=trace,
        latest_audit=_json_copy(result.get("audit") or previous.get("latest_audit") or {}),
        latest_step=_json_copy(result.get("step")),
        last_commit_packet=_json_copy(previous.get("last_commit_packet")),
        last_abandoned_packet=_json_copy(previous.get("last_abandoned_packet")),
    )


def _service_from_packet(packet: dict[str, Any]) -> EngineApiService:
    _validate_packet(packet)
    svc = EngineApiService(store_path="", record_provenance=False)
    for entry in _packet_trace(packet):
        event = entry.get("event")
        args = entry.get("arguments")
        if not isinstance(event, str) or not isinstance(args, dict):
            raise PacketReplayError("operator packet audit_trace entries require event and arguments")
        result = _replay_event(svc, event, args)
        if _is_rejection(result):
            raise PacketReplayError(f"operator packet trace is not replayable at {event}: {result}")
    return svc


def _replay_event(svc: EngineApiService, event: str, args: dict[str, Any]) -> dict[str, Any]:
    if event == "LOCK_FRAME":
        return svc.operator_lock_frame(
            family=args.get("family", "safety"),
            frame=args.get("frame") or {},
            governance_costs=args.get("governance_costs"),
            governance_calibration=args.get("governance_calibration"),
            manifest_path=args.get("manifest_path"),
        )
    if event == "RUN_REPORT":
        return svc.operator_run_report(
            report_text=str(args.get("report_text") or ""),
            sign=args.get("sign") or {},
            interpretation=args.get("interpretation"),
        )
    if event == "LOCK_REPORT":
        return svc.operator_lock_report()
    if event == "SET_THRESHOLD_DECISION":
        return svc.operator_set_threshold_decision(
            decision=str(args.get("decision") or ""),
            hold_reason=str(args.get("hold_reason") or ""),
        )
    if event in {"COMMIT_ITERATION", "ABANDON_PACKET"}:
        return svc.get_operator_session_state()
    raise PacketReplayError(f"unsupported operator packet trace event: {event}")


def _append_trace(packet: dict[str, Any], event: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    trace = _packet_trace(packet)
    trace.append({"event": event, "at": _now(), "arguments": _json_copy(arguments) or {}})
    return trace


def _validate_packet(packet: dict[str, Any]) -> None:
    if not isinstance(packet, dict):
        raise ValueError("operator packet must be an object")
    if packet.get("schema_id") != SCHEMA_ID:
        raise ValueError("operator packet schema_id must be nepsis.operator_packet")
    if packet.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"operator packet schema_version must be {SCHEMA_VERSION}")
    trace = packet.get("audit_trace")
    if not isinstance(trace, list):
        raise ValueError("operator packet audit_trace must be a list")
    max_trace = _operator_packet_max_trace_events()
    if len(trace) > max_trace:
        raise ValueError(f"operator packet audit_trace exceeds configured maximum of {max_trace} events")
    _verify_packet_integrity(packet)


def _transition_session(result: dict[str, Any]) -> dict[str, Any]:
    session = result.get("session")
    return session if isinstance(session, dict) else {}


def _is_rejection(result: dict[str, Any]) -> bool:
    return result.get("schema_id") == "nepsis.phase_rejection"


def _stateless_rejection(result: dict[str, Any]) -> dict[str, Any]:
    rejection = _json_copy(result) or {}
    phase = str(rejection.get("current_phase") or "frame_draft")
    rejection["legal_next_tools"] = _legal_next_tools(phase)
    if isinstance(rejection.get("attempted_tool"), str):
        rejection["attempted_tool"] = _stateful_to_stateless_tool(rejection["attempted_tool"])
    return rejection


def _local_rejection(
    *,
    attempted_tool: str,
    current_phase: str,
    failed_precondition: str,
    missing: list[str],
    coach_prompts: list[str],
) -> dict[str, Any]:
    return {
        "schema_id": "nepsis.phase_rejection",
        "schema_version": "1.0.0",
        "attempted_tool": attempted_tool,
        "failed_precondition": failed_precondition,
        "current_phase": current_phase,
        "legal_next_tools": _legal_next_tools(current_phase),
        "gate_status": "BLOCK",
        "missing": missing,
        "coach_prompts": coach_prompts,
    }


def _missing_commit_trace_events(packet: dict[str, Any]) -> list[str]:
    events = [entry.get("event") for entry in _packet_trace(packet) if isinstance(entry, dict)]
    return [event for event in _COMMIT_REQUIRED_TRACE_EVENTS if event not in events]


def _legal_next_tools(phase: str) -> list[str]:
    return list(_LEGAL_NEXT.get(phase, _LEGAL_NEXT["frame_draft"]))


def _stateful_to_stateless_tool(name: str) -> str:
    return _STATEFUL_TO_STATELESS_TOOL.get(name, name)


def _packet_trace(packet: dict[str, Any]) -> list[dict[str, Any]]:
    trace = packet.get("audit_trace")
    if not isinstance(trace, list):
        raise ValueError("operator packet audit_trace must be a list")
    return _json_copy(trace) or []


def _packet_loop_id(packet: dict[str, Any]) -> str:
    value = packet.get("loop_id")
    return value if isinstance(value, str) and value else str(uuid4())


def _packet_phase(packet: dict[str, Any]) -> str:
    value = packet.get("phase")
    return value if isinstance(value, str) and value in _LEGAL_NEXT else "frame_draft"


def _packet_family(packet: dict[str, Any]) -> Family:
    value = packet.get("family")
    return value if value in {"puzzle", "clinical", "safety"} else "safety"


def _packet_frame(packet: dict[str, Any]) -> dict[str, Any]:
    frame = packet.get("frame")
    return _json_copy(frame) if isinstance(frame, dict) else _json_copy(_DEFAULT_FRAME)


def _packet_governance(packet: dict[str, Any]) -> dict[str, Any] | None:
    governance = packet.get("governance_costs")
    return _json_copy(governance) if isinstance(governance, dict) else _json_copy(_DEFAULT_GOVERNANCE)


def _packet_calibration(packet: dict[str, Any]) -> dict[str, Any] | None:
    calibration = packet.get("governance_calibration")
    return _json_copy(calibration) if isinstance(calibration, dict) else None


def _packet_manifest_path(packet: dict[str, Any]) -> str | None:
    value = packet.get("manifest_path")
    return value if isinstance(value, str) and value else None


def _json_copy(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, sort_keys=True))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _seal_packet(packet: dict[str, Any]) -> dict[str, Any]:
    sealed = _json_copy(packet) or {}
    counter = _packet_integrity_counter(sealed)
    sealed["integrity"] = {
        "seal_version": INTEGRITY_SEAL_VERSION,
        "counter": counter,
        "sealed_fields": sorted(sealed.keys()),
        "seal": _packet_integrity_seal(sealed, counter),
    }
    return sealed


def _verify_packet_integrity(packet: dict[str, Any]) -> None:
    integrity = packet.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("operator packet integrity seal is required")
    seal = integrity.get("seal")
    counter = integrity.get("counter")
    if integrity.get("seal_version") != INTEGRITY_SEAL_VERSION:
        raise ValueError("operator packet integrity seal_version is unsupported")
    if not isinstance(seal, str) or not seal:
        raise ValueError("operator packet integrity seal is required")
    if not isinstance(counter, int) or counter < 0:
        raise ValueError("operator packet integrity counter must be a non-negative integer")
    expected_counter = _packet_integrity_counter(packet)
    if counter != expected_counter:
        raise ValueError("operator packet integrity counter does not match packet trace state")
    expected = _packet_integrity_seal(packet, counter)
    if not hmac.compare_digest(seal, expected):
        raise ValueError("operator packet integrity seal verification failed")


def _packet_integrity_payload(packet: dict[str, Any], counter: int) -> bytes:
    body = {key: value for key, value in packet.items() if key != "integrity"}
    payload = {"counter": counter, "packet": body}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _packet_integrity_seal(packet: dict[str, Any], counter: int) -> str:
    return hmac.new(
        _operator_packet_seal_secret(),
        _packet_integrity_payload(packet, counter),
        hashlib.sha256,
    ).hexdigest()


def _packet_integrity_counter(packet: dict[str, Any]) -> int:
    trace = packet.get("audit_trace")
    if isinstance(trace, list) and trace:
        return len(trace)
    previous_trace = packet.get("previous_trace")
    if isinstance(previous_trace, list) and previous_trace:
        return len(previous_trace)
    return 0


def _operator_packet_max_trace_events() -> int:
    raw = os.getenv("NEPSIS_OPERATOR_PACKET_MAX_TRACE_EVENTS", "64")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("NEPSIS_OPERATOR_PACKET_MAX_TRACE_EVENTS must be an integer") from exc
    if value <= 0:
        raise ValueError("NEPSIS_OPERATOR_PACKET_MAX_TRACE_EVENTS must be > 0")
    return value


def _operator_packet_seal_secret() -> bytes:
    raw = os.getenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET")
    if raw and raw.strip():
        return raw.strip().encode("utf-8")
    if _operator_packet_requires_configured_secret():
        raise ValueError("NEPSIS_OPERATOR_PACKET_SEAL_SECRET is required in production or operator mode")
    return _DEVELOPMENT_SEAL_SECRET


def _operator_packet_requires_configured_secret() -> bool:
    return (
        os.getenv("NODE_ENV", "").strip().lower() == "production"
        or os.getenv("NEPSIS_DEPLOYMENT_MODE", "").strip().lower() == "operator"
        or _env_true(os.getenv("NEXT_PUBLIC_NEPSIS_OPERATOR_SITE"))
    )


def _env_true(value: str | None) -> bool:
    return bool(value and value.strip().lower() in {"1", "true", "yes", "y", "on"})


__all__ = [
    "SCHEMA_ID",
    "SCHEMA_VERSION",
    "abandon_packet",
    "commit_iteration",
    "inspect_operator_packet",
    "lock_frame",
    "lock_report",
    "packet_hash",
    "run_report",
    "set_threshold_decision",
    "start_operator_packet",
]
