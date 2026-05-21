from __future__ import annotations

import json
import logging
import sys
from typing import Any

from ..api.service import EngineApiService
from ..core.mvp import build_nepsis_mvp_packet

LOGGER = logging.getLogger("nepsis_cgn.mcp.stdio")
PROTOCOL_VERSION = "2025-06-18"


def _tools() -> list[dict[str, Any]]:
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
            "description": "Return local NepsisCGN MCP bridge health.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "get_session_state",
            "description": "Return the ambient operator session phase, audit state, and legal next tools.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "lock_frame",
            "description": "Lock a complete operator frame and advance to report readiness.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "family": {"type": "string", "enum": ["puzzle", "clinical", "safety"]},
                    "frame": {"type": "object"},
                    "governance_costs": {"type": "object"},
                    "governance_calibration": {"type": "object"},
                    "manifest_path": {"type": "string"},
                },
                "required": ["frame"],
                "additionalProperties": False,
            },
        },
        {
            "name": "run_report",
            "description": "Atomically run CALL + REPORT + EVALUATE for the current operator frame.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "report_text": {"type": "string"},
                    "sign": {"type": "object"},
                    "interpretation": {"type": "object"},
                },
                "required": ["report_text", "sign"],
                "additionalProperties": False,
            },
        },
        {
            "name": "lock_report",
            "description": "Lock the latest passing report evaluation.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "set_threshold_decision",
            "description": "Set the operator threshold decision after a locked report.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": ["recommend", "hold"]},
                    "hold_reason": {"type": "string"},
                },
                "required": ["decision"],
                "additionalProperties": False,
            },
        },
        {
            "name": "commit_iteration",
            "description": "Emit the operator audit packet and cycle the ambient session to frame draft.",
            "inputSchema": {
                "type": "object",
                "properties": {"carry_forward_frame": {"type": "object"}},
                "additionalProperties": False,
            },
        },
        {
            "name": "abandon_session",
            "description": "Emit an abandoned-loop fragment and start a fresh ambient operator session.",
            "inputSchema": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    ]


def _handle_request(service: EngineApiService, body: dict[str, Any]) -> dict[str, Any] | None:
    request_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})
    if body.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _mcp_error(request_id, -32600, "Invalid JSON-RPC request.")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _mcp_error(request_id, -32602, "JSON-RPC params must be an object.")

    if method == "initialize":
        return _mcp_result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": "nepsis-cgn-local", "version": "0.3.0"},
                "capabilities": {"tools": {}},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _mcp_result(request_id, {"tools": _tools()})
    if method == "tools/call":
        return _call_tool(service, request_id, params)
    return _mcp_error(request_id, -32601, f"Unsupported MCP method: {method}")


def _call_tool(service: EngineApiService, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str):
        return _mcp_error(request_id, -32602, "MCP tools/call requires string field 'name'.")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return _mcp_error(request_id, -32602, "MCP tool arguments must be an object.")

    try:
        result = _tool_payload(service, name, arguments)
    except ValueError as exc:
        return _mcp_error(request_id, -32602, str(exc))
    except KeyError as exc:
        return _mcp_error(request_id, -32602, str(exc))

    return _tool_result(request_id, result, is_error=_is_phase_rejection(result))


def _tool_payload(service: EngineApiService, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "run_mvp":
        return _run_mvp(arguments)
    if name == "get_mvp_schema":
        return _mvp_schema()
    if name == "health":
        return {"ok": True, "transport": "stdio"}
    if name == "get_session_state":
        return service.get_operator_session_state()
    if name == "lock_frame":
        frame = arguments.get("frame")
        if not isinstance(frame, dict):
            raise ValueError("lock_frame requires object field 'frame'.")
        family = arguments.get("family", "safety")
        if family not in {"puzzle", "clinical", "safety"}:
            raise ValueError("family must be one of: puzzle, clinical, safety")
        governance_costs = arguments.get("governance_costs")
        if governance_costs is not None and not isinstance(governance_costs, dict):
            raise ValueError("governance_costs must be an object when provided.")
        governance_calibration = arguments.get("governance_calibration")
        if governance_calibration is not None and not isinstance(governance_calibration, dict):
            raise ValueError("governance_calibration must be an object when provided.")
        manifest_path = arguments.get("manifest_path")
        if manifest_path is not None and not isinstance(manifest_path, str):
            raise ValueError("manifest_path must be a string when provided.")
        return service.operator_lock_frame(
            family=family,
            frame=frame,
            governance_costs=governance_costs,
            governance_calibration=governance_calibration,
            manifest_path=manifest_path,
        )
    if name == "run_report":
        report_text = arguments.get("report_text")
        sign = arguments.get("sign")
        interpretation = arguments.get("interpretation")
        if not isinstance(report_text, str):
            raise ValueError("run_report requires string field 'report_text'.")
        if not isinstance(sign, dict):
            raise ValueError("run_report requires object field 'sign'.")
        if interpretation is not None and not isinstance(interpretation, dict):
            raise ValueError("interpretation must be an object when provided.")
        return service.operator_run_report(
            report_text=report_text,
            sign=sign,
            interpretation=interpretation,
        )
    if name == "lock_report":
        return service.operator_lock_report()
    if name == "set_threshold_decision":
        decision = arguments.get("decision")
        if not isinstance(decision, str):
            raise ValueError("set_threshold_decision requires string field 'decision'.")
        hold_reason = arguments.get("hold_reason", "")
        if not isinstance(hold_reason, str):
            raise ValueError("hold_reason must be a string when provided.")
        return service.operator_set_threshold_decision(decision=decision, hold_reason=hold_reason)
    if name == "commit_iteration":
        carry_forward_frame = arguments.get("carry_forward_frame")
        if carry_forward_frame is not None and not isinstance(carry_forward_frame, dict):
            raise ValueError("carry_forward_frame must be an object when provided.")
        return service.operator_commit_iteration(carry_forward_frame=carry_forward_frame)
    if name == "abandon_session":
        reason = arguments.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("reason must be a string when provided.")
        return service.operator_abandon_session(reason=reason)
    raise KeyError(f"Unknown MCP tool: {name}")


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


def _is_phase_rejection(payload: dict[str, Any]) -> bool:
    return payload.get("schema_id") == "nepsis.phase_rejection"


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


def _write_response(response: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run_stdio(service: EngineApiService | None = None) -> None:
    bridge_service = service or EngineApiService()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            body = json.loads(line)
            if not isinstance(body, dict):
                response = _mcp_error(None, -32600, "JSON-RPC message must be an object.")
            else:
                response = _handle_request(bridge_service, body)
        except Exception as exc:
            LOGGER.exception("mcp_stdio_request_failed")
            response = _mcp_error(None, -32603, str(exc))
        if response is not None:
            _write_response(response)


def entrypoint(argv: list[str] | None = None) -> None:  # pragma: no cover
    del argv
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    run_stdio()


if __name__ == "__main__":  # pragma: no cover
    entrypoint()


__all__ = ["entrypoint", "run_stdio"]
