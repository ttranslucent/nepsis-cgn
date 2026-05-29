from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..api.operator_packet import (
    abandon_packet,
    commit_iteration,
    inspect_operator_packet,
    lock_frame,
    lock_report,
    packet_hash,
    run_report,
    set_threshold_decision,
    start_operator_packet,
)
from ..core.mvp import build_nepsis_mvp_packet

LOGGER = logging.getLogger("nepsis_cgn.mcp.handler")
PROTOCOL_VERSION = "2025-06-18"

RouteManifestFn = Callable[[], list[dict[str, str]]]


@dataclass(frozen=True)
class CapabilityAuth:
    authorized: bool
    token_id: str | None = None


def mcp_tools() -> list[dict[str, Any]]:
    packet_schema = {"type": "object", "description": "Current nepsis.operator_packet v2 object."}
    return [
        {
            "name": "run_mvp",
            "description": "Run the public deterministic NepsisCGN MVP packet demo.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "case_id": {"type": "string", "enum": ["jailing", "clinical"]},
                    "input_text": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_mvp_schema",
            "description": "Return the canonical MVP packet schema fields and supported cases.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "health",
            "description": "Return NepsisCGN MCP bridge health.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "get_routes",
            "description": "Return the NepsisCGN API route manifest.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "start_operator_packet",
            "description": "Create a stateless operator packet. The model host owns future packet storage.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "family": {"type": "string", "enum": ["puzzle", "clinical", "safety"]},
                    "frame": {"type": "object"},
                    "governance_costs": {"type": "object"},
                    "governance_calibration": {"type": "object"},
                    "manifest_path": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_session_state",
            "description": "Inspect a stateless operator packet phase and legal next tools.",
            "inputSchema": {
                "type": "object",
                "properties": {"packet": packet_schema},
                "additionalProperties": False,
            },
        },
        {
            "name": "lock_frame",
            "description": "Guarded transition: lock an operator frame into a stateless packet.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "packet": packet_schema,
                    "family": {"type": "string", "enum": ["puzzle", "clinical", "safety"]},
                    "frame": {"type": "object"},
                    "governance_costs": {"type": "object"},
                    "governance_calibration": {"type": "object"},
                    "manifest_path": {"type": "string"},
                },
                "required": ["packet", "frame"],
                "additionalProperties": False,
            },
        },
        {
            "name": "run_report",
            "description": "Guarded transition: run CALL + REPORT + EVALUATE against the packet.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "packet": packet_schema,
                    "report_text": {"type": "string"},
                    "sign": {"type": "object"},
                    "interpretation": {"type": "object"},
                },
                "required": ["packet", "report_text", "sign"],
                "additionalProperties": False,
            },
        },
        {
            "name": "lock_report",
            "description": "Guarded transition: lock the latest passing report evaluation.",
            "inputSchema": {
                "type": "object",
                "properties": {"packet": packet_schema},
                "required": ["packet"],
                "additionalProperties": False,
            },
        },
        {
            "name": "set_threshold_decision",
            "description": "Guarded transition: set recommend/hold after a locked report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "packet": packet_schema,
                    "decision": {"type": "string", "enum": ["recommend", "hold"]},
                    "hold_reason": {"type": "string"},
                },
                "required": ["packet", "decision"],
                "additionalProperties": False,
            },
        },
        {
            "name": "commit_iteration",
            "description": "Guarded transition: commit only after required prior gates are proven in the packet trace.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "packet": packet_schema,
                    "carry_forward_frame": {"type": "object"},
                },
                "required": ["packet"],
                "additionalProperties": False,
            },
        },
        {
            "name": "abandon_packet",
            "description": "Emit an abandoned-loop fragment and reset the packet to frame draft.",
            "inputSchema": {
                "type": "object",
                "properties": {"packet": packet_schema, "reason": {"type": "string"}},
                "required": ["packet"],
                "additionalProperties": False,
            },
        },
    ]


