from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

SCHEMA = "nepsis.v3_orchestration_packet@0.1.0"
INTEGRITY_SEAL_VERSION = "hmac-sha256:v1"
DEFAULT_TTL_SECONDS = 6 * 60 * 60
LAYER_ORDER = ["intake", "red", "manifold", "blue", "still", "synthesis", "audit"]

_FIELD_STATES = {"unknown", "none_found", "not_applicable", "present"}
_SHARED_CONTRACT_FIELDS = (
    "goal_scope",
    "red_triggers",
    "blue_opportunity_space",
    "constraints",
    "manifold_match_mismatch",
    "still_blockers",
    "unresolved_questions",
    "audit_notes",
    "proposed_status",
    "lock_eligibility",
)
_RAW_SECRET_METADATA_KEYS = {
    "authorization",
    "capability_token",
    "x-nepsis-capability-token",
    "api_key",
    "openai_api_key",
    "anthropic_api_key",
    "gemini_api_key",
}


def canonical_hash(value: Any) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(value)).hexdigest()}"


def artifact_hash(artifact: dict[str, Any]) -> str:
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be an object")
    return canonical_hash(artifact)


def start_v3_orchestration(
    *,
    goal: str,
    scope: str,
    initial_context: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_goal = _required_text(goal, "goal")
    resolved_scope = _required_text(scope, "scope")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be > 0")
    created = _now(now)
    packet = {
        "schema": SCHEMA,
        "run_id": str(uuid4()),
        "packet_seq": 0,
        "created_at": _format_time(created),
        "expires_at": _format_time(created + timedelta(seconds=ttl_seconds)),
        "status": "active",
        "goal": resolved_goal,
        "scope": resolved_scope,
        "initial_context": initial_context.strip() if isinstance(initial_context, str) else "",
        "current_layer": "intake",
        "layer_order": list(LAYER_ORDER),
        "locked_layers": {},
        "current_proposal": None,
        "final_response_packet": None,
        "abandon_reason": "",
        "lineage": [{"event": "start", "at": _format_time(created), "layer": None}],
    }
    return _seal_packet(packet)


def inspect_v3_orchestration(packet: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    _validate_packet(packet, now=now)
    proposal = packet.get("current_proposal")
    validation = proposal.get("validation") if isinstance(proposal, dict) else {}
    lock_eligible = (
        isinstance(validation, dict)
        and validation.get("schema_valid") is True
        and validation.get("lock_eligible") is True
    )
    return {
        "valid": True,
        "schema": packet["schema"],
        "run_id": packet["run_id"],
        "packet_seq": packet["packet_seq"],
        "status": packet["status"],
        "current_layer": packet.get("current_layer"),
        "locked_layers": list(packet["locked_layers"].keys()),
        "pending_proposal": isinstance(proposal, dict),
        "lock_eligible": lock_eligible,
        "expires_at": packet["expires_at"],
        "next_legal_actions": _legal_actions(packet, lock_eligible=lock_eligible),
    }


def propose_v3_layer(
    packet: dict[str, Any],
    *,
    layer: str,
    artifact: dict[str, Any],
    draft_metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_active_packet(packet, now=now)
    current_layer = packet.get("current_layer")
    if layer != current_layer:
        raise ValueError(f"propose_v3_layer layer must match current layer: {current_layer}")
    if layer in packet.get("locked_layers", {}):
        raise ValueError(f"layer {layer} is already locked")
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be an object")

    created = _now(now)
    resolved_hash = artifact_hash(artifact)
    validation = _validate_layer_artifact(layer, artifact)
    updated = _copy_packet_body(packet)
    updated["packet_seq"] = int(updated["packet_seq"]) + 1
    updated["current_proposal"] = {
        "layer": layer,
        "artifact": _json_copy(artifact),
        "artifact_hash": resolved_hash,
        "draft_metadata": _normalize_draft_metadata(draft_metadata, created_at=created, draft_hash=resolved_hash),
        "validation": validation,
    }
    updated["lineage"] = _append_lineage(
        updated,
        {"event": "propose", "at": _format_time(created), "layer": layer, "artifact_hash": resolved_hash},
    )
    return _seal_packet(updated)


def lock_v3_layer(
    packet: dict[str, Any],
    *,
    layer: str,
    lock_assertion: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_active_packet(packet, now=now)
    locked_layers = packet.get("locked_layers", {})
    if isinstance(locked_layers, dict) and layer in locked_layers:
        raise ValueError(f"layer {layer} is already locked")
    current_layer = packet.get("current_layer")
    if layer != current_layer:
        raise ValueError(f"lock_v3_layer layer must match current layer: {current_layer}")

    proposal = packet.get("current_proposal")
    if not isinstance(proposal, dict):
        raise ValueError("lock_v3_layer requires a current proposal")
    if proposal.get("layer") != layer:
        raise ValueError("current proposal is for the wrong layer")

    assertion = _validate_lock_assertion(lock_assertion, expected_hash=str(proposal.get("artifact_hash") or ""))
    artifact = proposal.get("artifact")
    if not isinstance(artifact, dict):
        raise ValueError("current proposal artifact must be an object")
    validation = _validate_layer_artifact(layer, artifact)
    if validation["lock_eligible"] is not True:
        raise ValueError("; ".join(validation["errors"]) or f"{layer} layer is not lock eligible")

    locked_at = _now(now)
    artifact_digest = str(proposal["artifact_hash"])
    updated = _copy_packet_body(packet)
    updated["packet_seq"] = int(updated["packet_seq"]) + 1
    updated["locked_layers"] = dict(updated["locked_layers"])
    updated["locked_layers"][layer] = {
        "artifact": _json_copy(artifact),
        "artifact_hash": artifact_digest,
        "locked_at": _format_time(locked_at),
        "locked_by_assertion_hash": canonical_hash(assertion),
        "lock_assertion": {
            "assertion_text_hash": canonical_hash(assertion["assertion_text"]),
            "proposal_hash": assertion["proposal_hash"],
            "lock_nonce_hash": canonical_hash(assertion["lock_nonce"]),
        },
        "validation": validation,
    }
    updated["current_proposal"] = None
    updated["current_layer"] = _next_layer(layer)
    updated["lineage"] = _append_lineage(
        updated,
        {"event": "lock", "at": _format_time(locked_at), "layer": layer, "artifact_hash": artifact_digest},
    )
    return _seal_packet(updated)


def finalize_v3_orchestration(packet: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    _validate_active_packet(packet, now=now)
    locked_layers = packet.get("locked_layers")
    if not isinstance(locked_layers, dict) or set(locked_layers.keys()) != set(LAYER_ORDER):
        raise ValueError("finalize_v3_orchestration requires all layers locked")

    final_response = _build_final_response_packet(packet)
    finalized_at = _now(now)
    updated = _copy_packet_body(packet)
    updated["packet_seq"] = int(updated["packet_seq"]) + 1
    updated["status"] = "finalized"
    updated["current_layer"] = None
    updated["current_proposal"] = None
    updated["final_response_packet"] = final_response
    updated["lineage"] = _append_lineage(
        updated,
        {"event": "finalize", "at": _format_time(finalized_at), "layer": None},
    )
    return _seal_packet(updated)


def abandon_v3_orchestration(
    packet: dict[str, Any],
    *,
    reason: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_active_packet(packet, now=now)
    abandoned_at = _now(now)
    updated = _copy_packet_body(packet)
    updated["packet_seq"] = int(updated["packet_seq"]) + 1
    updated["status"] = "abandoned"
    updated["current_layer"] = None
    updated["abandon_reason"] = reason.strip() if isinstance(reason, str) else ""
    updated["lineage"] = _append_lineage(
        updated,
        {"event": "abandon", "at": _format_time(abandoned_at), "layer": None},
    )
    return _seal_packet(updated)


def _build_final_response_packet(packet: dict[str, Any]) -> dict[str, Any]:
    locked = packet["locked_layers"]
    artifacts = {layer: locked[layer]["artifact"] for layer in LAYER_ORDER}
    risks = _dedupe(_collect_layer_findings(artifacts, "risk"))
    ruins = _dedupe(_collect_layer_findings(artifacts, "ruin"))
    wins = _dedupe(_collect_layer_findings(artifacts, "win"))
    recommendations = _recommendations_from_synthesis(artifacts["synthesis"])
    for recommendation in recommendations:
        if recommendation["unresolved_ruin"]:
            raise ValueError("finalization blocked because a recommendation carries unresolved ruin")

    unresolved = _dedupe(
        _shared_field_items(artifacts)
        + _audit_uncertainty_items(artifacts["audit"])
    )
    lineage_hashes = {layer: locked[layer]["artifact_hash"] for layer in LAYER_ORDER}
    return {
        "schema": "nepsis.v3_final_response_packet@0.1.0",
        "run_id": packet["run_id"],
        "goal": _intake_goal(artifacts["intake"], fallback=str(packet.get("goal") or "")),
        "risk": risks,
        "ruin": ruins,
        "win": wins,
        "recommendations": recommendations,
        "unresolved_questions": unresolved,
        "audit_trace": _json_copy(packet.get("lineage")) or [],
        "lineage_hashes": lineage_hashes,
        "rollback_policy": "pure_stateless_ttl_forks_allowed",
    }


def _recommendations_from_synthesis(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    synthesis = artifact.get("synthesis")
    rows = synthesis.get("recommendations") if isinstance(synthesis, dict) else []
    recommendations: list[dict[str, Any]] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            recommendations.append(
                {
                    "text": str(row.get("text") or ""),
                    "supports_win": _string_list(row.get("supports_win")),
                    "mitigates_risk": _string_list(row.get("mitigates_risk")),
                    "unresolved_ruin": _string_list(row.get("unresolved_ruin")),
                    "source_layers": ["synthesis"],
                }
            )
    return [item for item in recommendations if item["text"]]


def _collect_layer_findings(artifacts: dict[str, dict[str, Any]], key: str) -> list[str]:
    values: list[str] = []
    for artifact in artifacts.values():
        findings = artifact.get("layer_findings")
        if isinstance(findings, dict):
            values.extend(_string_list(findings.get(key)))
    return values


def _shared_field_items(artifacts: dict[str, dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for artifact in artifacts.values():
        field = artifact.get("unresolved_questions")
        if isinstance(field, dict) and field.get("status") == "present":
            values.extend(_string_list(field.get("items")))
    return values


def _audit_uncertainty_items(audit_artifact: dict[str, Any]) -> list[str]:
    audit = audit_artifact.get("audit")
    if not isinstance(audit, dict):
        return []
    return _string_list(audit.get("unresolved_uncertainty"))


def _intake_goal(intake_artifact: dict[str, Any], *, fallback: str) -> str:
    intake = intake_artifact.get("intake")
    if isinstance(intake, dict) and isinstance(intake.get("goal"), str) and intake["goal"].strip():
        return intake["goal"].strip()
    return fallback


def _validate_layer_artifact(layer: str, artifact: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(artifact, dict):
        errors.append("artifact must be an object")
    elif artifact.get("layer") not in {None, layer}:
        errors.append("artifact layer does not match current layer")
    if isinstance(artifact, dict):
        _validate_shared_contract(artifact, errors)
        _validate_layer_specific_contract(layer, artifact, errors, warnings)
    return {
        "schema_valid": not any("must be an object" in error or "is required" in error for error in errors),
        "lock_eligible": not errors,
        "errors": errors,
        "warnings": warnings,
    }


def _validate_shared_contract(artifact: dict[str, Any], errors: list[str]) -> None:
    for name in _SHARED_CONTRACT_FIELDS:
        raw = artifact.get(name)
        if not isinstance(raw, dict):
            errors.append(f"{name} is required and must be an object")
            continue
        status = raw.get("status")
        if status not in _FIELD_STATES:
            errors.append(f"{name}.status must be one of: {', '.join(sorted(_FIELD_STATES))}")
        items = raw.get("items")
        if not isinstance(items, list):
            errors.append(f"{name}.items must be a list")
        elif status == "present" and not items:
            errors.append(f"{name}.items cannot be empty when status is present")
        rationale = raw.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            errors.append(f"{name}.rationale is required")


def _validate_layer_specific_contract(
    layer: str,
    artifact: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> None:
    del warnings
    if layer == "intake":
        _require_section_fields(
            artifact,
            "intake",
            errors,
            text_fields=("goal", "scope"),
            list_fields=("assumptions", "unresolved_questions"),
        )
    elif layer == "red":
        _require_section_fields(
            artifact,
            "red",
            errors,
            list_fields=("triggers", "ruin_paths", "constraints", "safety_blockers"),
        )
    elif layer == "manifold":
        _require_section_fields(
            artifact,
            "manifold",
            errors,
            list_fields=("matches", "mismatches", "false_analogies"),
        )
    elif layer == "blue":
        _require_section_fields(artifact, "blue", errors, list_fields=("wins", "bounded_by_red"))
    elif layer == "still":
        _require_section_fields(
            artifact,
            "still",
            errors,
            text_fields=("go_no_go",),
            list_fields=("blockers", "restraint_conditions"),
            allow_empty_lists={"blockers"},
        )
    elif layer == "synthesis":
        synthesis = artifact.get("synthesis")
        if not isinstance(synthesis, dict):
            errors.append("synthesis section is required")
            return
        recommendations = synthesis.get("recommendations")
        if not isinstance(recommendations, list) or not recommendations:
            errors.append("synthesis.recommendations must be a non-empty list")
            return
        for index, item in enumerate(recommendations):
            if not isinstance(item, dict):
                errors.append(f"synthesis.recommendations[{index}] must be an object")
                continue
            if not isinstance(item.get("text"), str) or not item["text"].strip():
                errors.append(f"synthesis.recommendations[{index}].text is required")
            for key in ("supports_win", "mitigates_risk", "unresolved_ruin"):
                if not isinstance(item.get(key), list):
                    errors.append(f"synthesis.recommendations[{index}].{key} must be a list")
    elif layer == "audit":
        audit = artifact.get("audit")
        if not isinstance(audit, dict):
            errors.append("audit section is required")
            return
        if audit.get("lineage_checked") is not True:
            errors.append("audit.lineage_checked must be true")
        if audit.get("risk_ruin_win_consistent") is not True:
            errors.append("audit.risk_ruin_win_consistent must be true")
        if not isinstance(audit.get("unresolved_uncertainty"), list):
            errors.append("audit.unresolved_uncertainty must be a list")
    else:
        errors.append(f"unsupported layer: {layer}")


def _require_section_fields(
    artifact: dict[str, Any],
    section_name: str,
    errors: list[str],
    *,
    text_fields: tuple[str, ...] = (),
    list_fields: tuple[str, ...] = (),
    allow_empty_lists: set[str] | None = None,
) -> None:
    section = artifact.get(section_name)
    if not isinstance(section, dict):
        errors.append(f"{section_name} section is required")
        return
    empty_ok = allow_empty_lists or set()
    for field in text_fields:
        if not isinstance(section.get(field), str) or not section[field].strip():
            errors.append(f"{section_name}.{field} is required")
    for field in list_fields:
        value = section.get(field)
        if not isinstance(value, list):
            errors.append(f"{section_name}.{field} must be a list")
        elif not value and field not in empty_ok:
            errors.append(f"{section_name}.{field} cannot be empty")


def _validate_lock_assertion(value: dict[str, Any], *, expected_hash: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError("lock_assertion must be an object")
    if value.get("asserted") is not True:
        raise ValueError("lock_assertion.asserted must be true")
    assertion_text = _required_text(value.get("assertion_text"), "lock_assertion.assertion_text")
    proposal_hash = _required_text(value.get("proposal_hash"), "lock_assertion.proposal_hash")
    lock_nonce = _required_text(value.get("lock_nonce"), "lock_assertion.lock_nonce")
    if proposal_hash != expected_hash:
        raise ValueError("lock assertion proposal hash does not match current proposal hash")
    return {
        "assertion_text": assertion_text,
        "proposal_hash": proposal_hash,
        "lock_nonce": lock_nonce,
    }


def _normalize_draft_metadata(
    value: dict[str, Any] | None,
    *,
    created_at: datetime,
    draft_hash: str,
) -> dict[str, Any]:
    metadata = _json_copy(value) if isinstance(value, dict) else {}
    for key in metadata:
        if key.strip().lower() in _RAW_SECRET_METADATA_KEYS:
            raise ValueError(f"draft_metadata must not include raw secret field: {key}")
    return {
        "host": _optional_text(metadata.get("host")),
        "model_name": _optional_text(metadata.get("model_name", metadata.get("modelName"))),
        "draft_hash": draft_hash,
        "prompt_hash": _optional_text(metadata.get("prompt_hash", metadata.get("promptHash"))),
        "created_at": _format_time(created_at),
    }


def _validate_packet(packet: dict[str, Any], *, now: datetime | None) -> None:
    if not isinstance(packet, dict):
        raise ValueError("v3 orchestration packet must be an object")
    if packet.get("schema") != SCHEMA:
        raise ValueError(f"v3 orchestration packet schema must be {SCHEMA}")
    if packet.get("layer_order") != LAYER_ORDER:
        raise ValueError("v3 orchestration packet layer_order mismatch")
    if not isinstance(packet.get("run_id"), str) or not packet["run_id"]:
        raise ValueError("v3 orchestration packet run_id is required")
    if not isinstance(packet.get("packet_seq"), int):
        raise ValueError("v3 orchestration packet packet_seq must be an integer")
    locked = packet.get("locked_layers")
    if not isinstance(locked, dict):
        raise ValueError("v3 orchestration packet locked_layers must be an object")
    lineage = packet.get("lineage")
    if not isinstance(lineage, list):
        raise ValueError("v3 orchestration packet lineage must be a list")
    _verify_packet_integrity(packet)
    if _now(now) > _parse_time(str(packet.get("expires_at") or "")):
        raise ValueError("v3 orchestration packet expired")


def _validate_active_packet(packet: dict[str, Any], *, now: datetime | None) -> None:
    _validate_packet(packet, now=now)
    if packet.get("status") != "active":
        raise ValueError("v3 orchestration packet must be active")


def _seal_packet(packet: dict[str, Any]) -> dict[str, Any]:
    sealed = _json_copy(packet) or {}
    integrity = sealed.get("integrity") if isinstance(sealed.get("integrity"), dict) else {}
    sealed["integrity"] = {
        "seal_version": INTEGRITY_SEAL_VERSION,
        "sealed_fields": sorted(key for key in sealed.keys() if key != "integrity"),
        "seal": "",
    }
    if isinstance(integrity, dict) and isinstance(integrity.get("sealed_at"), str):
        sealed["integrity"]["sealed_at"] = integrity["sealed_at"]
    sealed["integrity"]["seal"] = _packet_integrity_seal(sealed)
    return sealed


def _verify_packet_integrity(packet: dict[str, Any]) -> None:
    integrity = packet.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("v3 orchestration packet integrity seal is required")
    if integrity.get("seal_version") != INTEGRITY_SEAL_VERSION:
        raise ValueError("v3 orchestration packet integrity seal_version is unsupported")
    seal = integrity.get("seal")
    if not isinstance(seal, str) or not seal:
        raise ValueError("v3 orchestration packet integrity seal is required")
    expected = _packet_integrity_seal(packet)
    if not hmac.compare_digest(seal, expected):
        raise ValueError("v3 orchestration packet integrity seal verification failed")


def _packet_integrity_seal(packet: dict[str, Any]) -> str:
    return hmac.new(_v3_packet_seal_secret(), _canonical_json(_packet_integrity_payload(packet)), hashlib.sha256).hexdigest()


def _packet_integrity_payload(packet: dict[str, Any]) -> dict[str, Any]:
    body = _json_copy(packet) or {}
    integrity = body.get("integrity")
    if isinstance(integrity, dict):
        integrity = dict(integrity)
        integrity.pop("seal", None)
        body["integrity"] = integrity
    return _normalize_integrity_json(body)


def _normalize_integrity_json(value: Any) -> Any:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_normalize_integrity_json(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_integrity_json(item) for key, item in value.items()}
    return value


def _v3_packet_seal_secret() -> bytes:
    raw = os.getenv("NEPSIS_V3_PACKET_SEAL_SECRET") or os.getenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET")
    if raw and raw.strip():
        return raw.strip().encode("utf-8")
    raise ValueError(
        "NEPSIS_V3_PACKET_SEAL_SECRET or NEPSIS_OPERATOR_PACKET_SEAL_SECRET "
        "is required for V3 stateless packet sealing"
    )


def _legal_actions(packet: dict[str, Any], *, lock_eligible: bool) -> list[str]:
    if packet.get("status") != "active":
        return []
    if packet.get("current_layer") is None:
        return ["finalize_v3_orchestration", "abandon_v3_orchestration"]
    actions = ["propose_v3_layer", "abandon_v3_orchestration"]
    if isinstance(packet.get("current_proposal"), dict) and lock_eligible:
        actions.insert(0, "lock_v3_layer")
    return actions


def _next_layer(layer: str) -> str | None:
    index = LAYER_ORDER.index(layer)
    if index + 1 >= len(LAYER_ORDER):
        return None
    return LAYER_ORDER[index + 1]


def _copy_packet_body(packet: dict[str, Any]) -> dict[str, Any]:
    copied = _json_copy(packet) or {}
    copied.pop("integrity", None)
    return copied


def _append_lineage(packet: dict[str, Any], event: dict[str, Any]) -> list[dict[str, Any]]:
    lineage = _json_copy(packet.get("lineage")) or []
    lineage.append(event)
    return lineage


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    resolved = value.strip()
    return resolved or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            out.append(value)
            seen.add(value)
    return out


def _json_copy(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value, sort_keys=True))


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return _now(value).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    if not value:
        raise ValueError("timestamp is required")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


__all__ = [
    "LAYER_ORDER",
    "SCHEMA",
    "abandon_v3_orchestration",
    "artifact_hash",
    "canonical_hash",
    "finalize_v3_orchestration",
    "inspect_v3_orchestration",
    "lock_v3_layer",
    "propose_v3_layer",
    "start_v3_orchestration",
]
