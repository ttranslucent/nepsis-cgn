from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..core.case_reasoning import threshold_fields_from_case_reasoning
from .orchestration_packet import (
    LAYER_ORDER as V3_LAYER_ORDER,
    lock_v3_layer as _lock_v3_orchestration_layer,
    propose_v3_layer as _propose_v3_orchestration_layer,
    start_v3_orchestration,
)
from .service import EngineApiService, Family

SCHEMA_ID = "nepsis.operator_packet"
SCHEMA_VERSION = "2.1.0"
INTEGRITY_SEAL_VERSION = "hmac-sha256:v1"
V3_LAYER_LOOP_SCHEMA_ID = "nepsis.operator_v3_layer_loop"
V3_LAYER_LOOP_SCHEMA_VERSION = "0.1.0"
GUIDE_STATE_SCHEMA_ID = "nepsis.operator_guide_state"
GUIDE_STATE_SCHEMA_VERSION = "0.1.0"
GUIDE_TIER_TABLE_VERSION = "guide-tier-table-v1"
GUIDE_TEXT_HASH_CANONICALIZATION = {
    "encoding": "utf-8",
    "unicode_normalization": "NFC",
    "line_endings": "LF",
    "trim_trailing_line_whitespace": True,
    "final_newline_policy": "ignored",
}
V3_LAYER_NAVIGATION_SHORTCUTS = {
    "next_layer": "Meta+ArrowRight",
    "previous_layer": "Meta+ArrowLeft",
}
POLICY = {
    "name": "nepsis_cgn.stateless_operator_packet",
    "version": "2026-05-22",
    "model_cost_owner": "user_model_host",
    "server_retention": "none",
}
PROPOSAL_RECEIPT_SCHEMA_ID = "nepsis.operator_model_proposal_receipt"
PROPOSAL_RECEIPT_SCHEMA_VERSION = "1.0.0"
PROPOSAL_RECEIPT_ROUTE = "/api/operator/model"
PROPOSAL_RECEIPT_SIGNATURE_ALGORITHM = "hmac-sha256"
_COMMIT_REQUIRED_TRACE_EVENTS = [
    "LOCK_FRAME",
    "RUN_REPORT",
    "LOCK_REPORT",
    "SET_THRESHOLD_DECISION",
]
_V3_OPERATOR_TRACE_EVENTS = {
    "START_V3_LAYER_LOOP",
    "SET_V3_LAYER_FIELD",
    "PROPOSE_V3_LAYER_LOCK",
    "LOCK_V3_LAYER",
}
_DEVELOPMENT_SEAL_SECRET = secrets.token_bytes(32)
_GUIDE_DOMAIN_ADAPTERS = {"general", "clinical", "finance", "legal", "research"}
_GUIDE_MAX_TURNS = 8
_GUIDE_EVENT_TYPES = {"GUIDE_TURN", "GUIDE_PATCH_ACTION", "GUIDE_LOCK_REFUSAL"}
_GUIDE_PATCH_ACTIONS = {"accept", "accept_edited", "reject", "void", "superseded"}
_GUIDE_PATCH_PENDING_STATUSES = {"proposed"}
_GUIDE_DISCRIMINATOR_RESOLUTION_STATUSES = {
    "open",
    "resolved",
    "mooted",
    "blocked",
    "deferred",
}
_GUIDE_ORDINAL_ESTIMATES = {"low", "medium", "high"}
_GUIDE_CONSEQUENCE_TARGETS = {
    "adapter",
    "candidate_frame",
    "excluded_options",
    "frame.text",
    "frame.constraints_hard",
    "frame.key_uncertainty",
    "frame.red_definition",
    "frame.blue_goals",
    "frame_constraint",
    "irreversible_action",
    "red_concern",
    "risk_tolerance",
    "ruin_path",
    "action_threshold",
}

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
    "frame_draft": ["start_operator_packet", "guide_turn", "lock_frame", "abandon_packet"],
    "frame_locked": ["guide_turn", "run_report", "abandon_packet"],
    "report_evaluated": ["guide_turn", "run_report", "lock_report", "abandon_packet"],
    "report_locked": ["guide_turn", "set_threshold_decision", "abandon_packet"],
    "threshold_set": ["guide_turn", "commit_iteration", "abandon_packet"],
}
_GUIDE_TURN_PHASES = set(_LEGAL_NEXT)
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
    resolved_frame = (
        _json_copy(frame) if frame is not None else _json_copy(_DEFAULT_FRAME)
    )
    resolved_governance = (
        _json_copy(governance_costs)
        if governance_costs is not None
        else _json_copy(_DEFAULT_GOVERNANCE)
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


def guide_turn(
    *,
    packet: dict[str, Any],
    user_message: str,
    domain_adapter: str,
    guide: dict[str, Any],
) -> dict[str, Any]:
    _service_from_packet(packet)
    phase = _packet_phase(packet)
    if phase not in _GUIDE_TURN_PHASES:
        return _local_rejection(
            attempted_tool="guide_turn",
            current_phase=phase,
            failed_precondition="guide_active_operator_phase_required",
            missing=["ACTIVE_OPERATOR_PHASE"],
            coach_prompts=[
                "Operator-guided packet mode requires an active operator packet."
            ],
        )
    turn = _normalize_guide_turn(
        user_message=user_message,
        domain_adapter=domain_adapter,
        guide=guide,
    )
    arguments = _guide_trace_arguments(turn, domain_adapter=turn["domain_adapter"])
    arguments["turn"] = turn
    arguments = _with_guide_event_chain(packet, "GUIDE_TURN", arguments)
    trace = _append_trace(packet, "GUIDE_TURN", arguments)
    state = _replay_guide_state_from_trace(trace)
    return _packet_from_guide_transition(packet, trace, state)


def guide_patch_action(
    *,
    packet: dict[str, Any],
    patch_id: str,
    action: str,
    final_value: Any = None,
    confirmation: dict[str, Any] | None = None,
    receipt_id: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    _service_from_packet(packet)
    normalized_patch_id = _required_nonempty_string(
        patch_id, max_len=80, field="patch_id"
    )
    normalized_action = _bounded_string(action, max_len=40, field="action")
    if normalized_action not in {"accept", "accept_edited", "reject", "void"}:
        raise ValueError("guide patch action must be accept, accept_edited, reject, or void")
    patch = _guide_patch_by_id(_packet_guide_state(packet), normalized_patch_id)
    if patch.get("status") not in _GUIDE_PATCH_PENDING_STATUSES:
        raise ValueError("guide patch action requires a pending proposed patch")

    proposed_hash = _required_hash(
        patch.get("proposed_value_hash"), field="patch.proposed_value_hash"
    )
    final_text = ""
    final_hash = ""
    confirmation_hash = ""
    confirmation_checked = False
    if normalized_action in {"accept", "accept_edited"}:
        if final_value is None:
            final_text = _canonical_assist_text(patch.get("proposed_value")) or ""
        else:
            final_text = _canonical_assist_text(final_value) or ""
        final_hash = guide_text_sha256(final_text)
        if normalized_action == "accept" and final_hash != proposed_hash:
            raise ValueError("guide patch accept requires final text to match proposed hash")
        if normalized_action == "accept_edited" and final_hash == proposed_hash:
            raise ValueError("guide patch accept_edited requires changed final text")
        confirmation_checked, confirmation_hash = _normalize_guide_confirmation(
            confirmation,
            required=bool(patch.get("requires_echo_confirmation")),
        )
        if patch.get("requires_echo_confirmation") and confirmation_hash != final_hash:
            raise ValueError("guide patch confirmation hash does not match final text")

    arguments = _with_guide_event_chain(
        packet,
        "GUIDE_PATCH_ACTION",
        {
            "event_id": f"guide_patch_action_{uuid4().hex}",
            "patch_id": normalized_patch_id,
            "action": normalized_action,
            "target": patch.get("target"),
            "prior_text_hash": proposed_hash,
            "final_value_hash": final_hash,
            "confirmation_hash": confirmation_hash,
            "confirmation_checked": confirmation_checked,
            "echo_origin": (
                "deterministic_server_template"
                if patch.get("requires_echo_confirmation")
                else "not_required"
            ),
            "receipt_id": _bounded_string(
                receipt_id, max_len=120, field="receipt_id"
            ),
            "batch_id": _bounded_string(batch_id, max_len=120, field="batch_id"),
            "batch_accepted": bool(batch_id),
            "at": _now(),
        },
    )
    trace = _append_trace(packet, "GUIDE_PATCH_ACTION", arguments)
    state = _replay_guide_state_from_trace(trace)
    return _packet_from_guide_transition(packet, trace, state)


def lock_frame(
    *,
    packet: dict[str, Any],
    frame: dict[str, Any],
    family: Family | None = None,
    governance_costs: dict[str, Any] | None = None,
    governance_calibration: dict[str, Any] | None = None,
    manifest_path: str | None = None,
    assist_acceptances: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _validate_packet(packet)
    blockers = _guide_lock_blockers(packet)
    if blockers:
        arguments = _with_guide_event_chain(
            packet,
            "GUIDE_LOCK_REFUSAL",
            {
                "event_id": f"guide_refusal_{uuid4().hex}",
                "reason": "blocking_uncertainties_present",
                "blocking_uncertainties": blockers,
                "at": _now(),
            },
        )
        trace = _append_trace(packet, "GUIDE_LOCK_REFUSAL", arguments)
        state = _replay_guide_state_from_trace(trace)
        return _packet_from_guide_transition(packet, trace, state)
    accepted_assists = _normalize_assist_acceptances(
        assist_acceptances,
        final_values=_frame_assist_values(frame),
        loop_id=_packet_loop_id(packet),
    )
    svc = _service_from_packet(packet)
    resolved_family = family or _packet_family(packet)
    resolved_governance = (
        governance_costs if governance_costs is not None else _packet_governance(packet)
    )
    resolved_calibration = (
        governance_calibration
        if governance_calibration is not None
        else _packet_calibration(packet)
    )
    resolved_manifest = (
        manifest_path if manifest_path is not None else _packet_manifest_path(packet)
    )
    result = svc.operator_lock_frame(
        family=resolved_family,
        frame=frame,
        governance_costs=resolved_governance,
        governance_calibration=resolved_calibration,
        manifest_path=resolved_manifest,
    )
    if _is_rejection(result):
        return _stateless_rejection(result)
    session = _transition_session(result)
    trace_frame = _json_copy(
        session.get("frame") if isinstance(session.get("frame"), dict) else frame
    )
    trace = _append_trace(
        packet,
        "LOCK_FRAME",
        {
            "family": resolved_family,
            "frame": trace_frame,
            "governance_costs": resolved_governance,
            "governance_calibration": resolved_calibration,
            "manifest_path": resolved_manifest,
            "assist_acceptances": accepted_assists,
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
    result = svc.operator_run_report(
        report_text=report_text, sign=sign, interpretation=interpretation
    )
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
    assist_acceptances: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    accepted_assists = _normalize_assist_acceptances(
        assist_acceptances,
        final_values=_threshold_assist_values(hold_reason),
        loop_id=_packet_loop_id(packet),
    )
    svc = _service_from_packet(packet)
    result = svc.operator_set_threshold_decision(
        decision=decision, hold_reason=hold_reason
    )
    if _is_rejection(result):
        return _stateless_rejection(result)
    trace = _append_trace(
        packet,
        "SET_THRESHOLD_DECISION",
        {
            "decision": decision,
            "hold_reason": hold_reason,
            "assist_acceptances": accepted_assists,
        },
    )
    return _packet_from_transition(packet, result, trace)


def set_threshold_decision_from_case_reasoning(
    *,
    packet: dict[str, Any],
    assist_acceptances: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    fields = threshold_fields_from_case_reasoning(_latest_case_reasoning(packet))
    return set_threshold_decision(
        packet=packet,
        decision=str(fields["decision"]),
        hold_reason=str(fields["hold_reason"]),
        assist_acceptances=assist_acceptances,
    )


def start_v3_layer_loop(
    *,
    packet: dict[str, Any],
    goal: str,
    scope: str,
    initial_context: str | None = None,
) -> dict[str, Any]:
    _service_from_packet(packet)
    phase = _packet_phase(packet)
    if phase == "frame_draft":
        return _local_rejection(
            attempted_tool="start_v3_layer_loop",
            current_phase=phase,
            failed_precondition="frame_lock_required",
            missing=["LOCK_FRAME"],
            coach_prompts=[
                "Lock the operator frame before starting the V3 layer loop."
            ],
        )
    if _packet_v3_layer_loop(packet) is not None:
        raise ValueError("v3 layer loop is already active")

    v3_packet = start_v3_orchestration(
        goal=goal,
        scope=scope,
        initial_context=initial_context,
    )
    loop = _new_v3_layer_loop(v3_packet)
    trace = _append_trace(
        packet,
        "START_V3_LAYER_LOOP",
        {
            "goal": goal,
            "scope": scope,
            "initial_context": initial_context or "",
            "v3_run_id": v3_packet["run_id"],
        },
    )
    return _packet_from_v3_transition(packet, trace, loop)


def set_v3_layer_field(
    *,
    packet: dict[str, Any],
    layer: str,
    field: str,
    value: Any,
    assist_acceptances: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _service_from_packet(packet)
    loop = _packet_v3_layer_loop(packet)
    if loop is None:
        return _local_rejection(
            attempted_tool="set_v3_layer_field",
            current_phase=_packet_phase(packet),
            failed_precondition="v3_layer_loop_required",
            missing=["START_V3_LAYER_LOOP"],
            coach_prompts=["Start the V3 layer loop after locking the operator frame."],
        )
    v3_packet = _v3_packet_from_loop(loop)
    current_layer = _v3_current_layer(v3_packet)
    resolved_layer = _validate_v3_layer(layer)
    if resolved_layer != current_layer:
        return _local_rejection(
            attempted_tool="set_v3_layer_field",
            current_phase=_packet_phase(packet),
            failed_precondition="v3_layer_order_required",
            missing=[f"LOCK_V3_LAYER:{current_layer}"],
            coach_prompts=[
                f"Current V3 layer is {current_layer}; lock it before editing {resolved_layer}."
            ],
            extra={"current_layer": current_layer, "attempted_layer": resolved_layer},
        )

    resolved_field = _validate_v3_field(field)
    target = _v3_assist_target(resolved_layer, resolved_field)
    canonical_value = _canonical_v3_field_text(value)
    accepted_assists = _normalize_assist_acceptances(
        assist_acceptances,
        final_values={target: canonical_value},
        loop_id=_packet_loop_id(packet),
    )
    draft_layers = _v3_draft_layers(loop)
    draft = dict(draft_layers.get(resolved_layer) or {})
    draft[resolved_field] = _json_copy(value)
    draft_layers[resolved_layer] = draft
    loop["draft_layers"] = draft_layers

    trace = _append_trace(
        packet,
        "SET_V3_LAYER_FIELD",
        {
            "layer": resolved_layer,
            "field": resolved_field,
            "value": _json_copy(value),
            "value_hash": _sha256_hex(canonical_value),
            "assist_acceptances": accepted_assists,
        },
    )
    return _packet_from_v3_transition(packet, trace, loop)


def propose_v3_operator_layer(*, packet: dict[str, Any], layer: str) -> dict[str, Any]:
    _service_from_packet(packet)
    loop = _packet_v3_layer_loop(packet)
    if loop is None:
        return _local_rejection(
            attempted_tool="propose_v3_operator_layer",
            current_phase=_packet_phase(packet),
            failed_precondition="v3_layer_loop_required",
            missing=["START_V3_LAYER_LOOP"],
            coach_prompts=["Start the V3 layer loop before proposing a layer lock."],
        )
    v3_packet = _v3_packet_from_loop(loop)
    current_layer = _v3_current_layer(v3_packet)
    resolved_layer = _validate_v3_layer(layer)
    if resolved_layer != current_layer:
        return _local_rejection(
            attempted_tool="propose_v3_operator_layer",
            current_phase=_packet_phase(packet),
            failed_precondition="v3_layer_order_required",
            missing=[f"LOCK_V3_LAYER:{current_layer}"],
            coach_prompts=[
                f"Current V3 layer is {current_layer}; lock it before proposing {resolved_layer}."
            ],
            extra={"current_layer": current_layer, "attempted_layer": resolved_layer},
        )
    artifact = _v3_draft_layers(loop).get(resolved_layer)
    if not isinstance(artifact, dict):
        return _local_rejection(
            attempted_tool="propose_v3_operator_layer",
            current_phase=_packet_phase(packet),
            failed_precondition="v3_layer_fields_required",
            missing=["SET_V3_LAYER_FIELD"],
            coach_prompts=[
                f"Set at least one field for the {resolved_layer} V3 layer before proposing a lock."
            ],
            extra={"current_layer": current_layer},
        )

    proposed = _propose_v3_orchestration_layer(
        v3_packet,
        layer=resolved_layer,
        artifact=artifact,
        draft_metadata={
            "source": "operator_packet",
            "operator_loop_id": _packet_loop_id(packet),
        },
    )
    proposal = proposed["current_proposal"]
    loop["packet"] = proposed
    trace = _append_trace(
        packet,
        "PROPOSE_V3_LAYER_LOCK",
        {
            "layer": resolved_layer,
            "artifact_hash": proposal["artifact_hash"],
            "draft_fields": sorted(artifact.keys()),
            "validation": _json_copy(proposal.get("validation") or {}),
        },
    )
    return _packet_from_v3_transition(packet, trace, loop)


def lock_v3_operator_layer(
    *,
    packet: dict[str, Any],
    layer: str,
    lock_assertion: dict[str, Any],
) -> dict[str, Any]:
    _service_from_packet(packet)
    loop = _packet_v3_layer_loop(packet)
    if loop is None:
        return _local_rejection(
            attempted_tool="lock_v3_operator_layer",
            current_phase=_packet_phase(packet),
            failed_precondition="v3_layer_loop_required",
            missing=["START_V3_LAYER_LOOP"],
            coach_prompts=["Start the V3 layer loop before locking a layer."],
        )
    v3_packet = _v3_packet_from_loop(loop)
    current_layer = _v3_current_layer(v3_packet)
    resolved_layer = _validate_v3_layer(layer)
    if resolved_layer != current_layer:
        return _local_rejection(
            attempted_tool="lock_v3_operator_layer",
            current_phase=_packet_phase(packet),
            failed_precondition="v3_layer_order_required",
            missing=[f"LOCK_V3_LAYER:{current_layer}"],
            coach_prompts=[
                f"Current V3 layer is {current_layer}; lock it before locking {resolved_layer}."
            ],
            extra={"current_layer": current_layer, "attempted_layer": resolved_layer},
        )
    proposal = v3_packet.get("current_proposal")
    if not isinstance(proposal, dict):
        return _local_rejection(
            attempted_tool="lock_v3_operator_layer",
            current_phase=_packet_phase(packet),
            failed_precondition="v3_layer_proposal_required",
            missing=["PROPOSE_V3_LAYER_LOCK"],
            coach_prompts=[f"Propose the {resolved_layer} V3 layer before locking it."],
            extra={"current_layer": current_layer},
        )

    locked = _lock_v3_orchestration_layer(
        v3_packet,
        layer=resolved_layer,
        lock_assertion=lock_assertion,
    )
    loop["packet"] = locked
    trace = _append_trace(
        packet,
        "LOCK_V3_LAYER",
        {
            "layer": resolved_layer,
            "artifact_hash": proposal["artifact_hash"],
            "locked_layers": list(locked.get("locked_layers", {}).keys()),
            "next_layer": locked.get("current_layer"),
            "lock_assertion_hash": locked["locked_layers"][resolved_layer][
                "locked_by_assertion_hash"
            ],
        },
    )
    return _packet_from_v3_transition(packet, trace, loop)


def commit_iteration(
    *,
    packet: dict[str, Any],
    carry_forward_frame: dict[str, Any] | None = None,
    assist_acceptances: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    accepted_assists = _normalize_assist_acceptances(
        assist_acceptances,
        final_values=_commit_assist_values(carry_forward_frame),
        loop_id=_packet_loop_id(packet),
    )
    if _packet_phase(packet) == "threshold_set":
        missing_events = _missing_commit_trace_events(packet)
        if missing_events:
            return _local_rejection(
                attempted_tool="commit_iteration",
                current_phase="threshold_set",
                failed_precondition="audit_trace_required",
                missing=missing_events,
                coach_prompts=[
                    "Commit requires the packet trace to prove each prior operator gate."
                ],
            )
    svc = _service_from_packet(packet)
    result = svc.operator_commit_iteration(carry_forward_frame=carry_forward_frame)
    if _is_rejection(result):
        return _stateless_rejection(result)
    trace = _append_trace(
        packet,
        "COMMIT_ITERATION",
        {
            "carry_forward_frame": carry_forward_frame,
            "assist_acceptances": accepted_assists,
        },
    )
    committed_packet = _json_copy(result.get("packet"))
    session = _transition_session(result)
    return _packet(
        loop_id=_packet_loop_id(packet),
        phase=str(result.get("phase") or "frame_draft"),
        family=str(session.get("family") or _packet_family(packet)),
        frame=_json_copy(session.get("frame") or _packet_frame(packet)),
        governance_costs=_json_copy(
            session.get("governance") or _packet_governance(packet)
        ),
        governance_calibration=_json_copy(
            session.get("calibration") or _packet_calibration(packet)
        ),
        manifest_path=(
            session.get("manifest_path")
            if isinstance(session.get("manifest_path"), str)
            else _packet_manifest_path(packet)
        ),
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
    started["previous_trace"] = _append_trace(
        packet, "ABANDON_PACKET", {"reason": reason}
    )
    return started


def inspect_operator_packet(packet: dict[str, Any] | None = None) -> dict[str, Any]:
    if packet is None:
        resolved = start_operator_packet()
    else:
        _validate_packet(packet)
        resolved = packet
    state = {
        "schema_id": "nepsis.operator_packet_state",
        "loop_id": _packet_loop_id(resolved),
        "phase": _packet_phase(resolved),
        "legal_next_tools": _legal_next_tools(
            _packet_phase(resolved),
            v3_layer_loop=_packet_v3_layer_loop(resolved),
        ),
        "audit_trace": _json_copy(resolved.get("audit_trace")) or [],
        "latest_audit": _json_copy(resolved.get("latest_audit")) or {},
        "packet_hash": packet_hash(resolved),
    }
    v3_loop = _packet_v3_layer_loop(resolved)
    if v3_loop is not None:
        state["v3_layer_loop"] = _json_copy(v3_loop)
    guide_state = _packet_guide_state(resolved)
    if guide_state is not None:
        state["guide_state"] = _json_copy(guide_state)
    return state


def packet_hash(packet: dict[str, Any] | None) -> str | None:
    if not isinstance(packet, dict):
        return None
    raw = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


_ASSIST_ACCEPTANCE_MAX_ITEMS = 16
_ASSIST_ACCEPTANCE_MAX_TEXT = 1000
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_ASSIST_DISPOSITIONS = {"accepted", "edited", "rejected"}
_ASSIST_TARGETS = {
    "frame.text",
    "frame.key_uncertainty",
    "frame.constraints_hard",
    "frame.constraints_soft",
    "frame.red_definition",
    "frame.blue_goals",
    "threshold.hold_reason",
    "next_frame.text",
}


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_guide_text(value: str) -> str:
    """Canonical text form shared by guide hashing and echo confirmation."""
    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip(" \t") for line in normalized.splitlines())


def guide_text_sha256(value: str) -> str:
    return _sha256_hex(canonical_guide_text(value))


def _guide_tier_table_sha256() -> str:
    path = Path(__file__).with_name("guide_tier_table.v1.yaml")
    try:
        data = path.read_bytes()
    except OSError:
        data = GUIDE_TIER_TABLE_VERSION.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _guide_target_tier(target: str) -> dict[str, Any]:
    if target in _GUIDE_CONSEQUENCE_TARGETS:
        return {
            "friction_tier": "consequence_bearing",
            "batch_eligible": False,
            "requires_echo_confirmation": True,
            "tier_table_version": GUIDE_TIER_TABLE_VERSION,
            "tier_table_sha256": _guide_tier_table_sha256(),
        }
    return {
        "friction_tier": "batch_eligible",
        "batch_eligible": True,
        "requires_echo_confirmation": False,
        "tier_table_version": GUIDE_TIER_TABLE_VERSION,
        "tier_table_sha256": _guide_tier_table_sha256(),
    }


def _bounded_string(
    value: Any, *, max_len: int = _ASSIST_ACCEPTANCE_MAX_TEXT, field: str
) -> str:
    if not isinstance(value, str):
        return ""
    resolved = value.strip()
    if len(resolved) > max_len:
        raise ValueError(f"{field} exceeds maximum length of {max_len}")
    return resolved


def _required_nonempty_string(value: Any, *, max_len: int, field: str) -> str:
    resolved = _bounded_string(value, max_len=max_len, field=field)
    if not resolved:
        raise ValueError(f"{field} is required")
    return resolved


def _normalize_domain_adapter(value: Any) -> str:
    adapter = _bounded_string(value, max_len=40, field="domain_adapter") or "general"
    if adapter not in _GUIDE_DOMAIN_ADAPTERS:
        raise ValueError(
            f"domain_adapter must be one of: {', '.join(sorted(_GUIDE_DOMAIN_ADAPTERS))}"
        )
    return adapter


def _normalize_string_list(value: Any, *, field: str, max_items: int = 8) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list when provided")
    if len(value) > max_items:
        raise ValueError(f"{field} exceeds maximum length of {max_items}")
    out: list[str] = []
    for idx, item in enumerate(value):
        text = _bounded_string(item, max_len=500, field=f"{field}[{idx}]")
        if text:
            out.append(text)
    return out


def _normalize_guide_scaffold(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("visible_scaffold must be an object when provided")
    out: dict[str, Any] = {}
    for key in (
        "current_frame",
        "open_constraint",
        "next_question",
        "red_concern",
    ):
        text = _bounded_string(value.get(key), max_len=700, field=f"visible_scaffold.{key}")
        if text:
            out[key] = text
    ready = _normalize_string_list(value.get("ready_to_lock"), field="visible_scaffold.ready_to_lock")
    if ready:
        out["ready_to_lock"] = ready
    return out


def _normalize_packet_delta_preview(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("packet_delta_preview must be an object when provided")
    if len(value) > 16:
        raise ValueError("packet_delta_preview exceeds maximum length of 16")
    out: dict[str, Any] = {}
    for key, raw in value.items():
        field = _bounded_string(key, max_len=120, field="packet_delta_preview key")
        if not field:
            continue
        if isinstance(raw, list):
            out[field] = _normalize_string_list(raw, field=f"packet_delta_preview.{field}", max_items=8)
        elif isinstance(raw, dict):
            out[field] = _json_copy(raw)
        else:
            out[field] = _bounded_string(raw, max_len=1000, field=f"packet_delta_preview.{field}")
    return out


def _guide_update_consequence_level(target: str) -> str:
    return "high" if _guide_target_tier(target)["friction_tier"] == "consequence_bearing" else "low"


def _guide_update_confirmation_prompt(target: str) -> str:
    if _guide_update_consequence_level(target) == "low":
        return f"{target} can be batch accepted when it preserves already-stated wording."
    return f"{target} changes the frame or risk channel. Confirm this patch individually."


def _guide_update_requires_echo_confirmation(target: str) -> bool:
    return bool(_guide_target_tier(target)["requires_echo_confirmation"])


def _normalize_proposed_updates(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("proposed_updates must be a list when provided")
    if len(value) > 8:
        raise ValueError("proposed_updates exceeds maximum length of 8")
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("proposed_updates entries must be objects")
        target = _bounded_string(item.get("target"), max_len=120, field=f"proposed_updates[{idx}].target")
        if not target:
            continue
        proposed_raw = item.get("proposed_value", item.get("proposedValue"))
        if isinstance(proposed_raw, list):
            proposed_value: Any = _normalize_string_list(
                proposed_raw, field=f"proposed_updates[{idx}].proposed_value", max_items=12
            )
            proposed_text = "\n".join(proposed_value)
        else:
            proposed_text = _bounded_string(
                proposed_raw, max_len=1000, field=f"proposed_updates[{idx}].proposed_value"
            )
            proposed_value = proposed_text
        tier = _guide_target_tier(target)
        row = {
            "patch_id": _bounded_string(
                item.get("patch_id", item.get("patchId", item.get("id"))),
                max_len=80,
                field=f"proposed_updates[{idx}].patch_id",
            )
            or f"patch_{uuid4().hex}",
            "target": target,
            "title": _bounded_string(item.get("title"), max_len=120, field=f"proposed_updates[{idx}].title")
            or "Guide suggestion",
            "proposed_value_hash": guide_text_sha256(proposed_text),
            "consequence_level": _guide_update_consequence_level(target),
            "friction_tier": tier["friction_tier"],
            "batch_eligible": tier["batch_eligible"],
            "confirmation_prompt": _guide_update_confirmation_prompt(target),
            "requires_echo_confirmation": tier["requires_echo_confirmation"],
            "tier_table_version": tier["tier_table_version"],
            "tier_table_sha256": tier["tier_table_sha256"],
            "status": "proposed",
            "rationale": _bounded_string(
                item.get("rationale"), max_len=1000, field=f"proposed_updates[{idx}].rationale"
            ),
            "risk_note": _bounded_string(
                item.get("risk_note", item.get("riskNote")),
                max_len=1000,
                field=f"proposed_updates[{idx}].risk_note",
            ),
        }
        if proposed_value:
            row["proposed_value"] = proposed_value
        out.append(row)
    return out


def _normalize_ordinal_estimate(value: Any, *, field: str) -> str:
    if value is None:
        return "medium"
    resolved = _bounded_string(value, max_len=40, field=field)
    if resolved not in _GUIDE_ORDINAL_ESTIMATES:
        raise ValueError(f"{field} must be one of: low, medium, high")
    return resolved


def _normalize_discriminator_resolution_status(value: Any, *, field: str) -> str:
    if value is None:
        return "open"
    resolved = _bounded_string(value, max_len=40, field=field)
    if resolved not in _GUIDE_DISCRIMINATOR_RESOLUTION_STATUSES:
        raise ValueError(
            f"{field} must be one of: {', '.join(sorted(_GUIDE_DISCRIMINATOR_RESOLUTION_STATUSES))}"
        )
    return resolved


def _normalize_ranked_discriminators(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("ranked_discriminators must be a list when provided")
    if len(value) > 8:
        raise ValueError("ranked_discriminators exceeds maximum length of 8")
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError("ranked_discriminators entries must be objects")
        rank_raw = item.get("rank", idx + 1)
        rank = rank_raw if isinstance(rank_raw, int) and rank_raw > 0 else idx + 1
        rationale = _bounded_string(
            item.get("rationale", item.get("why_it_moves_decision", item.get("whyItMovesDecision"))),
            max_len=1000,
            field=f"ranked_discriminators[{idx}].rationale",
        )
        out.append(
            {
                "discriminator_id": _bounded_string(
                    item.get("discriminator_id", item.get("discriminatorId")),
                    max_len=80,
                    field=f"ranked_discriminators[{idx}].discriminator_id",
                )
                or f"disc_{uuid4().hex}",
                "rank": rank,
                "label": _bounded_string(
                    item.get("label"), max_len=160, field=f"ranked_discriminators[{idx}].label"
                ),
                "question": _bounded_string(
                    item.get("question"), max_len=700, field=f"ranked_discriminators[{idx}].question"
                ),
                "why_it_moves_decision": _bounded_string(
                    item.get("why_it_moves_decision", item.get("whyItMovesDecision")),
                    max_len=1000,
                    field=f"ranked_discriminators[{idx}].why_it_moves_decision",
                ),
                "target_field": _bounded_string(
                    item.get("target_field", item.get("targetField")),
                    max_len=120,
                    field=f"ranked_discriminators[{idx}].target_field",
                ),
                "expected_information_gain": _normalize_ordinal_estimate(
                    item.get("expected_information_gain", item.get("expectedInformationGain")),
                    field=f"ranked_discriminators[{idx}].expected_information_gain",
                ),
                "cost_to_resolve": _normalize_ordinal_estimate(
                    item.get("cost_to_resolve", item.get("costToResolve")),
                    field=f"ranked_discriminators[{idx}].cost_to_resolve",
                ),
                "consequence_if_wrong": _normalize_ordinal_estimate(
                    item.get("consequence_if_wrong", item.get("consequenceIfWrong")),
                    field=f"ranked_discriminators[{idx}].consequence_if_wrong",
                ),
                "rationale": rationale,
                "rationale_sha256": guide_text_sha256(rationale),
                "resolution_status": _normalize_discriminator_resolution_status(
                    item.get("resolution_status", item.get("resolutionStatus")),
                    field=f"ranked_discriminators[{idx}].resolution_status",
                ),
                "blocking": bool(item.get("blocking", True)),
                "basis": _bounded_string(
                    item.get("basis"), max_len=400, field=f"ranked_discriminators[{idx}].basis"
                )
                or "model_estimate",
            }
        )
    return out


def _normalize_guide_turn(
    *,
    user_message: str,
    domain_adapter: str,
    guide: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(guide, dict):
        raise ValueError("guide must be an object")
    message = _required_nonempty_string(user_message, max_len=4000, field="user_message")
    adapter = _normalize_domain_adapter(domain_adapter)
    next_question = _required_nonempty_string(
        guide.get("next_question", guide.get("nextQuestion")),
        max_len=700,
        field="guide.next_question",
    )
    turn = {
        "turn_id": str(uuid4()),
        "created_at": _now(),
        "domain_adapter": adapter,
        "user_message_hash": guide_text_sha256(message),
        "user_message_excerpt": message[:280],
        "next_question": next_question,
        "model_route_id": _bounded_string(
            guide.get("model_route_id", guide.get("modelRouteId")),
            max_len=120,
            field="guide.model_route_id",
        )
        or "/api/operator/guide",
        "tier_table_version": GUIDE_TIER_TABLE_VERSION,
        "tier_table_sha256": _guide_tier_table_sha256(),
        "canonicalization": dict(GUIDE_TEXT_HASH_CANONICALIZATION),
        "visible_scaffold": _normalize_guide_scaffold(guide.get("visible_scaffold", guide.get("visibleScaffold"))),
        "packet_delta_preview": _normalize_packet_delta_preview(
            guide.get("packet_delta_preview", guide.get("packetDeltaPreview"))
        ),
        "proposed_updates": _normalize_proposed_updates(
            guide.get("proposed_updates", guide.get("proposedUpdates"))
        ),
        "fields_ready_to_lock": _normalize_string_list(
            guide.get("fields_ready_to_lock", guide.get("fieldsReadyToLock")),
            field="fields_ready_to_lock",
        ),
        "blocking_uncertainties": _normalize_string_list(
            guide.get("blocking_uncertainties", guide.get("blockingUncertainties")),
            field="blocking_uncertainties",
        ),
        "ranked_discriminators": _normalize_ranked_discriminators(
            guide.get("ranked_discriminators", guide.get("rankedDiscriminators"))
        ),
    }
    turn["proposed_patch_ids"] = [
        row["patch_id"] for row in turn["proposed_updates"] if isinstance(row, dict)
    ]
    turn["ranked_discriminator_ids"] = [
        row["discriminator_id"]
        for row in turn["ranked_discriminators"]
        if isinstance(row, dict)
    ]
    turn["ranking_rationale_hashes"] = [
        row["rationale_sha256"]
        for row in turn["ranked_discriminators"]
        if isinstance(row, dict)
    ]
    return turn


def _empty_guide_state(domain_adapter: str = "general") -> dict[str, Any]:
    return {
        "schema_id": GUIDE_STATE_SCHEMA_ID,
        "schema_version": GUIDE_STATE_SCHEMA_VERSION,
        "domain_adapter": _normalize_domain_adapter(domain_adapter),
        "message_count": 0,
        "turns": [],
        "patches": [],
        "discriminators": [],
        "convergence": _guide_convergence([], [], []),
    }


def apply_guide_event(
    previous: dict[str, Any] | None,
    *,
    event: str,
    arguments: dict[str, Any],
) -> dict[str, Any] | None:
    if event not in _GUIDE_EVENT_TYPES:
        return _json_copy(previous) if previous is not None else None
    if event == "GUIDE_TURN":
        return _apply_guide_turn_event(previous, arguments)
    if event == "GUIDE_PATCH_ACTION":
        return _apply_guide_patch_action_event(previous, arguments)
    if event == "GUIDE_LOCK_REFUSAL":
        return _apply_guide_lock_refusal_event(previous, arguments)
    raise PacketReplayError(f"unsupported guide event: {event}")


def _apply_guide_turn_event(
    previous: dict[str, Any] | None, arguments: dict[str, Any]
) -> dict[str, Any]:
    turn = arguments.get("turn")
    if not isinstance(turn, dict):
        raise PacketReplayError("GUIDE_TURN requires turn payload")
    adapter = _normalize_domain_adapter(turn.get("domain_adapter"))
    previous_turns = (
        previous.get("turns")
        if isinstance(previous, dict) and isinstance(previous.get("turns"), list)
        else []
    )
    turns = [*_json_copy(previous_turns), turn][-_GUIDE_MAX_TURNS:]
    message_count = (
        previous.get("message_count")
        if isinstance(previous, dict) and isinstance(previous.get("message_count"), int)
        else len(previous_turns)
    )
    patches = _merge_guide_patches(
        previous.get("patches") if isinstance(previous, dict) else None,
        turn.get("proposed_updates"),
    )
    discriminators = _merge_guide_discriminators(
        previous.get("discriminators") if isinstance(previous, dict) else None,
        turn.get("ranked_discriminators"),
    )
    blocking_uncertainties = _normalize_string_list(
        turn.get("blocking_uncertainties"),
        field="turn.blocking_uncertainties",
    )
    return {
        "schema_id": GUIDE_STATE_SCHEMA_ID,
        "schema_version": GUIDE_STATE_SCHEMA_VERSION,
        "domain_adapter": adapter,
        "message_count": message_count + 1,
        "last_turn": turn,
        "turns": turns,
        "patches": patches,
        "discriminators": discriminators,
        "convergence": _guide_convergence(
            patches,
            discriminators,
            blocking_uncertainties,
        ),
    }


def _apply_guide_patch_action_event(
    previous: dict[str, Any] | None, arguments: dict[str, Any]
) -> dict[str, Any]:
    if not isinstance(previous, dict):
        raise PacketReplayError("GUIDE_PATCH_ACTION requires existing guide_state")
    patch_id = _bounded_string(arguments.get("patch_id"), max_len=80, field="patch_id")
    action = _bounded_string(arguments.get("action"), max_len=40, field="action")
    if action not in _GUIDE_PATCH_ACTIONS:
        raise PacketReplayError("GUIDE_PATCH_ACTION action is unsupported")
    patches = []
    matched = False
    for patch in previous.get("patches", []):
        if not isinstance(patch, dict):
            continue
        row = _json_copy(patch)
        if row.get("patch_id") == patch_id:
            matched = True
            row["status"] = {
                "accept": "accepted",
                "accept_edited": "accepted_edited",
            }.get(action, action)
            row["disposition_event_id"] = arguments.get("event_id")
            row["final_value_hash"] = arguments.get("final_value_hash", "")
            row["confirmation_hash"] = arguments.get("confirmation_hash", "")
            row["receipt_id"] = arguments.get("receipt_id", "")
            row["batch_id"] = arguments.get("batch_id", "")
        patches.append(row)
    if not matched:
        raise PacketReplayError(f"GUIDE_PATCH_ACTION references unknown patch: {patch_id}")
    state = _json_copy(previous)
    state["patches"] = patches
    state["convergence"] = _guide_convergence(
        patches,
        state.get("discriminators", []),
        _latest_blocking_uncertainties(state),
    )
    return state


def _apply_guide_lock_refusal_event(
    previous: dict[str, Any] | None, arguments: dict[str, Any]
) -> dict[str, Any]:
    state = _json_copy(previous) if isinstance(previous, dict) else _empty_guide_state()
    refusals = state.get("lock_refusals") if isinstance(state.get("lock_refusals"), list) else []
    refusals.append(
        {
            "event_id": arguments.get("event_id"),
            "reason": arguments.get("reason"),
            "blocking_uncertainties": _json_copy(arguments.get("blocking_uncertainties")) or [],
            "at": arguments.get("at"),
        }
    )
    state["lock_refusals"] = refusals
    state["convergence"] = _guide_convergence(
        state.get("patches", []),
        state.get("discriminators", []),
        _latest_blocking_uncertainties(state),
        lock_refusals=refusals,
    )
    return state


def _merge_guide_patches(
    previous: Any, proposed_updates: Any
) -> list[dict[str, Any]]:
    if isinstance(previous, list):
        patches = [_json_copy(row) for row in previous if isinstance(row, dict)]
    else:
        patches = []
    incoming = (
        [_json_copy(row) for row in proposed_updates if isinstance(row, dict)]
        if isinstance(proposed_updates, list)
        else []
    )
    incoming_targets = {
        row.get("target")
        for row in incoming
        if isinstance(row.get("target"), str)
    }
    superseding_by_target = {
        row.get("target"): row.get("patch_id")
        for row in incoming
        if isinstance(row.get("target"), str) and isinstance(row.get("patch_id"), str)
    }
    for row in patches:
        if (
            row.get("status") in _GUIDE_PATCH_PENDING_STATUSES
            and row.get("target") in incoming_targets
        ):
            row["status"] = "superseded"
            row["superseded_by"] = superseding_by_target.get(row.get("target"), "")
    return [*patches, *incoming]


def _merge_guide_discriminators(
    previous: Any, ranked_discriminators: Any
) -> list[dict[str, Any]]:
    if not isinstance(ranked_discriminators, list) or not ranked_discriminators:
        return (
            [_json_copy(row) for row in previous if isinstance(row, dict)]
            if isinstance(previous, list)
            else []
        )
    return [_json_copy(row) for row in ranked_discriminators if isinstance(row, dict)]


def _latest_blocking_uncertainties(state: dict[str, Any]) -> list[str]:
    last_turn = state.get("last_turn")
    if not isinstance(last_turn, dict):
        return []
    return _normalize_string_list(
        last_turn.get("blocking_uncertainties"),
        field="last_turn.blocking_uncertainties",
    )


def _guide_convergence(
    patches: Any,
    discriminators: Any,
    blocking_uncertainties: list[str],
    *,
    lock_refusals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    patch_rows = patches if isinstance(patches, list) else []
    discriminator_rows = discriminators if isinstance(discriminators, list) else []
    blocking_discriminators = [
        row
        for row in discriminator_rows
        if isinstance(row, dict)
        and bool(row.get("blocking", True))
        and row.get("resolution_status", "open") in {"open", "blocked"}
    ]
    accepted_fields = [
        row.get("target")
        for row in patch_rows
        if isinstance(row, dict)
        and row.get("status") in {"accepted", "accepted_edited"}
        and isinstance(row.get("target"), str)
    ]
    pending_high_tier = [
        row.get("patch_id")
        for row in patch_rows
        if isinstance(row, dict)
        and row.get("status") == "proposed"
        and row.get("friction_tier") == "consequence_bearing"
    ]
    blocking_count = len(blocking_uncertainties) + len(blocking_discriminators)
    return {
        "basis": "server_computed_from_packet_state",
        "blocking_uncertainty_count": blocking_count,
        "blocking_uncertainties": list(blocking_uncertainties),
        "blocking_discriminator_ids": [
            row.get("discriminator_id")
            for row in blocking_discriminators
            if isinstance(row.get("discriminator_id"), str)
        ],
        "accepted_field_count": len(set(accepted_fields)),
        "accepted_fields": sorted(set(accepted_fields)),
        "pending_consequence_patch_ids": [
            patch_id for patch_id in pending_high_tier if isinstance(patch_id, str)
        ],
        "lock_ready": blocking_count == 0 and not pending_high_tier,
        "lock_refusal_count": len(lock_refusals or []),
    }


def _guide_patch_by_id(
    guide_state: dict[str, Any] | None, patch_id: str
) -> dict[str, Any]:
    if not isinstance(guide_state, dict):
        raise ValueError("guide_state is required before patch actions")
    patches = guide_state.get("patches")
    if not isinstance(patches, list):
        raise ValueError("guide_state patches registry is required")
    for patch in patches:
        if isinstance(patch, dict) and patch.get("patch_id") == patch_id:
            return _json_copy(patch)
    raise ValueError(f"unknown guide patch id: {patch_id}")


def _normalize_guide_confirmation(
    value: dict[str, Any] | None, *, required: bool
) -> tuple[bool, str]:
    if value is None:
        if required:
            raise ValueError("guide patch confirmation is required")
        return False, ""
    if not isinstance(value, dict):
        raise ValueError("guide patch confirmation must be an object")
    checked = bool(value.get("checked"))
    text_hash = value.get("text_sha256", value.get("textSha256"))
    if not isinstance(text_hash, str) or not text_hash:
        text = value.get("text")
        if isinstance(text, str):
            text_hash = guide_text_sha256(text)
    resolved_hash = _required_hash(text_hash, field="confirmation.text_sha256")
    if required and not checked:
        raise ValueError("guide patch confirmation checkbox is required")
    return checked, resolved_hash


def _guide_lock_blockers(packet: dict[str, Any]) -> list[str]:
    guide_state = _packet_guide_state(packet)
    if not isinstance(guide_state, dict):
        return []
    convergence = guide_state.get("convergence")
    if not isinstance(convergence, dict):
        return []
    blockers = _normalize_string_list(
        convergence.get("blocking_uncertainties"),
        field="guide_state.convergence.blocking_uncertainties",
        max_items=16,
    )
    for discriminator_id in convergence.get("blocking_discriminator_ids", []):
        if isinstance(discriminator_id, str) and discriminator_id:
            blockers.append(f"discriminator:{discriminator_id}")
    return blockers


def _guide_chain_start(packet: dict[str, Any]) -> str:
    integrity = packet.get("integrity")
    seal = integrity.get("seal") if isinstance(integrity, dict) else None
    return seal if isinstance(seal, str) and seal else "0" * 64


def _last_guide_chain_hash(trace: list[dict[str, Any]], *, fallback: str) -> str:
    chain = fallback
    for entry in trace:
        if not isinstance(entry, dict) or entry.get("event") not in _GUIDE_EVENT_TYPES:
            continue
        args = entry.get("arguments")
        if isinstance(args, dict) and isinstance(args.get("sealed_sha256_after"), str):
            chain = args["sealed_sha256_after"]
    return chain


def _with_guide_event_chain(
    packet: dict[str, Any], event: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    args = _json_copy(arguments) or {}
    args.setdefault("event_id", f"guide_event_{uuid4().hex}")
    before = _last_guide_chain_hash(
        _packet_trace(packet),
        fallback=_guide_chain_start(packet),
    )
    args["sealed_sha256_before"] = before
    args["sealed_sha256_after"] = _guide_event_chain_hash(event, args)
    return args


def _guide_event_chain_hash(event: str, arguments: dict[str, Any]) -> str:
    payload_args = {
        key: _json_copy(value)
        for key, value in arguments.items()
        if key != "sealed_sha256_after"
    }
    payload = {
        "event": event,
        "arguments": _normalize_integrity_json(payload_args),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _verify_guide_event_chain(trace: list[dict[str, Any]]) -> None:
    previous_after = ""
    for idx, entry in enumerate(trace):
        if not isinstance(entry, dict) or entry.get("event") not in _GUIDE_EVENT_TYPES:
            continue
        event = str(entry.get("event"))
        args = entry.get("arguments")
        if not isinstance(args, dict):
            raise ValueError(f"guide event {idx} arguments are required")
        before = args.get("sealed_sha256_before")
        after = args.get("sealed_sha256_after")
        if not isinstance(before, str) or not _SHA256_HEX_RE.match(before):
            raise ValueError(f"guide event {idx} sealed_sha256_before is invalid")
        if not isinstance(after, str) or not _SHA256_HEX_RE.match(after):
            raise ValueError(f"guide event {idx} sealed_sha256_after is invalid")
        if previous_after and before != previous_after:
            raise ValueError(f"guide event chain breaks before event {idx}")
        expected_after = _guide_event_chain_hash(event, args)
        if not hmac.compare_digest(after, expected_after):
            raise ValueError(f"guide event chain breaks at event {idx}")
        previous_after = after


def _replay_guide_state_from_trace(trace: list[dict[str, Any]]) -> dict[str, Any] | None:
    _verify_guide_event_chain(trace)
    state: dict[str, Any] | None = None
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        event = entry.get("event")
        args = entry.get("arguments")
        if not isinstance(event, str) or not isinstance(args, dict):
            continue
        state = apply_guide_event(state, event=event, arguments=args)
    return state


def _guide_trace_arguments(last_turn: dict[str, Any], *, domain_adapter: str) -> dict[str, Any]:
    return {
        "domain_adapter": domain_adapter,
        "turn_id": last_turn.get("turn_id"),
        "user_message_hash": last_turn.get("user_message_hash"),
        "user_message_excerpt": last_turn.get("user_message_excerpt"),
        "next_question": last_turn.get("next_question"),
        "model_route_id": last_turn.get("model_route_id"),
        "tier_table_version": last_turn.get("tier_table_version"),
        "tier_table_sha256": last_turn.get("tier_table_sha256"),
        "fields_ready_to_lock": _json_copy(last_turn.get("fields_ready_to_lock")) or [],
        "blocking_uncertainties": _json_copy(last_turn.get("blocking_uncertainties")) or [],
        "ranked_discriminators": _json_copy(last_turn.get("ranked_discriminators")) or [],
        "ranking_rationale_hashes": _json_copy(last_turn.get("ranking_rationale_hashes")) or [],
        "proposed_update_targets": [
            row.get("target")
            for row in last_turn.get("proposed_updates", [])
            if isinstance(row, dict) and isinstance(row.get("target"), str)
        ],
    }


def _required_hash(value: Any, *, field: str) -> str:
    resolved = _bounded_string(value, max_len=64, field=field)
    if not _SHA256_HEX_RE.match(resolved):
        raise ValueError(f"{field} must be a 64-character lowercase sha256 hex digest")
    return resolved


def _verify_assist_proposal_receipt(
    value: Any,
    *,
    target: str,
    model: str,
    loop_id: str,
    proposed_hash: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(
            "proposal_receipt is required for model_suggestion assist provenance"
        )
    if value.get("schema_id") != PROPOSAL_RECEIPT_SCHEMA_ID:
        raise ValueError("proposal_receipt schema_id mismatch")
    if value.get("schema_version") != PROPOSAL_RECEIPT_SCHEMA_VERSION:
        raise ValueError(
            f"proposal_receipt schema_version must be {PROPOSAL_RECEIPT_SCHEMA_VERSION}"
        )
    if value.get("route") != PROPOSAL_RECEIPT_ROUTE:
        raise ValueError("proposal_receipt route mismatch")
    if value.get("target") != target:
        raise ValueError("proposal_receipt target mismatch")
    if value.get("model") != model:
        raise ValueError("proposal_receipt model mismatch")
    if value.get("loop_id") != loop_id:
        raise ValueError("proposal_receipt loop_id mismatch")
    if value.get("proposed_value_hash") != proposed_hash:
        raise ValueError("proposal_receipt proposed_value_hash mismatch")
    if value.get("mode") not in {"suggest_field", "review_completion"}:
        raise ValueError("proposal_receipt mode mismatch")

    signature = value.get("signature")
    if not isinstance(signature, dict):
        raise ValueError("proposal_receipt signature is required")
    if signature.get("algorithm") != PROPOSAL_RECEIPT_SIGNATURE_ALGORITHM:
        raise ValueError("proposal_receipt signature algorithm mismatch")
    key_id = (
        os.getenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_KEY_ID", "default").strip()
        or "default"
    )
    if signature.get("key_id") != key_id:
        raise ValueError("proposal_receipt key_id mismatch")
    signature_value = signature.get("signature")
    if not isinstance(signature_value, str) or not _SHA256_HEX_RE.match(
        signature_value
    ):
        raise ValueError("proposal_receipt signature must be a sha256 hex digest")

    expected = hmac.new(
        _operator_proposal_receipt_secret(),
        _proposal_receipt_signing_bytes(value),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature_value, expected):
        raise ValueError("proposal_receipt signature verification failed")
    return _json_copy(value) or {}


def _proposal_receipt_signing_bytes(receipt: dict[str, Any]) -> bytes:
    unsigned = {
        key: _json_copy(value) for key, value in receipt.items() if key != "signature"
    }
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _operator_proposal_receipt_secret() -> bytes:
    raw = os.getenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", "").strip()
    if not raw:
        raise ValueError(
            "NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET is required for model proposal receipts"
        )
    return raw.encode("utf-8")


def _read_rationale_segment(rationale: Any, label: str) -> str:
    if not isinstance(rationale, str):
        return ""
    match = re.search(rf"(?:^|\|\s*){re.escape(label)}:\s*([^|]*)", rationale)
    return match.group(1).strip() if match else ""


def _canonical_assist_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    return None


def _frame_assist_values(
    frame: dict[str, Any] | None, *, prefix: str = "frame"
) -> dict[str, str]:
    if not isinstance(frame, dict):
        return {}
    values: dict[str, str] = {}
    for target, key in {
        f"{prefix}.text": "text",
        f"{prefix}.constraints_hard": "constraints_hard",
        f"{prefix}.constraints_soft": "constraints_soft",
    }.items():
        resolved = _canonical_assist_text(frame.get(key))
        if resolved is not None:
            values[target] = resolved
    rationale = frame.get("rationale_for_change")
    values[f"{prefix}.key_uncertainty"] = _read_rationale_segment(
        rationale, "Uncertainty"
    )
    values[f"{prefix}.red_definition"] = _read_rationale_segment(
        rationale, "Red channel"
    )
    values[f"{prefix}.blue_goals"] = _read_rationale_segment(rationale, "Blue channel")
    return values


def _threshold_assist_values(hold_reason: str) -> dict[str, str]:
    return {"threshold.hold_reason": hold_reason}


def _commit_assist_values(carry_forward_frame: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(carry_forward_frame, dict):
        return {}
    text = _canonical_assist_text(carry_forward_frame.get("text"))
    return {"next_frame.text": text} if text is not None else {}


def _normalize_assist_acceptances(
    value: Any,
    *,
    final_values: dict[str, str],
    loop_id: str,
) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("assist_acceptances must be a list when provided")
    if len(value) > _ASSIST_ACCEPTANCE_MAX_ITEMS:
        raise ValueError(
            f"assist_acceptances exceeds {_ASSIST_ACCEPTANCE_MAX_ITEMS} entries"
        )

    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("assist_acceptances entries must be objects")
        target = _bounded_string(item.get("target"), max_len=120, field="assist target")
        disposition = _bounded_string(
            item.get("disposition"), max_len=40, field="assist disposition"
        )
        if target not in _ASSIST_TARGETS and not _is_v3_assist_target(target):
            raise ValueError(f"unsupported assist target: {target}")
        if disposition not in _ASSIST_DISPOSITIONS:
            raise ValueError("assist disposition must be accepted, edited, or rejected")

        proposed_hash = _required_hash(
            item.get("proposed_value_hash"), field="proposed_value_hash"
        )
        model = _bounded_string(item.get("model"), max_len=120, field="assist model")
        receipt = _verify_assist_proposal_receipt(
            item.get("proposal_receipt"),
            target=target,
            model=model,
            loop_id=loop_id,
            proposed_hash=proposed_hash,
        )
        final_hash = ""
        if disposition in {"accepted", "edited"}:
            if target not in final_values:
                raise ValueError(
                    f"assist target {target!r} is not part of this transition"
                )
            final_hash = _required_hash(
                item.get("final_value_hash"), field="final_value_hash"
            )
            actual_hash = _sha256_hex(final_values[target])
            if actual_hash != final_hash:
                raise ValueError(f"assist final_value_hash mismatch for {target}")
            if disposition == "accepted" and proposed_hash != final_hash:
                raise ValueError(
                    "accepted assist hashes diverge; use disposition=edited"
                )
            if disposition == "edited" and proposed_hash == final_hash:
                raise ValueError("edited assist hashes match; use disposition=accepted")

        normalized.append(
            {
                "target": target,
                "source": _bounded_string(
                    item.get("source"), max_len=80, field="assist source"
                )
                or "model_suggestion",
                "model": model,
                "disposition": disposition,
                "proposed_value_hash": proposed_hash,
                "final_value_hash": final_hash,
                "proposal_receipt": receipt,
                "summary": _bounded_string(item.get("summary"), field="assist summary"),
            }
        )
    return normalized


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
    v3_layer_loop: dict[str, Any] | None = None,
    guide_state: dict[str, Any] | None = None,
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
        "legal_next_tools": _legal_next_tools(phase, v3_layer_loop=v3_layer_loop),
        "latest_audit": _json_copy(latest_audit) or {},
        "latest_step": _json_copy(latest_step),
        "last_commit_packet": _json_copy(last_commit_packet),
        "last_abandoned_packet": _json_copy(last_abandoned_packet),
        "previous_trace": _json_copy(previous_trace) or [],
        "policy": dict(POLICY),
    }
    if v3_layer_loop is not None:
        packet["v3_layer_loop"] = _json_copy(v3_layer_loop)
    if guide_state is not None:
        packet["guide_state"] = _json_copy(guide_state)
    return _seal_packet(packet)


def _packet_from_transition(
    previous: dict[str, Any],
    result: dict[str, Any],
    trace: list[dict[str, Any]],
) -> dict[str, Any]:
    session = _transition_session(result)
    phase = str(
        result.get("phase") or session.get("operator_phase") or _packet_phase(previous)
    )
    return _packet(
        loop_id=_packet_loop_id(previous),
        phase=phase,
        family=str(session.get("family") or _packet_family(previous)),
        frame=_json_copy(session.get("frame") or _packet_frame(previous)),
        governance_costs=_json_copy(
            session.get("governance") or _packet_governance(previous)
        ),
        governance_calibration=_json_copy(
            session.get("calibration") or _packet_calibration(previous)
        ),
        manifest_path=(
            session.get("manifest_path")
            if isinstance(session.get("manifest_path"), str)
            else _packet_manifest_path(previous)
        ),
        audit_trace=trace,
        latest_audit=_json_copy(
            result.get("audit") or previous.get("latest_audit") or {}
        ),
        latest_step=_json_copy(result.get("step")),
        last_commit_packet=_json_copy(previous.get("last_commit_packet")),
        last_abandoned_packet=_json_copy(previous.get("last_abandoned_packet")),
        v3_layer_loop=_packet_v3_layer_loop(previous),
        guide_state=_packet_guide_state(previous),
    )


def _packet_from_guide_transition(
    previous: dict[str, Any],
    trace: list[dict[str, Any]],
    guide_state: dict[str, Any],
) -> dict[str, Any]:
    return _packet(
        loop_id=_packet_loop_id(previous),
        phase=_packet_phase(previous),
        family=_packet_family(previous),
        frame=_packet_frame(previous),
        governance_costs=_packet_governance(previous),
        governance_calibration=_packet_calibration(previous),
        manifest_path=_packet_manifest_path(previous),
        audit_trace=trace,
        latest_audit=_json_copy(previous.get("latest_audit") or {}),
        latest_step=_json_copy(previous.get("latest_step")),
        last_commit_packet=_json_copy(previous.get("last_commit_packet")),
        last_abandoned_packet=_json_copy(previous.get("last_abandoned_packet")),
        v3_layer_loop=_packet_v3_layer_loop(previous),
        guide_state=guide_state,
    )


def _packet_from_v3_transition(
    previous: dict[str, Any],
    trace: list[dict[str, Any]],
    v3_layer_loop: dict[str, Any],
) -> dict[str, Any]:
    return _packet(
        loop_id=_packet_loop_id(previous),
        phase=_packet_phase(previous),
        family=_packet_family(previous),
        frame=_packet_frame(previous),
        governance_costs=_packet_governance(previous),
        governance_calibration=_packet_calibration(previous),
        manifest_path=_packet_manifest_path(previous),
        audit_trace=trace,
        latest_audit=_json_copy(previous.get("latest_audit") or {}),
        latest_step=_json_copy(previous.get("latest_step")),
        last_commit_packet=_json_copy(previous.get("last_commit_packet")),
        last_abandoned_packet=_json_copy(previous.get("last_abandoned_packet")),
        v3_layer_loop=v3_layer_loop,
        guide_state=_packet_guide_state(previous),
    )


def _service_from_packet(packet: dict[str, Any]) -> EngineApiService:
    _validate_packet(packet)
    svc = EngineApiService(store_path="", record_provenance=False)
    for entry in _packet_trace(packet):
        event = entry.get("event")
        args = entry.get("arguments")
        if not isinstance(event, str) or not isinstance(args, dict):
            raise PacketReplayError(
                "operator packet audit_trace entries require event and arguments"
            )
        result = _replay_event(svc, event, args)
        if _is_rejection(result):
            raise PacketReplayError(
                f"operator packet trace is not replayable at {event}: {result}"
            )
    return svc


def _replay_event(
    svc: EngineApiService, event: str, args: dict[str, Any]
) -> dict[str, Any]:
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
    if event in _GUIDE_EVENT_TYPES:
        return svc.get_operator_session_state()
    if event in _V3_OPERATOR_TRACE_EVENTS:
        return svc.get_operator_session_state()
    if event in {"COMMIT_ITERATION", "ABANDON_PACKET"}:
        return svc.get_operator_session_state()
    raise PacketReplayError(f"unsupported operator packet trace event: {event}")


def _append_trace(
    packet: dict[str, Any], event: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    trace = _packet_trace(packet)
    trace.append(
        {"event": event, "at": _now(), "arguments": _json_copy(arguments) or {}}
    )
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
        raise ValueError(
            f"operator packet audit_trace exceeds configured maximum of {max_trace} events"
        )
    _verify_packet_integrity(packet)
    _verify_guide_projection(packet)


def _verify_guide_projection(packet: dict[str, Any]) -> None:
    trace = _packet_trace(packet)
    expected = _replay_guide_state_from_trace(trace)
    actual = _packet_guide_state(packet)
    if expected is None and actual is None:
        return
    if expected != actual:
        raise ValueError("operator packet guide_state does not match replayed guide events")


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
        rejection["attempted_tool"] = _stateful_to_stateless_tool(
            rejection["attempted_tool"]
        )
    return rejection


def _local_rejection(
    *,
    attempted_tool: str,
    current_phase: str,
    failed_precondition: str,
    missing: list[str],
    coach_prompts: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rejection = {
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
    if extra:
        rejection.update(_json_copy(extra) or {})
    return rejection


def _missing_commit_trace_events(packet: dict[str, Any]) -> list[str]:
    events = [
        entry.get("event") for entry in _packet_trace(packet) if isinstance(entry, dict)
    ]
    return [event for event in _COMMIT_REQUIRED_TRACE_EVENTS if event not in events]


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


def _legal_next_tools(
    phase: str, *, v3_layer_loop: dict[str, Any] | None = None
) -> list[str]:
    tools = list(_LEGAL_NEXT.get(phase, _LEGAL_NEXT["frame_draft"]))
    if phase != "frame_locked":
        return tools
    if _is_v3_layer_loop(v3_layer_loop):
        for tool in (
            "set_v3_layer_field",
            "propose_v3_operator_layer",
            "lock_v3_operator_layer",
        ):
            if tool not in tools:
                tools.insert(0, tool)
    elif "start_v3_layer_loop" not in tools:
        tools.insert(0, "start_v3_layer_loop")
    return tools


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
    return (
        _json_copy(governance)
        if isinstance(governance, dict)
        else _json_copy(_DEFAULT_GOVERNANCE)
    )


def _packet_calibration(packet: dict[str, Any]) -> dict[str, Any] | None:
    calibration = packet.get("governance_calibration")
    return _json_copy(calibration) if isinstance(calibration, dict) else None


def _packet_manifest_path(packet: dict[str, Any]) -> str | None:
    value = packet.get("manifest_path")
    return value if isinstance(value, str) and value else None


def _packet_guide_state(packet: dict[str, Any]) -> dict[str, Any] | None:
    state = packet.get("guide_state")
    return (
        _json_copy(state)
        if isinstance(state, dict)
        and state.get("schema_id") == GUIDE_STATE_SCHEMA_ID
        and state.get("schema_version") == GUIDE_STATE_SCHEMA_VERSION
        else None
    )


def _new_v3_layer_loop(v3_packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_id": V3_LAYER_LOOP_SCHEMA_ID,
        "schema_version": V3_LAYER_LOOP_SCHEMA_VERSION,
        "packet": _json_copy(v3_packet),
        "draft_layers": {},
        "navigation_shortcuts": dict(V3_LAYER_NAVIGATION_SHORTCUTS),
    }


def _packet_v3_layer_loop(packet: dict[str, Any]) -> dict[str, Any] | None:
    loop = packet.get("v3_layer_loop")
    return _json_copy(loop) if _is_v3_layer_loop(loop) else None


def _is_v3_layer_loop(value: Any) -> bool:
    return isinstance(value, dict) and value.get("schema_id") == V3_LAYER_LOOP_SCHEMA_ID


def _v3_packet_from_loop(loop: dict[str, Any]) -> dict[str, Any]:
    packet = loop.get("packet")
    if not isinstance(packet, dict):
        raise ValueError("v3 layer loop packet is required")
    return _json_copy(packet)


def _v3_draft_layers(loop: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = loop.get("draft_layers")
    if not isinstance(raw, dict):
        return {}
    drafts: dict[str, dict[str, Any]] = {}
    for layer, artifact in raw.items():
        if isinstance(layer, str) and isinstance(artifact, dict):
            drafts[layer] = _json_copy(artifact)
    return drafts


def _v3_current_layer(v3_packet: dict[str, Any]) -> str:
    layer = v3_packet.get("current_layer")
    if isinstance(layer, str) and layer in V3_LAYER_ORDER:
        return layer
    raise ValueError("v3 layer loop does not have a current layer")


def _validate_v3_layer(layer: Any) -> str:
    if not isinstance(layer, str) or layer not in V3_LAYER_ORDER:
        raise ValueError(f"layer must be one of: {', '.join(V3_LAYER_ORDER)}")
    return layer


def _validate_v3_field(field: Any) -> str:
    if not isinstance(field, str) or not re.match(r"^[a-z][a-z0-9_]*$", field):
        raise ValueError("v3 layer field must be snake_case")
    return field


def _v3_assist_target(layer: str, field: str) -> str:
    return f"v3_layer.{layer}.{field}"


def _is_v3_assist_target(target: str) -> bool:
    parts = target.split(".")
    return (
        len(parts) == 3
        and parts[0] == "v3_layer"
        and parts[1] in V3_LAYER_ORDER
        and re.match(r"^[a-z][a-z0-9_]*$", parts[2]) is not None
    )


def _canonical_v3_field_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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
        raise ValueError(
            "operator packet integrity counter must be a non-negative integer"
        )
    expected_counter = _packet_integrity_counter(packet)
    if counter != expected_counter:
        raise ValueError(
            "operator packet integrity counter does not match packet trace state"
        )
    expected = _packet_integrity_seal(packet, counter)
    if not hmac.compare_digest(seal, expected):
        raise ValueError("operator packet integrity seal verification failed")


def _packet_integrity_payload(packet: dict[str, Any], counter: int) -> bytes:
    body = _normalize_integrity_json(
        {key: value for key, value in packet.items() if key != "integrity"}
    )
    payload = {"counter": counter, "packet": body}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _normalize_integrity_json(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_normalize_integrity_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_integrity_json(item) for key, item in value.items()}
    return value


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
        raise ValueError(
            "NEPSIS_OPERATOR_PACKET_MAX_TRACE_EVENTS must be an integer"
        ) from exc
    if value <= 0:
        raise ValueError("NEPSIS_OPERATOR_PACKET_MAX_TRACE_EVENTS must be > 0")
    return value


def _operator_packet_seal_secret() -> bytes:
    raw = os.getenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET")
    if raw and raw.strip():
        return raw.strip().encode("utf-8")
    if _operator_packet_requires_configured_secret():
        raise ValueError(
            "NEPSIS_OPERATOR_PACKET_SEAL_SECRET is required in production or operator mode"
        )
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
    "canonical_guide_text",
    "commit_iteration",
    "guide_patch_action",
    "guide_text_sha256",
    "guide_turn",
    "inspect_operator_packet",
    "lock_frame",
    "lock_report",
    "lock_v3_operator_layer",
    "packet_hash",
    "propose_v3_operator_layer",
    "run_report",
    "set_threshold_decision",
    "set_threshold_decision_from_case_reasoning",
    "set_v3_layer_field",
    "start_v3_layer_loop",
    "start_operator_packet",
]