def handle_mcp_request(
    body: dict[str, Any],
    *,
    headers: dict[str, Any] | None = None,
    require_capability_token: bool,
    server_name: str,
    route_manifest_fn: RouteManifestFn | None = None,
    request_id: str | None = None,
) -> dict[str, Any] | None:
    jsonrpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})
    if body.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _mcp_error(jsonrpc_id, -32600, "Invalid JSON-RPC request.")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _mcp_error(jsonrpc_id, -32602, "JSON-RPC params must be an object.")

    if method == "initialize":
        return _mcp_result(
            jsonrpc_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": server_name, "version": "0.3.0"},
                "capabilities": {"tools": {}},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _mcp_result(jsonrpc_id, {"tools": mcp_tools()})
    if method == "tools/call":
        return _call_tool(
            jsonrpc_id,
            params,
            headers=headers or {},
            require_capability_token=require_capability_token,
            route_manifest_fn=route_manifest_fn,
            request_id=request_id,
        )
    return _mcp_error(jsonrpc_id, -32601, f"Unsupported MCP method: {method}")


def authorize_capability(headers: dict[str, Any]) -> CapabilityAuth:
    token = _request_capability_token(headers)
    if token is None:
        return CapabilityAuth(False)
    digest = _sha256(token)
    for token_id, configured_hash in _configured_token_hashes().items():
        if hmac_compare(digest, configured_hash):
            return CapabilityAuth(True, token_id=token_id)
    return CapabilityAuth(False)


def _call_tool(
    jsonrpc_id: Any,
    params: dict[str, Any],
    *,
    headers: dict[str, Any],
    require_capability_token: bool,
    route_manifest_fn: RouteManifestFn | None,
    request_id: str | None,
) -> dict[str, Any]:
    started = time.perf_counter()
    name = params.get("name")
    arguments = params.get("arguments", {})
    auth = authorize_capability(headers)
    if not isinstance(name, str):
        return _mcp_error(jsonrpc_id, -32602, "MCP tools/call requires string field 'name'.")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _mcp_error(jsonrpc_id, -32602, "MCP tool arguments must be an object.")
    if require_capability_token and not auth.authorized:
        response = _mcp_error(jsonrpc_id, -32001, "MCP tool requires a valid Nepsis capability token.")
        _log_tool_call(request_id, name, "unauthorized", auth.token_id, arguments, started)
        return response

    try:
        result = _tool_payload(name, arguments, route_manifest_fn)
    except KeyError:
        response = _mcp_error(jsonrpc_id, -32601, f"Unknown MCP tool: {name}")
        _log_tool_call(request_id, name, "unknown", auth.token_id, arguments, started)
        return response
    except ValueError as exc:
        response = _mcp_error(jsonrpc_id, -32602, str(exc))
        _log_tool_call(request_id, name, "invalid", auth.token_id, arguments, started)
        return response

    is_error = result.get("schema_id") == "nepsis.phase_rejection"
    response = _tool_result(jsonrpc_id, result, is_error=is_error)
    _log_tool_call(request_id, name, "phase_rejection" if is_error else "ok", auth.token_id, arguments, started, result)
    return response


def _tool_payload(
    name: str,
    arguments: dict[str, Any],
    route_manifest_fn: RouteManifestFn | None,
) -> dict[str, Any]:
    if name == "run_mvp":
        return _run_mvp(arguments)
    if name == "get_mvp_schema":
        return _mvp_schema()
    if name == "health":
        return {"ok": True, "transport": "mcp", "model_provider_keys_required": False}
    if name == "get_routes":
        return {"routes": route_manifest_fn() if route_manifest_fn is not None else []}
    if name == "start_operator_packet":
        return start_operator_packet(
            family=arguments.get("family", "safety"),
            frame=_optional_object(arguments, "frame"),
            governance_costs=_optional_object(arguments, "governance_costs"),
            governance_calibration=_optional_object(arguments, "governance_calibration"),
            manifest_path=_optional_string(arguments, "manifest_path"),
        )
    if name == "get_session_state":
        packet = arguments.get("packet")
        return inspect_operator_packet(packet if isinstance(packet, dict) else None)
    if name == "lock_frame":
        return lock_frame(
            packet=_required_object(arguments, "packet"),
            family=arguments.get("family"),
            frame=_required_object(arguments, "frame"),
            governance_costs=_optional_object(arguments, "governance_costs"),
            governance_calibration=_optional_object(arguments, "governance_calibration"),
            manifest_path=_optional_string(arguments, "manifest_path"),
        )
    if name == "run_report":
        return run_report(
            packet=_required_object(arguments, "packet"),
            report_text=_required_string(arguments, "report_text"),
            sign=_required_object(arguments, "sign"),
            interpretation=_optional_object(arguments, "interpretation"),
        )
    if name == "lock_report":
        return lock_report(packet=_required_object(arguments, "packet"))
    if name == "set_threshold_decision":
        return set_threshold_decision(
            packet=_required_object(arguments, "packet"),
            decision=_required_string(arguments, "decision"),
            hold_reason=str(arguments.get("hold_reason") or ""),
        )
    if name == "commit_iteration":
        return commit_iteration(
            packet=_required_object(arguments, "packet"),
            carry_forward_frame=_optional_object(arguments, "carry_forward_frame"),
        )
    if name == "abandon_packet":
        return abandon_packet(packet=_required_object(arguments, "packet"), reason=str(arguments.get("reason") or ""))
    raise KeyError(name)


def _run_mvp(arguments: dict[str, Any]) -> dict[str, Any]:
    case_id = arguments.get("case_id", arguments.get("case", "jailing"))
    if case_id not in {"jailing", "clinical"}:
        raise ValueError("case_id must be one of: jailing, clinical")
    input_text = arguments.get("input_text", arguments.get("inputText"))
    if input_text is not None and not isinstance(input_text, str):
        raise ValueError("input_text must be a string when provided")
    return build_nepsis_mvp_packet(case_id=case_id, input_text=input_text)


def _mvp_schema() -> dict[str, Any]:
    return {
        "schema_id": "nepsis.mvp_packet",
        "supported_cases": ["jailing", "clinical"],
        "top_level_fields": [
            "case_id",
            "input_text",
            "observations",
            "constraints",
            "red_channel",
            "still",
            "blue_channel",
            "contradiction_monitor",
            "denominator_collapse",
            "non_quiescence",
            "zeroback",
            "voronoi_commitment",
            "state_feedback",
            "audit_trace",
            "final_output",
        ],
    }


def _required_object(arguments: dict[str, Any], name: str) -> dict[str, Any]:
    value = arguments.get(name)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _optional_object(arguments: dict[str, Any], name: str) -> dict[str, Any] | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object when provided")
    return value


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _optional_string(arguments: dict[str, Any], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string when provided")
    return value or None


def _request_capability_token(headers: dict[str, Any]) -> str | None:
    auth = headers.get("authorization") or headers.get("Authorization")
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    direct = headers.get("x-nepsis-capability-token") or headers.get("X-Nepsis-Capability-Token")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    return None


def _configured_token_hashes() -> dict[str, str]:
    raw = os.getenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", "")
    hashes: dict[str, str] = {}
    for index, item in enumerate(raw.split(","), start=1):
        value = item.strip()
        if not value:
            continue
        token_id: str
        digest: str
        if ":" in value:
            token_id, digest = value.split(":", 1)
            token_id = token_id.strip() or f"token-{index}"
            digest = digest.strip().lower()
        else:
            digest = value.lower()
            token_id = f"token-{index}"
        if len(digest) == 64 and all(char in "0123456789abcdef" for char in digest):
            hashes[token_id] = digest
    return hashes


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


def _tool_result(request_id: Any, payload: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
    return _mcp_result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
            "isError": is_error,
        },
    )


def _mcp_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _mcp_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _log_tool_call(
    request_id: str | None,
    tool_name: str,
    status: str,
    token_id: str | None,
    arguments: dict[str, Any],
    started: float,
    result: dict[str, Any] | None = None,
) -> None:
    packet = arguments.get("packet")
    logged_packet = packet if isinstance(packet, dict) else result if isinstance(result, dict) else None
    LOGGER.info(
        json.dumps(
            {
                "event": "mcp_tool_call",
                "request_id": request_id,
                "tool": tool_name,
                "status": status,
                "token_id": token_id,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "packet_hash": packet_hash(logged_packet),
            }
        )
    )


__all__ = [
    "PROTOCOL_VERSION",
    "authorize_capability",
    "handle_mcp_request",
    "mcp_tools",
]
