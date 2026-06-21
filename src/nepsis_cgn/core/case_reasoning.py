from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

SCHEMA_ID = "nepsis.case_reasoning_compiler"
SCHEMA_VERSION = "0.1.0"
COMPILER_SOURCE = "deterministic_v1"
COMPILER_SOURCES = {COMPILER_SOURCE, "model_v1"}

RED_STATUSES = {"open", "closed", "uncertain"}
THRESHOLD_ACTIONS = {"escalate_red", "hold_for_review", "deescalate", "request_more_data"}
TIME_SENSITIVE = {"immediate", "hours"}
REQUIRED_NODE_KEYS = (
    "intake_boundary",
    "red",
    "blue",
    "trajectory_spc",
    "authority_reassurance",
    "closure",
    "zeroback_reset",
)

_RUNTIME_SAFETY_CONSTRAINTS = [
    "No PHI or patient-identifiable data.",
    "No autonomous clinical, financial, or operational advice.",
    "Preserve source facts.",
    "Preserve RED-before-BLUE ordering.",
]

_AUTHORITY_CUE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("radiology", "radiology"),
    ("consultant", "consultant"),
    ("urology", "urology"),
    ("surgery says", "surgery"),
    ("maintenance says", "maintenance"),
    ("maintenance lead", "maintenance"),
    ("expert", "expert"),
    ("auditor", "auditor"),
    ("analyst", "analyst"),
    ("regulator", "regulator"),
    ("market confidence", "market confidence"),
    ("management reassurance", "management"),
    ("management reassured", "management"),
    ("no crepitus therefore", "clinical reassurance"),
    ("read as traumatic", "imaging interpretation"),
    ("favors traumatic", "imaging interpretation"),
    ("authority pushback", "authority pushback"),
)

_FALSE_REASSURANCE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("no crepitus", "classic finding absent", "Crepitus is insensitive and may be late."),
    ("absence of crepitus", "classic finding absent", "Crepitus is insensitive and may be late."),
    ("no shock", "hemodynamic stability", "Hemodynamic stability does not exclude evolving high-harm disease."),
    ("hemodynamic stability", "stable vitals", "Stable vitals do not close an early or evolving red hazard."),
    ("no abscess", "no drainable collection", "Absence of abscess does not exclude deep infection."),
    ("no obvious abscess", "no drainable collection", "Absence of abscess does not exclude deep infection."),
    ("normal x-ray", "benign initial imaging", "A normal x-ray does not close deep infection or CNS-extension risk."),
    ("young or low risk", "low baseline risk", "Baseline risk does not close trajectory-compatible red risk."),
    ("high-quality securities", "asset quality reassurance", "Asset quality does not prove liquidity under run stress."),
    ("prior success", "reputation or track record", "Prior success does not verify current liquidity or asset claims."),
    ("regulatory supervision", "institutional oversight", "Supervision does not itself close the domain red hazard."),
    ("auditor reputation", "institutional credibility", "Reputation is not direct verification."),
    ("stock-market validation", "market acceptance", "Market acceptance can propagate a false frame."),
    ("rib fracture", "alternative explanation exists", "An alternative explanation must explain the full trajectory."),
)

_TRAJECTORY_CUES = (
    "trajectory",
    "progressive",
    "worsening",
    "secondary worsening",
    "initial pain",
    "partial settling",
    "over years",
    "rising rates",
    "continues rising",
    "continued heating",
    "temperature continues",
    "rapid withdrawals",
    "run dynamics",
    "liquidity pressure",
    "no progression",
    "pain improves",
)

_PROCESS_SAFETY_TERMS = (
    "no-phi",
    "no phi",
    "source facts",
    "hard safety constraints",
    "runtime safety",
    "operator review",
    "preserve red before blue",
    "preserve red-before-blue",
    "do not present",
    "autonomous recommendation",
)

_DOMAIN_HARM_TERMS = (
    "missed",
    "delayed",
    "death",
    "tissue loss",
    "septic shock",
    "neurologic",
    "disability",
    "infection",
    "source control",
    "cash",
    "solvency",
    "liquidity",
    "bank failure",
    "investor",
    "creditor",
    "fabricated",
    "collapse",
    "red hazard",
    "critical incident",
    "fire",
    "injury",
    "damage",
    "thermal runaway",
    "corruption",
    "source-token",
    "wrong-manifold",
    "transformed answer",
)

_GENERIC_DECISION_RECEIPTS = (
    "operator review is required before recommendation",
    "operator review is required before treating this as a recommendation",
    "preserved the red frame",
    "source facts and hard safety constraints were preserved",
    "hold for operator review before recommendation",
)


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def detect_domain(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("wirecard", "cash", "auditor", "svb", "bank", "liquidity")):
        return "finance"
    if any(
        term in lowered
        for term in (
            "nsti",
            "necrotizing",
            "fournier",
            "spinal epidural",
            "meningitic",
            "lactate",
            "wbc",
            "operative",
            "wound",
        )
    ):
        return "medicine"
    if any(term in lowered for term in ("jingall", "jailing", "source token")):
        return "word_puzzle"
    return "safety"


def detect_authority_cues(text: str) -> list[dict[str, str]]:
    lowered = text.lower()
    cues: list[dict[str, str]] = []
    for pattern, source in _AUTHORITY_CUE_PATTERNS:
        if pattern in lowered:
            cues.append({"source": source, "cue": pattern})
    return _dedupe_rows(cues, "cue")


def detect_false_reassurance_tokens(text: str) -> list[dict[str, str]]:
    lowered = text.lower()
    tokens: list[dict[str, str]] = []
    for pattern, why_reassuring, why_non_closing in _FALSE_REASSURANCE_PATTERNS:
        if pattern in lowered:
            token = pattern.replace("absence of ", "no ")
            tokens.append(
                {
                    "token": token,
                    "why_reassuring": why_reassuring,
                    "why_non_closing": why_non_closing,
                }
            )
    return _dedupe_rows(tokens, "token")


def detect_trajectory_cues(text: str) -> list[str]:
    lowered = text.lower()
    return [cue for cue in _TRAJECTORY_CUES if cue in lowered]


def detect_red_question(text: str) -> str:
    match = re.search(r"red-channel question:\s*([^.\n?]+[?]?)", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    lowered = text.lower()
    if "wirecard" in lowered or "claimed cash" in lowered:
        return "Does the claimed cash actually exist?"
    if "svb" in lowered or "rapid depositor flight" in lowered:
        return "Can the bank survive rapid depositor flight given liquidity position and asset-liability mismatch?"
    if "fournier" in lowered:
        return "Could this be Fournier's or necrotizing genital-perineal infection?"
    if "spinal epidural" in lowered or "meningitic" in lowered:
        return "Could this be spinal epidural abscess with CNS or meningitic extension?"
    if "nsti" in lowered or "necrotizing" in lowered:
        return "Could this be necrotizing soft tissue infection?"
    if "jingall" in lowered or "jailing" in lowered:
        return "Is the candidate answer preserving the authoritative source token?"
    return "What domain red hazard remains unclosed?"


def compile_case_reasoning(
    source_text: str,
    *,
    case_id: str = "custom",
    frame_id: str,
    input_prompt_hash: str | None = None,
) -> dict[str, Any]:
    resolved_hash = input_prompt_hash or prompt_hash(source_text)
    packet = compile_known_fixture(
        source_text,
        case_id=case_id,
        frame_id=frame_id,
        input_prompt_hash=resolved_hash,
    )
    _ensure_agentic_nodes(
        packet,
        source_text=source_text,
        frame_id=frame_id,
        input_prompt_hash=resolved_hash,
    )
    validation = validate_case_reasoning(
        packet,
        source_text=source_text,
        frame_id=frame_id,
        input_prompt_hash=resolved_hash,
    )
    mark_case_reasoning_validation(packet, validation)
    return packet


def compile_known_fixture(
    source_text: str,
    *,
    case_id: str = "custom",
    frame_id: str,
    input_prompt_hash: str,
) -> dict[str, Any]:
    lowered = f"{case_id}\n{source_text}".lower()
    if "true_closure" in lowered or "operative wound exploration shows no necrotic" in lowered:
        return _medical_true_closure(source_text, case_id, frame_id, input_prompt_hash)
    if "uncertain" in lowered and "insufficient" in lowered:
        return _medical_uncertain(source_text, case_id, frame_id, input_prompt_hash)
    if "wirecard" in lowered:
        return _wirecard(source_text, case_id, frame_id, input_prompt_hash)
    if "svb" in lowered or "silicon valley bank" in lowered:
        return _svb(source_text, case_id, frame_id, input_prompt_hash)
    if "fournier" in lowered:
        return _fournier(source_text, case_id, frame_id, input_prompt_hash)
    if "spinal epidural" in lowered or "meningitic" in lowered:
        return _sea(source_text, case_id, frame_id, input_prompt_hash)
    if "nsti" in lowered or "necrotizing" in lowered or "chest wall" in lowered:
        return _nsti(source_text, case_id, frame_id, input_prompt_hash)
    if "jingall" in lowered or "jailing" in lowered:
        return _jingall(source_text, case_id, frame_id, input_prompt_hash)
    return _generic_uncertain(source_text, case_id, frame_id, input_prompt_hash)


def validate_case_reasoning(
    packet: dict[str, Any],
    *,
    source_text: str,
    frame_id: str,
    input_prompt_hash: str,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(packet, dict):
        return {
            "status": "BLOCK",
            "errors": ["case_reasoning must be an object"],
            "warnings": [],
        }

    if packet.get("schema_id") != SCHEMA_ID:
        errors.append("case_reasoning schema_id mismatch")
    if packet.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"case_reasoning schema_version must be {SCHEMA_VERSION}")
    if packet.get("compiler_source") not in COMPILER_SOURCES:
        errors.append(f"compiler_source must be one of: {', '.join(sorted(COMPILER_SOURCES))}")
    if packet.get("input_frame_id") != frame_id:
        errors.append("input_frame_id does not match current frame")
    if packet.get("input_prompt_hash") != input_prompt_hash:
        errors.append("input_prompt_hash does not match current prompt")

    for key in (
        "surface_story",
        "red_channel_question",
        "domain_catastrophic_outcome",
        "trajectory_signal",
        "closure_condition",
        "current_red_status",
        "decision_reason",
        "recommended_threshold_action",
    ):
        if not _has_value(packet.get(key)):
            errors.append(f"{key} is required")

    if packet.get("current_red_status") not in RED_STATUSES:
        errors.append("current_red_status must be open, closed, or uncertain")
    if packet.get("recommended_threshold_action") not in THRESHOLD_ACTIONS:
        errors.append("recommended_threshold_action is unsupported")

    if not _looks_like_domain_harm(str(packet.get("domain_catastrophic_outcome", ""))):
        errors.append("domain_catastrophic_outcome must describe domain harm, not runtime/process safety")

    decision_reason = str(packet.get("decision_reason", ""))
    if _is_generic_process_receipt(decision_reason):
        errors.append("decision_reason must be case-specific and cannot be a process receipt")

    if not _frames_distinct(packet.get("blue_frame"), packet.get("red_frame")):
        errors.append("blue_frame and red_frame must both be present and meaningfully distinct")

    if detect_authority_cues(source_text) and not _non_empty_list(packet.get("authority_pushback")):
        errors.append("authority cues require authority_pushback entries")

    trajectory = packet.get("trajectory_signal")
    if detect_trajectory_cues(source_text) and not _nested_text(trajectory, "violation"):
        errors.append("temporal course requires trajectory_signal.violation")

    closure = packet.get("closure_condition")
    if packet.get("current_red_status") == "closed" and _nested_text(closure, "current_closure_status") != "satisfied":
        errors.append("closed red status requires satisfied closure condition")

    for item in packet.get("authority_pushback") if isinstance(packet.get("authority_pushback"), list) else []:
        if isinstance(item, dict) and not item.get("what_it_does_not_close"):
            warnings.append("authority pushback should state what it does not close")

    if _non_empty_list(packet.get("false_reassurance_tokens")) and not _non_empty_list(packet.get("non_closure_evidence")):
        warnings.append("false reassurance tokens should be represented in non_closure_evidence")

    _validate_agentic_nodes(packet, frame_id=frame_id, input_prompt_hash=input_prompt_hash, errors=errors)

    return {
        "status": "BLOCK" if errors else "WARN" if warnings else "PASS",
        "errors": errors,
        "warnings": warnings,
    }


def mark_case_reasoning_validation(packet: dict[str, Any], validation: dict[str, Any]) -> None:
    status = str(validation.get("status") or "BLOCK")
    errors = list(validation.get("errors") if isinstance(validation.get("errors"), list) else [])
    warnings = list(validation.get("warnings") if isinstance(validation.get("warnings"), list) else [])
    packet["compiler_valid"] = status != "BLOCK"
    packet["validation_errors"] = errors
    packet["validation_warnings"] = warnings

    reason = errors[0] if errors else ""
    governor = packet.get("governor")
    if isinstance(governor, dict):
        governor["validation_status"] = status
        zeroback = governor.get("zeroback") if isinstance(governor.get("zeroback"), dict) else {}
        zeroback["reset_required"] = status == "BLOCK"
        zeroback["reason"] = reason
        governor["zeroback"] = zeroback

    nodes = packet.get("nodes")
    if isinstance(nodes, dict):
        reset = nodes.get("zeroback_reset") if isinstance(nodes.get("zeroback_reset"), dict) else {}
        reset["reset_required"] = status == "BLOCK"
        reset["reason"] = reason
        reset["triggers"] = errors
        nodes["zeroback_reset"] = reset


def _ensure_agentic_nodes(
    packet: dict[str, Any],
    *,
    source_text: str,
    frame_id: str,
    input_prompt_hash: str,
) -> None:
    closure_basis = _closure_basis_from_packet(packet)
    packet.setdefault("closure_basis", closure_basis)
    compiler_source = str(packet.get("compiler_source") or COMPILER_SOURCE)
    packet["governor"] = {
        "schema_id": "nepsis.case_reasoning_governor",
        "input_frame_id": frame_id,
        "input_prompt_hash": input_prompt_hash,
        "compiler_source": compiler_source,
        "validation_status": "pending",
        "zeroback": {"reset_required": False, "reason": ""},
    }
    packet["nodes"] = {
        "intake_boundary": {
            "source_facts": [_excerpt(source_text)],
            "user_query": _excerpt(source_text),
            "runtime_safety_constraints": _copy_value(packet.get("runtime_safety_constraints") or []),
            "input_prompt_hash": input_prompt_hash,
            "privacy_boundary": "no_phi_or_runtime_boundary_declared"
            if "no phi" in source_text.lower() or "no-phi" in source_text.lower()
            else "runtime_boundary_declared",
        },
        "red": {
            "domain_red_hazard": _copy_value(packet.get("domain_red_hazard")),
            "domain_catastrophic_outcome": packet.get("domain_catastrophic_outcome"),
            "red_channel_question": packet.get("red_channel_question"),
            "closure_condition": _copy_value(packet.get("closure_condition")),
        },
        "blue": {
            "surface_story": packet.get("surface_story"),
            "blue_frame": _copy_value(packet.get("blue_frame")),
        },
        "trajectory_spc": {
            "trajectory_signal": _copy_value(packet.get("trajectory_signal")),
            "time_sensitivity": packet.get("time_sensitivity"),
            "drift_signal": _drift_signal_from_trajectory(packet.get("trajectory_signal")),
        },
        "authority_reassurance": {
            "authority_pushback": _copy_value(packet.get("authority_pushback") or []),
            "false_reassurance_tokens": _copy_value(packet.get("false_reassurance_tokens") or []),
            "non_closure_evidence": _copy_value(packet.get("non_closure_evidence") or []),
        },
        "closure": {
            "current_red_status": packet.get("current_red_status"),
            "closure_basis": closure_basis,
            "closure_condition": _copy_value(packet.get("closure_condition")),
        },
        "zeroback_reset": {
            "reset_required": False,
            "triggers": [],
            "reason": "",
        },
    }


def _validate_agentic_nodes(
    packet: dict[str, Any],
    *,
    frame_id: str,
    input_prompt_hash: str,
    errors: list[str],
) -> None:
    governor = packet.get("governor")
    if not isinstance(governor, dict):
        errors.append("governor is required")
    else:
        if governor.get("input_frame_id") != frame_id:
            errors.append("governor.input_frame_id does not match current frame")
        if governor.get("input_prompt_hash") != input_prompt_hash:
            errors.append("governor.input_prompt_hash does not match current prompt")
        if governor.get("compiler_source") != packet.get("compiler_source"):
            errors.append("governor.compiler_source must match compiler_source")
        if not isinstance(governor.get("zeroback"), dict):
            errors.append("governor.zeroback is required")

    nodes = packet.get("nodes")
    if not isinstance(nodes, dict):
        errors.append("nodes is required")
        return

    for key in REQUIRED_NODE_KEYS:
        if not isinstance(nodes.get(key), dict):
            errors.append(f"nodes.{key} is required")

    red = nodes.get("red") if isinstance(nodes.get("red"), dict) else {}
    blue = nodes.get("blue") if isinstance(nodes.get("blue"), dict) else {}
    trajectory = nodes.get("trajectory_spc") if isinstance(nodes.get("trajectory_spc"), dict) else {}
    authority = nodes.get("authority_reassurance") if isinstance(nodes.get("authority_reassurance"), dict) else {}
    closure = nodes.get("closure") if isinstance(nodes.get("closure"), dict) else {}
    intake = nodes.get("intake_boundary") if isinstance(nodes.get("intake_boundary"), dict) else {}

    _require_node_match(packet, "domain_red_hazard", red, "domain_red_hazard", errors, node_name="red")
    _require_node_match(packet, "domain_catastrophic_outcome", red, "domain_catastrophic_outcome", errors, node_name="red")
    _require_node_match(packet, "red_channel_question", red, "red_channel_question", errors, node_name="red")
    _require_node_match(packet, "closure_condition", red, "closure_condition", errors, node_name="red")
    _require_node_match(packet, "surface_story", blue, "surface_story", errors, node_name="blue")
    _require_node_match(packet, "blue_frame", blue, "blue_frame", errors, node_name="blue")
    _require_node_match(packet, "trajectory_signal", trajectory, "trajectory_signal", errors, node_name="trajectory_spc")
    _require_node_match(packet, "time_sensitivity", trajectory, "time_sensitivity", errors, node_name="trajectory_spc")
    _require_node_match(packet, "authority_pushback", authority, "authority_pushback", errors, node_name="authority_reassurance")
    _require_node_match(
        packet,
        "false_reassurance_tokens",
        authority,
        "false_reassurance_tokens",
        errors,
        node_name="authority_reassurance",
    )
    _require_node_match(packet, "non_closure_evidence", authority, "non_closure_evidence", errors, node_name="authority_reassurance")
    _require_node_match(packet, "current_red_status", closure, "current_red_status", errors, node_name="closure")
    _require_node_match(packet, "closure_basis", closure, "closure_basis", errors, default="", node_name="closure")
    _require_node_match(packet, "closure_condition", closure, "closure_condition", errors, node_name="closure")

    if intake.get("input_prompt_hash") != input_prompt_hash:
        errors.append("nodes.intake_boundary.input_prompt_hash does not match current prompt")
    if "runtime_safety_constraints" in intake and intake.get("runtime_safety_constraints") != packet.get(
        "runtime_safety_constraints"
    ):
        errors.append("runtime_safety_constraints must match nodes.intake_boundary.runtime_safety_constraints")


def _require_node_match(
    packet: dict[str, Any],
    top_key: str,
    node: dict[str, Any],
    node_key: str,
    errors: list[str],
    *,
    default: Any = None,
    node_name: str,
) -> None:
    if not node:
        return
    top_value = packet.get(top_key, default)
    node_value = node.get(node_key, default)
    if top_value != node_value:
        errors.append(f"{top_key} must match nodes.{node_name}.{node_key}")


def threshold_fields_from_case_reasoning(case_reasoning: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(case_reasoning, dict) or case_reasoning.get("compiler_valid") is not True:
        return {
            "decision": "hold",
            "hold_reason": "Threshold blocked because the case reasoning compiler was invalid.",
            "recommendation": "compiler_invalid_hold",
            "recommended_threshold_action": "hold_for_review",
            "warning_level": "red",
            "gate_crossed": True,
            "closure_basis": "",
        }

    status = str(case_reasoning.get("current_red_status") or "uncertain")
    action = str(case_reasoning.get("recommended_threshold_action") or "request_more_data")
    reason = str(case_reasoning.get("decision_reason") or "Case reasoning did not provide a decision reason.")

    if status == "closed":
        closure = case_reasoning.get("closure_condition") if isinstance(case_reasoning.get("closure_condition"), dict) else {}
        return {
            "decision": "recommend",
            "hold_reason": "",
            "recommendation": "deescalate",
            "recommended_threshold_action": "deescalate",
            "warning_level": "low",
            "gate_crossed": False,
            "closure_basis": str(closure.get("required_to_close") or reason),
        }

    if status == "open":
        warning = "red" if case_reasoning.get("time_sensitivity") in TIME_SENSITIVE or action == "escalate_red" else "yellow"
        return {
            "decision": "hold",
            "hold_reason": reason,
            "recommendation": "escalate_red" if action == "escalate_red" else "hold_for_review",
            "recommended_threshold_action": action,
            "warning_level": warning,
            "gate_crossed": True,
            "closure_basis": "",
        }

    return {
        "decision": "hold",
        "hold_reason": reason,
        "recommendation": "request_more_data",
        "recommended_threshold_action": "request_more_data",
        "warning_level": "yellow_or_red",
        "gate_crossed": True,
        "closure_basis": "",
    }


def _base_packet(
    *,
    source_text: str,
    case_id: str,
    frame_id: str,
    input_prompt_hash: str,
    domain: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_id": SCHEMA_ID,
        "schema_version": SCHEMA_VERSION,
        "compiler_source": COMPILER_SOURCE,
        "input_frame_id": frame_id,
        "input_prompt_hash": input_prompt_hash,
        "compiler_valid": False,
        "validation_errors": [],
        "validation_warnings": [],
        "case_id": case_id,
        "domain": domain or detect_domain(source_text),
        "runtime_safety_constraints": list(_RUNTIME_SAFETY_CONSTRAINTS),
        "false_reassurance_tokens": detect_false_reassurance_tokens(source_text),
        "authority_pushback": [],
        "non_closure_evidence": [],
        "reasoning_quality_flags": {
            "authority_substitution_detected": bool(detect_authority_cues(source_text)),
            "trajectory_violation_detected": bool(detect_trajectory_cues(source_text)),
            "frame_tension_detected": False,
            "false_reassurance_risk_detected": bool(detect_false_reassurance_tokens(source_text)),
            "missing_closure_condition": False,
        },
    }


def _nsti(source_text: str, case_id: str, frame_id: str, input_prompt_hash: str) -> dict[str, Any]:
    packet = _base_packet(source_text=source_text, case_id=case_id, frame_id=frame_id, input_prompt_hash=input_prompt_hash, domain="medicine")
    packet.update(
        {
            "surface_story": "Chest wall swelling and pain after blunt trauma with delayed secondary worsening.",
            "blue_frame": _frame_obj(
                "traumatic chest wall injury with rib fracture",
                "Pain, swelling, and gas are attributed to blunt trauma and rib fracture.",
                ["fall onto metal fence", "rib fracture", "radiology favored traumatic gas"],
                ["secondary worsening", "severe progressive pain", "erythema, warmth, swelling", "elevated WBC and lactate"],
            ),
            "red_frame": _frame_obj(
                "necrotizing soft tissue infection",
                "A deep, time-sensitive necrotizing infection after trauma or inoculation.",
                ["delayed secondary worsening", "severe pain", "soft tissue inflammation", "deep gas", "systemic response"],
                ["no obvious skin breakdown", "no abscess", "hemodynamic stability"],
            ),
            "red_channel_question": detect_red_question(source_text),
            "domain_catastrophic_outcome": "Missed NSTI with delayed source control, tissue loss, septic shock, death, or major morbidity.",
            "domain_red_hazard": {
                "hazard": "missed NSTI",
                "mechanism_of_harm": "delayed operative source control",
                "time_sensitivity": "hours",
                "closure_requirement": "operative exploration or definitive alternative explaining the full trajectory",
            },
            "mechanism_of_harm": "Delay to operative exploration allows rapid tissue destruction and systemic toxicity.",
            "time_sensitivity": "hours",
            "trajectory_signal": {
                "expected_curve_under_blue_frame": "Simple trauma should peak early, plateau, then improve.",
                "observed_curve": "Initial injury partially settled, then pain, swelling, erythema, warmth, and systemic response worsened.",
                "violation": "Delayed secondary worsening violates the simple-trauma curve.",
                "interpretation": "Trauma explains the initial event but does not close the infectious red frame.",
            },
            "authority_pushback": [
                {
                    "source": "radiology",
                    "claim": "gas is traumatic from rib fracture",
                    "what_it_explains": ["rib fracture", "possible local traumatic air"],
                    "what_it_does_not_close": ["secondary worsening", "severe progressive pain", "systemic inflammatory response"],
                    "closure_status": "non_closing",
                }
            ]
            if detect_authority_cues(source_text)
            else [],
            "non_closure_evidence": _non_closure_from_tokens(source_text),
            "closure_condition": {
                "required_to_close": "Operative exploration or a definitive alternative explaining the full trajectory, exam, labs, and imaging.",
                "acceptable_closure_modes": ["direct operative exploration", "definitive alternative explanation", "future course incompatible with NSTI"],
                "current_closure_status": "not_satisfied",
            },
            "current_red_status": "open",
            "decision_reason": "The NSTI red channel remains open because traumatic gas, absent abscess, and stable vitals reduce probability but do not close the delayed-worsening infectious trajectory.",
            "recommended_threshold_action": "escalate_red",
        }
    )
    packet["reasoning_quality_flags"].update(
        {
            "authority_substitution_detected": bool(packet["authority_pushback"]),
            "trajectory_violation_detected": True,
            "frame_tension_detected": True,
            "false_reassurance_risk_detected": True,
        }
    )
    return packet


def _medical_true_closure(source_text: str, case_id: str, frame_id: str, input_prompt_hash: str) -> dict[str, Any]:
    packet = _base_packet(source_text=source_text, case_id=case_id, frame_id=frame_id, input_prompt_hash=input_prompt_hash, domain="medicine")
    packet.update(
        {
            "surface_story": "Traumatic subcutaneous air after an open wound with improving course and operative exploration.",
            "blue_frame": _frame_obj(
                "traumatic subcutaneous air without infection",
                "Air is explained by the open traumatic wound and direct exploration.",
                ["air immediately after open wound", "pain improves", "normal vitals and labs", "operative exploration shows viable tissue"],
                [],
            ),
            "red_frame": _frame_obj(
                "necrotizing soft tissue infection",
                "The feared state would be deep necrotizing infection requiring source control.",
                [],
                ["operative exploration directly showed no necrosis, purulence, or tracking infection"],
            ),
            "red_channel_question": detect_red_question(source_text),
            "domain_catastrophic_outcome": "Missed necrotizing infection with delayed source control, tissue loss, septic shock, or death.",
            "domain_red_hazard": {
                "hazard": "missed NSTI",
                "mechanism_of_harm": "delayed source control if exploration had not closed the concern",
                "time_sensitivity": "hours",
                "closure_requirement": "direct exploration showing viable tissue and no tracking infection",
            },
            "mechanism_of_harm": "Unclosed NSTI would harm through delayed source control, but direct exploration closed the red frame.",
            "time_sensitivity": "hours",
            "trajectory_signal": {
                "expected_curve_under_blue_frame": "Traumatic air should not progress after direct wound assessment.",
                "observed_curve": "Pain improves, vitals and labs are normal, and exploration shows viable tissue.",
                "violation": "No ongoing violation after direct exploration.",
                "interpretation": "The feared red frame is closed by direct reality-testing.",
            },
            "authority_pushback": [],
            "non_closure_evidence": [],
            "closure_condition": {
                "required_to_close": "Direct operative exploration showed viable fascia and muscle with no necrotic tissue, purulence, or tracking infection.",
                "acceptable_closure_modes": ["direct operative exploration"],
                "current_closure_status": "satisfied",
            },
            "current_red_status": "closed",
            "decision_reason": "The NSTI red channel is closed because direct operative exploration satisfies the closure condition.",
            "recommended_threshold_action": "deescalate",
        }
    )
    return packet


def _medical_uncertain(source_text: str, case_id: str, frame_id: str, input_prompt_hash: str) -> dict[str, Any]:
    packet = _base_packet(source_text=source_text, case_id=case_id, frame_id=frame_id, input_prompt_hash=input_prompt_hash, domain="medicine")
    packet.update(
        {
            "surface_story": "Early localized symptoms with limited data and no established trajectory.",
            "blue_frame": _frame_obj("limited benign surface story", "Symptoms may remain local and self-limited.", ["early localized pain"], ["insufficient data"]),
            "red_frame": _frame_obj("early deep infection", "A high-harm process is possible but not yet discriminated.", ["possible deep infection"], ["no trajectory yet"]),
            "red_channel_question": detect_red_question(source_text),
            "domain_catastrophic_outcome": "Missed early deep infection with delayed source control, tissue loss, sepsis, or death.",
            "domain_red_hazard": {
                "hazard": "possible early deep infection",
                "mechanism_of_harm": "delayed recognition if progression declares itself later",
                "time_sensitivity": "uncertain",
                "closure_requirement": "additional trajectory, exam, labs, imaging, or direct evaluation",
            },
            "mechanism_of_harm": "Harm would occur if limited early data falsely closes a high-harm process.",
            "time_sensitivity": "uncertain",
            "trajectory_signal": {
                "expected_curve_under_blue_frame": "Localized pain should improve or remain bounded.",
                "observed_curve": "No sufficient temporal trajectory is available yet.",
                "violation": "Trajectory is not yet discriminating.",
                "interpretation": "The red channel is uncertain, not closed.",
            },
            "authority_pushback": [],
            "non_closure_evidence": [{"claim_or_observation": "limited early data", "why_non_closing": "Limited data cannot close a high-harm red frame."}],
            "closure_condition": {
                "required_to_close": "Additional data showing improvement, benign alternative explanation, or direct exclusion.",
                "acceptable_closure_modes": ["additional trajectory", "definitive alternative explanation", "direct evaluation"],
                "current_closure_status": "unclear",
            },
            "current_red_status": "uncertain",
            "decision_reason": "The red channel is uncertain because available data neither proves progression nor satisfies closure.",
            "recommended_threshold_action": "request_more_data",
        }
    )
    return packet


def _fournier(source_text: str, case_id: str, frame_id: str, input_prompt_hash: str) -> dict[str, Any]:
    packet = _nsti(source_text, case_id, frame_id, input_prompt_hash)
    packet.update(
        {
            "surface_story": "Progressive scrotal and perineal pain or swelling after a urethral procedure.",
            "blue_frame": _frame_obj("non-necrotizing GU inflammation", "Symptoms are attributed to a less dangerous GU explanation.", ["recent urethral procedure", "no crepitus"], ["progressive pain", "systemic signs", "skin changes"]),
            "red_frame": _frame_obj("Fournier's gangrene", "Necrotizing genital-perineal infection remains possible.", ["progressive pain", "systemic signs", "evolving skin findings"], ["no crepitus"]),
            "red_channel_question": "Could this be Fournier's or necrotizing genital-perineal infection?",
            "domain_catastrophic_outcome": "Missed necrotizing genital-perineal infection with delayed debridement, septic shock, death, or extensive tissue loss.",
            "domain_red_hazard": {
                "hazard": "missed Fournier's gangrene",
                "mechanism_of_harm": "delayed debridement",
                "time_sensitivity": "hours",
                "closure_requirement": "operative evaluation, debridement, or definitive direct exclusion",
            },
            "decision_reason": "The Fournier's red channel remains open because absence of crepitus and stability do not close progressive genital-perineal infection.",
        }
    )
    if packet["authority_pushback"]:
        packet["authority_pushback"][0]["claim"] = "no crepitus makes Fournier's less likely"
    return packet


def _sea(source_text: str, case_id: str, frame_id: str, input_prompt_hash: str) -> dict[str, Any]:
    packet = _nsti(source_text, case_id, frame_id, input_prompt_hash)
    packet.update(
        {
            "surface_story": "Back pain or viral/musculoskeletal surface story with worsening pain and emerging systemic or neurologic features.",
            "blue_frame": _frame_obj("musculoskeletal or viral syndrome", "Initial symptoms are treated as benign back pain or viral illness.", ["benign initial exam", "normal x-ray"], ["worsening pain", "fever or systemic symptoms", "meningitic or neurologic features"]),
            "red_frame": _frame_obj("spinal epidural abscess or CNS infection", "Deep infection with neurologic or CNS extension remains possible.", ["worsening pain", "systemic symptoms", "neurologic or meningitic features"], ["no deficit yet"]),
            "red_channel_question": "Could this be spinal epidural abscess with CNS or meningitic extension?",
            "domain_catastrophic_outcome": "Missed spinal epidural abscess or CNS infection with delayed therapy, neurologic injury, sepsis, death, or irreversible disability.",
            "domain_red_hazard": {
                "hazard": "missed SEA or CNS infection",
                "mechanism_of_harm": "delayed imaging, source control, or antimicrobial therapy",
                "time_sensitivity": "hours",
                "closure_requirement": "MRI, LP when appropriate, cultures, course, or definitive alternative",
            },
            "decision_reason": "The SEA or CNS infection red channel remains open because benign initial exam and reassurance do not close a worsening trajectory.",
        }
    )
    return packet


def _wirecard(source_text: str, case_id: str, frame_id: str, input_prompt_hash: str) -> dict[str, Any]:
    packet = _base_packet(source_text=source_text, case_id=case_id, frame_id=frame_id, input_prompt_hash=input_prompt_hash, domain="finance")
    packet.update(
        {
            "surface_story": "High-growth fintech with institutional credibility and repeated concerns about accounting and cash.",
            "blue_frame": _frame_obj("legitimate high-growth fintech", "Concerns are treated as misunderstanding or handled by authorities.", ["DAX-listed company", "auditor involvement", "market credibility"], ["direct cash verification remained unresolved"]),
            "red_frame": _frame_obj("unverified or nonexistent cash", "The core asset claim may be false despite institutional reassurance.", ["repeated fraud concerns", "missing cash disclosure", "banks denied holding funds"], ["why authorities accepted the story"]),
            "red_channel_question": "Does the claimed cash actually exist?",
            "domain_catastrophic_outcome": "Nonexistent or unverified cash is falsely treated as real, causing investor, creditor, auditor, regulator, and market reliance on fabricated solvency.",
            "domain_red_hazard": {
                "hazard": "unverified or nonexistent cash",
                "mechanism_of_harm": "continued reliance on false solvency",
                "time_sensitivity": "months",
                "closure_requirement": "independent direct bank confirmation or equivalent cash-control verification",
            },
            "mechanism_of_harm": "Authority reassurance substitutes for direct verification until collapse.",
            "time_sensitivity": "months",
            "trajectory_signal": {
                "expected_curve_under_blue_frame": "Repeated concerns should close through clean independent verification if cash exists.",
                "observed_curve": "Concerns accumulated and were explained or socially suppressed rather than directly closed.",
                "violation": "Persistent unresolved verification concerns are incompatible with clean closure.",
                "interpretation": "The key red channel is cash verification, not expert reassurance.",
            },
            "authority_pushback": [
                {
                    "source": "management, auditors, analysts, regulators, and market credibility",
                    "claim": "the company is legitimate and the cash or business model is acceptable",
                    "what_it_explains": ["why investors remained comfortable", "why critics were dismissed"],
                    "what_it_does_not_close": ["direct existence of cash", "independent bank confirmation", "cash control"],
                    "closure_status": "non_closing",
                }
            ],
            "non_closure_evidence": _non_closure_from_tokens(source_text)
            + [{"claim_or_observation": "auditor or market reassurance", "why_non_closing": "Reassurance is not independent direct confirmation of cash."}],
            "closure_condition": {
                "required_to_close": "Independent bank confirmation or direct verification of cash.",
                "acceptable_closure_modes": ["direct bank confirmation", "independent audit evidence tracing cash control", "transparent reconciliation"],
                "current_closure_status": "not_satisfied",
            },
            "current_red_status": "open",
            "decision_reason": "The cash-existence red channel remains open because management, auditor, market, and expert reassurance do not independently verify the cash.",
            "recommended_threshold_action": "escalate_red",
        }
    )
    packet["reasoning_quality_flags"].update({"authority_substitution_detected": True, "trajectory_violation_detected": True, "frame_tension_detected": True})
    return packet


def _svb(source_text: str, case_id: str, frame_id: str, input_prompt_hash: str) -> dict[str, Any]:
    packet = _wirecard(source_text, case_id, frame_id, input_prompt_hash)
    packet.update(
        {
            "surface_story": "Successful specialized bank with high-quality securities and concentrated uninsured depositors.",
            "blue_frame": _frame_obj("solvent specialized bank with high-quality securities", "Asset quality and prior success are treated as stabilizing.", ["high-quality securities", "prior success", "regulatory supervision"], ["large unrealized losses", "concentrated uninsured deposits", "rapid withdrawals"]),
            "red_frame": _frame_obj("liquidity-run collapse from asset-liability mismatch", "Rapid depositor flight can overwhelm available liquidity.", ["rising rates", "unrealized securities losses", "concentrated uninsured deposits", "rapid run"], ["why controls did not correct earlier"]),
            "red_channel_question": "Can the bank survive rapid depositor flight given liquidity position and asset-liability mismatch?",
            "domain_catastrophic_outcome": "Liquidity collapse and bank failure despite superficially plausible solvency or asset-quality narratives.",
            "domain_red_hazard": {
                "hazard": "liquidity-run collapse",
                "mechanism_of_harm": "depositor flight and asset-liability mismatch",
                "time_sensitivity": "hours",
                "closure_requirement": "demonstrated liquidity under stress, deposit stabilization, or credible immediate backstop",
            },
            "mechanism_of_harm": "Depositor flight creates a nonlinear liquidity crisis faster than assets can be sold or capital raised.",
            "time_sensitivity": "hours",
            "trajectory_signal": {
                "expected_curve_under_blue_frame": "A stable bank with high-quality assets should maintain confidence and meet liquidity needs.",
                "observed_curve": "Rising rates, unrealized losses, concentrated uninsured deposits, and rapid withdrawals created escalating liquidity stress.",
                "violation": "Run dynamics overwhelm the stable-bank narrative.",
                "interpretation": "Solvency and asset-quality narratives do not close immediate depositor-flight risk.",
            },
            "authority_pushback": [
                {
                    "source": "prior success, regulatory supervision, and high-quality asset narrative",
                    "claim": "the bank is fundamentally sound or the securities are safe",
                    "what_it_explains": ["why the bank was previously trusted", "why losses seemed manageable"],
                    "what_it_does_not_close": ["immediate liquidity", "concentrated uninsured depositor flight", "confidence collapse"],
                    "closure_status": "non_closing",
                }
            ],
            "closure_condition": {
                "required_to_close": "Demonstrated liquidity under stress, credible funding backstop, deposit stabilization, or successful capital/liquidity resolution.",
                "acceptable_closure_modes": ["secured liquidity backstop", "successful capital raise", "deposit outflows stabilize"],
                "current_closure_status": "not_satisfied",
            },
            "decision_reason": "The liquidity-run red channel remains open because asset-quality and prior-success narratives do not close immediate depositor-flight dynamics.",
        }
    )
    return packet


def _jingall(source_text: str, case_id: str, frame_id: str, input_prompt_hash: str) -> dict[str, Any]:
    packet = _base_packet(source_text=source_text, case_id=case_id, frame_id=frame_id, input_prompt_hash=input_prompt_hash, domain="word_puzzle")
    packet.update(
        {
            "surface_story": "A candidate answer may collapse JINGALL into JAILING.",
            "blue_frame": _frame_obj("fluent word correction", "The candidate chooses a more familiar English-looking token.", ["JAILING is familiar"], ["source token is JINGALL"]),
            "red_frame": _frame_obj("source-token corruption", "The candidate changes the authoritative source token.", ["source token JINGALL", "candidate JAILING"], []),
            "red_channel_question": "Is the candidate answer preserving the authoritative source token?",
            "domain_catastrophic_outcome": "Source-token corruption falsely treats a transformed answer as correct, causing wrong-manifold closure.",
            "domain_red_hazard": {
                "hazard": "source-token corruption",
                "mechanism_of_harm": "fluent substitution of a non-identical token",
                "time_sensitivity": "immediate",
                "closure_requirement": "exact-token match or explicit source-token verification",
            },
            "mechanism_of_harm": "Fluency substitutes for source fidelity.",
            "time_sensitivity": "immediate",
            "trajectory_signal": {
                "expected_curve_under_blue_frame": "A fluent correction may prefer JAILING.",
                "observed_curve": "The source token remains JINGALL while the candidate collapses to JAILING.",
                "violation": "The candidate changes the object under test.",
                "interpretation": "The RED frame remains active until exact source-token preservation is proven.",
            },
            "authority_pushback": [],
            "non_closure_evidence": [{"claim_or_observation": "JAILING is more fluent", "why_non_closing": "Fluency does not preserve the source token."}],
            "closure_condition": {
                "required_to_close": "Exact-token match to the authoritative source token.",
                "acceptable_closure_modes": ["exact-token verification"],
                "current_closure_status": "not_satisfied",
            },
            "current_red_status": "open",
            "decision_reason": "The source-token red channel remains open because JAILING is not identical to the authoritative JINGALL token.",
            "recommended_threshold_action": "escalate_red",
        }
    )
    packet["reasoning_quality_flags"].update({"frame_tension_detected": True, "trajectory_violation_detected": True})
    return packet


def _generic_uncertain(source_text: str, case_id: str, frame_id: str, input_prompt_hash: str) -> dict[str, Any]:
    packet = _base_packet(source_text=source_text, case_id=case_id, frame_id=frame_id, input_prompt_hash=input_prompt_hash)
    red_question = detect_red_question(source_text)
    packet.update(
        {
            "surface_story": _excerpt(source_text),
            "blue_frame": _frame_obj("default surface frame", "The available facts may support a benign or ordinary interpretation.", ["available surface facts"], ["red hazard not yet closed"]),
            "red_frame": _frame_obj("unclosed critical incident", "A high-consequence safety hazard may remain unresolved.", ["critical signal or uncertainty"], ["missing discriminator"]),
            "red_channel_question": red_question,
            "domain_catastrophic_outcome": "Missed critical incident causing preventable user harm or failed verification.",
            "domain_red_hazard": {
                "hazard": "unclosed critical incident",
                "mechanism_of_harm": "premature closure before discriminating evidence",
                "time_sensitivity": "uncertain",
                "closure_requirement": "case-specific discriminator or verified benign alternative",
            },
            "mechanism_of_harm": "Premature closure can miss a critical incident.",
            "time_sensitivity": "uncertain",
            "trajectory_signal": {
                "expected_curve_under_blue_frame": "The benign frame should explain the source facts without residual red tension.",
                "observed_curve": "The current report does not provide enough discriminator detail.",
                "violation": "Trajectory is unresolved.",
                "interpretation": "Hold for more case-specific reasoning.",
            },
            "authority_pushback": [],
            "non_closure_evidence": _non_closure_from_tokens(source_text)
            or [{"claim_or_observation": "missing discriminator", "why_non_closing": "Missing discriminators cannot close the red channel."}],
            "closure_condition": {
                "required_to_close": "A case-specific discriminator or definitive alternative explanation.",
                "acceptable_closure_modes": ["direct observation", "definitive alternative explanation", "risk collapse below action threshold"],
                "current_closure_status": "unclear",
            },
            "current_red_status": "uncertain",
            "decision_reason": "The red channel is uncertain because the report lacks a case-specific discriminator that would close the domain hazard.",
            "recommended_threshold_action": "request_more_data",
        }
    )
    return packet


def _frame_obj(name: str, description: str, support: list[str], weak: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "supporting_evidence": support,
        "unexplained_or_weakly_explained_evidence": weak,
    }


def _copy_value(value: Any) -> Any:
    return copy.deepcopy(value)


def _closure_basis_from_packet(packet: dict[str, Any]) -> str:
    existing = packet.get("closure_basis")
    if isinstance(existing, str) and existing.strip():
        return existing.strip()
    if packet.get("current_red_status") != "closed":
        return ""
    closure = packet.get("closure_condition")
    if not isinstance(closure, dict):
        return ""
    basis = closure.get("required_to_close")
    return basis.strip() if isinstance(basis, str) else ""


def _drift_signal_from_trajectory(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    violation = value.get("violation")
    if isinstance(violation, str) and violation.strip():
        return violation.strip()
    interpretation = value.get("interpretation")
    return interpretation.strip() if isinstance(interpretation, str) else ""


def _non_closure_from_tokens(source_text: str) -> list[dict[str, str]]:
    return [
        {"claim_or_observation": item["token"], "why_non_closing": item["why_non_closing"]}
        for item in detect_false_reassurance_tokens(source_text)
    ]


def _looks_like_domain_harm(text: str) -> bool:
    lowered = text.lower()
    has_harm = any(term in lowered for term in _DOMAIN_HARM_TERMS)
    has_process = any(term in lowered for term in _PROCESS_SAFETY_TERMS)
    return has_harm and not (has_process and not has_harm)


def _is_generic_process_receipt(text: str) -> bool:
    lowered = text.lower().strip()
    return any(term in lowered for term in _GENERIC_DECISION_RECEIPTS) or (
        any(term in lowered for term in _PROCESS_SAFETY_TERMS)
        and not any(term in lowered for term in ("because", "trajectory", "cash", "liquidity", "nsti", "source-token", "direct"))
    )


def _frames_distinct(blue: Any, red: Any) -> bool:
    if not isinstance(blue, dict) or not isinstance(red, dict):
        return False
    blue_name = str(blue.get("name") or "").strip().lower()
    red_name = str(red.get("name") or "").strip().lower()
    blue_desc = str(blue.get("description") or "").strip().lower()
    red_desc = str(red.get("description") or "").strip().lower()
    return bool(blue_name and red_name and blue_desc and red_desc and (blue_name != red_name or blue_desc != red_desc))


def _has_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value)
    if isinstance(value, list):
        return bool(value)
    return value is not None


def _non_empty_list(value: Any) -> bool:
    return isinstance(value, list) and len(value) > 0


def _nested_text(value: Any, key: str) -> str:
    if not isinstance(value, dict):
        return ""
    raw = value.get(key)
    return raw.strip() if isinstance(raw, str) else ""


def _dedupe_rows(rows: list[dict[str, str]], key: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for row in rows:
        marker = row.get(key, "")
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(row)
    return deduped


def _excerpt(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    return normalized if len(normalized) <= limit else f"{normalized[:limit]}..."
