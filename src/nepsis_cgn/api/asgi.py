import logging
import os
import json
import time
import hmac
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..core.mvp import PUBLIC_MVP_CASE_IDS, build_nepsis_mvp_packet
from ..core.runtime import default_manifest_path
from ..mcp.handler import handle_mcp_request
from ..provenance import record_packet_observation
from .private_demo import build_private_demo_runtime_packet
from .operator_packet import (
    abandon_packet,
    commit_iteration,
    inspect_operator_packet,
    lock_frame as lock_operator_packet_frame,
    lock_report as lock_operator_packet_report,
    run_report as run_operator_packet_report,
    set_threshold_decision as set_operator_packet_threshold_decision,
    start_operator_packet,
)
from .service import EngineApiService, Family

LOGGER = logging.getLogger("nepsis_cgn.api.asgi")
_RATE_LIMIT_LOCK = RLock()
_RATE_LIMIT_STATE: dict[str, list[float]] = {}
_PRIVATE_DEMO_MISCONFIGURATION_DETAIL = "Private demo runtime is not configured."
_PRIVATE_DEMO_SERVER_CONFIG_ERRORS = {
    "NEPSIS_OPERATOR_PACKET_SEAL_SECRET is required in production or operator mode",
}


def _default_store_path() -> str:
    configured = os.getenv("NEPSIS_API_STORE_PATH")
    if configured and configured.strip():
        return configured
    return str(
        (Path.cwd() / "ledger" / "sessions" / "engine_api_sessions.db").resolve()
    )


API = EngineApiService(store_path=_default_store_path())
PUBLIC_PATHS = {
    "/v1/health",
    "/v1/routes",
    "/v1/openapi.json",
    "/docs",
    "/openapi.json",
    "/mcp",
}


def _operator_family(value: Any) -> Family:
    if value not in {"puzzle", "clinical", "safety"}:
        raise ValueError("family must be one of: puzzle, clinical, safety")
    return value


def _is_private_demo_server_config_error(exc: ValueError) -> bool:
    return str(exc) in _PRIVATE_DEMO_SERVER_CONFIG_ERRORS


def _required_operator_packet(body: dict[str, Any]) -> dict[str, Any]:
    packet = body.get("packet")
    if not isinstance(packet, dict):
        raise ValueError("operator packet payload requires object field 'packet'")
    return packet


def create_app():
    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI runtime is not installed. Install optional deps: pip install 'nepsis-cgn[api]'"
        ) from exc

    app = FastAPI(title="NepsisCGN API", version="0.3.0")

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):  # noqa: ARG001
        return JSONResponse({"error": str(exc)}, status_code=400)

    @app.exception_handler(PermissionError)
    async def permission_error_handler(
        request: Request, exc: PermissionError
    ):  # noqa: ARG001
        LOGGER.info(
            "permission_denied",
            extra={"request_id": getattr(request.state, "request_id", None)},
        )
        return JSONResponse({"error": "Not found"}, status_code=404)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):  # type: ignore[override]
        started = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id

        origin = request.headers.get("origin")
        if origin and not _is_origin_allowed(origin):
            return JSONResponse(
                {"error": "CORS origin not allowed", "request_id": request_id},
                status_code=403,
            )

        if request.method != "OPTIONS" and request.url.path not in PUBLIC_PATHS:
            if not _rate_limit_allow(_rate_limit_key(request)):
                return JSONResponse(
                    {"error": "Rate limit exceeded", "request_id": request_id},
                    status_code=429,
                )
            expected = _configured_api_token()
            if _auth_required() and expected is None:
                return JSONResponse(
                    {"error": "Server auth misconfigured", "request_id": request_id},
                    status_code=503,
                )
            if expected is not None:
                token = _request_api_token(dict(request.headers))
                if not _api_token_matches(token, expected):
                    return JSONResponse(
                        {"error": "Unauthorized", "request_id": request_id},
                        status_code=401,
                    )

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if origin and _is_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = (
                origin if "*" not in _allowed_origins() else "*"
            )
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization, X-API-Key, X-Request-ID, X-Nepsis-Capability-Token"
            )
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Max-Age"] = "600"
        LOGGER.info(
            json.dumps(
                {
                    "event": "api_response",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "remote_addr": request.client.host if request.client else None,
                }
            )
        )
        return response

    @app.options("/{path:path}")
    async def options_handler(path: str):  # noqa: ARG001
        return JSONResponse({"ok": True})

    @app.get("/v1/health")
    async def health():
        return {"ok": True}

    @app.get("/v1/routes")
    async def routes():
        return {"routes": route_manifest()}

    @app.get("/v1/openapi.json")
    async def openapi_document():
        return openapi_spec()

    @app.post("/mcp")
    async def mcp_endpoint(request: Request):
        body = await _read_json_body(request)
        response = handle_mcp_request(
            body,
            headers=dict(request.headers),
            require_capability_token=True,
            server_name="nepsis-cgn",
            route_manifest_fn=route_manifest,
            request_id=getattr(request.state, "request_id", None),
        )
        if response is None:
            return JSONResponse({}, status_code=202)
        return response

    @app.post("/v1/mvp")
    async def run_mvp(request: Request):
        body = await _read_json_body(request)
        case_id = body.get("case_id", body.get("case", "jailing"))
        if case_id not in PUBLIC_MVP_CASE_IDS:
            raise HTTPException(
                status_code=400,
                detail=f"case_id must be one of: {', '.join(PUBLIC_MVP_CASE_IDS)}",
            )
        input_text = body.get("input_text", body.get("inputText"))
        if input_text is not None and not isinstance(input_text, str):
            raise HTTPException(
                status_code=400, detail="input_text must be a string when provided"
            )
        packet = build_nepsis_mvp_packet(case_id=case_id, input_text=input_text)
        record_packet_observation(
            packet=packet,
            source="backend_mvp",
            retention_mode="retained",
            request_context=_request_context(request),
        )
        return packet

    @app.post("/v1/private-demo")
    async def run_private_demo(request: Request):
        body = await _read_json_body(request)
        try:
            return build_private_demo_runtime_packet(body)
        except ValueError as exc:
            if _is_private_demo_server_config_error(exc):
                LOGGER.error(
                    "private_demo_runtime_misconfigured",
                    extra={"request_id": getattr(request.state, "request_id", None)},
                )
                raise HTTPException(
                    status_code=503, detail=_PRIVATE_DEMO_MISCONFIGURATION_DETAIL
                ) from exc
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator-packet/start")
    async def start_operator_packet_route(request: Request):
        body = await _read_json_body(request)
        try:
            family = _operator_family(body.get("family", "safety"))
            frame = body.get("frame")
            if frame is not None and not isinstance(frame, dict):
                raise ValueError("frame must be an object when provided")
            governance = body.get("governance_costs", body.get("governance"))
            if governance is not None and not isinstance(governance, dict):
                raise ValueError("governance must be an object when provided")
            calibration = body.get("governance_calibration", body.get("calibration"))
            if calibration is not None and not isinstance(calibration, dict):
                raise ValueError("calibration must be an object when provided")
            return _record_stateless_packet_result(
                start_operator_packet(
                    family=family,
                    frame=frame,
                    governance_costs=governance,
                    governance_calibration=calibration,
                    manifest_path=_validated_manifest_path(body.get("manifest_path")),
                ),
                request,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator-packet/state")
    async def inspect_operator_packet_route(request: Request):
        body = await _read_json_body(request)
        packet = body.get("packet")
        if packet is not None and not isinstance(packet, dict):
            raise HTTPException(
                status_code=400,
                detail="operator packet payload requires object field 'packet' when provided",
            )
        try:
            return _record_stateless_packet_result(
                inspect_operator_packet(packet), request
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator-packet/frame")
    async def lock_operator_packet_frame_route(request: Request):
        body = await _read_json_body(request)
        try:
            packet = _required_operator_packet(body)
            frame = body.get("frame")
            if not isinstance(frame, dict):
                raise ValueError(
                    "operator packet frame payload requires object field 'frame'"
                )
            family = body.get("family")
            governance = body.get("governance_costs", body.get("governance"))
            if governance is not None and not isinstance(governance, dict):
                raise ValueError("governance must be an object when provided")
            calibration = body.get("governance_calibration", body.get("calibration"))
            if calibration is not None and not isinstance(calibration, dict):
                raise ValueError("calibration must be an object when provided")
            return _phase_json_response(
                _record_stateless_packet_result(
                    lock_operator_packet_frame(
                        packet=packet,
                        frame=frame,
                        family=_operator_family(family) if family is not None else None,
                        governance_costs=governance,
                        governance_calibration=calibration,
                        manifest_path=_validated_manifest_path(
                            body.get("manifest_path")
                        ),
                        assist_acceptances=body.get("assist_acceptances"),
                    ),
                    request,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator-packet/report")
    async def run_operator_packet_report_route(request: Request):
        body = await _read_json_body(request)
        try:
            packet = _required_operator_packet(body)
            report_text = body.get("report_text", body.get("reportText"))
            sign = body.get("sign")
            interpretation = body.get("interpretation")
            if not isinstance(report_text, str):
                raise ValueError(
                    "operator packet report payload requires string field 'report_text'"
                )
            if not isinstance(sign, dict):
                raise ValueError(
                    "operator packet report payload requires object field 'sign'"
                )
            if interpretation is not None and not isinstance(interpretation, dict):
                raise ValueError("interpretation must be an object when provided")
            return _phase_json_response(
                _record_stateless_packet_result(
                    run_operator_packet_report(
                        packet=packet,
                        report_text=report_text,
                        sign=sign,
                        interpretation=interpretation,
                    ),
                    request,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator-packet/report/lock")
    async def lock_operator_packet_report_route(request: Request):
        body = await _read_json_body(request)
        try:
            return _phase_json_response(
                _record_stateless_packet_result(
                    lock_operator_packet_report(packet=_required_operator_packet(body)),
                    request,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator-packet/threshold")
    async def set_operator_packet_threshold_decision_route(request: Request):
        body = await _read_json_body(request)
        try:
            decision = body.get("decision")
            hold_reason = body.get("hold_reason", body.get("holdReason", ""))
            if not isinstance(decision, str):
                raise ValueError(
                    "operator packet threshold payload requires string field 'decision'"
                )
            if not isinstance(hold_reason, str):
                raise ValueError("hold_reason must be a string when provided")
            return _phase_json_response(
                _record_stateless_packet_result(
                    set_operator_packet_threshold_decision(
                        packet=_required_operator_packet(body),
                        decision=decision,
                        hold_reason=hold_reason,
                        assist_acceptances=body.get("assist_acceptances"),
                    ),
                    request,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator-packet/commit")
    async def commit_operator_packet_iteration_route(request: Request):
        body = await _read_json_body(request)
        try:
            carry_forward_frame = body.get(
                "carry_forward_frame", body.get("carryForwardFrame")
            )
            if carry_forward_frame is not None and not isinstance(
                carry_forward_frame, dict
            ):
                raise ValueError("carry_forward_frame must be an object when provided")
            return _phase_json_response(
                _record_stateless_packet_result(
                    commit_iteration(
                        packet=_required_operator_packet(body),
                        carry_forward_frame=carry_forward_frame,
                        assist_acceptances=body.get("assist_acceptances"),
                    ),
                    request,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator-packet/abandon")
    async def abandon_operator_packet_route(request: Request):
        body = await _read_json_body(request)
        try:
            reason = body.get("reason", "")
            if not isinstance(reason, str):
                raise ValueError("reason must be a string when provided")
            return _record_stateless_packet_result(
                abandon_packet(packet=_required_operator_packet(body), reason=reason),
                request,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/operator/session")
    async def get_operator_session_state():
        return API.get_operator_session_state()

    @app.post("/v1/operator/frame")
    async def lock_operator_frame(request: Request):
        body = await _read_json_body(request)
        frame = body.get("frame")
        if not isinstance(frame, dict):
            raise HTTPException(
                status_code=400,
                detail="operator frame payload requires object field 'frame'",
            )
        family = body.get("family", "safety")
        if family not in {"puzzle", "clinical", "safety"}:
            raise HTTPException(
                status_code=400,
                detail="family must be one of: puzzle, clinical, safety",
            )
        governance = body.get("governance_costs", body.get("governance"))
        if governance is not None and not isinstance(governance, dict):
            raise HTTPException(
                status_code=400, detail="governance must be an object when provided"
            )
        calibration = body.get("governance_calibration", body.get("calibration"))
        if calibration is not None and not isinstance(calibration, dict):
            raise HTTPException(
                status_code=400, detail="calibration must be an object when provided"
            )
        manifest_path = _validated_manifest_path(body.get("manifest_path"))
        try:
            return _phase_json_response(
                API.operator_lock_frame(
                    family=family,
                    frame=frame,
                    governance_costs=governance,
                    governance_calibration=calibration,
                    manifest_path=manifest_path,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator/report")
    async def run_operator_report(request: Request):
        body = await _read_json_body(request)
        report_text = body.get("report_text", body.get("reportText"))
        sign = body.get("sign")
        interpretation = body.get("interpretation")
        if not isinstance(report_text, str):
            raise HTTPException(
                status_code=400,
                detail="operator report payload requires string field 'report_text'",
            )
        if not isinstance(sign, dict):
            raise HTTPException(
                status_code=400,
                detail="operator report payload requires object field 'sign'",
            )
        if interpretation is not None and not isinstance(interpretation, dict):
            raise HTTPException(
                status_code=400, detail="interpretation must be an object when provided"
            )
        try:
            return _phase_json_response(
                API.operator_run_report(
                    report_text=report_text,
                    sign=sign,
                    interpretation=interpretation,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator/report/lock")
    async def lock_operator_report():
        return _phase_json_response(API.operator_lock_report())

    @app.post("/v1/operator/threshold")
    async def set_operator_threshold_decision(request: Request):
        body = await _read_json_body(request)
        decision = body.get("decision")
        hold_reason = body.get("hold_reason", body.get("holdReason", ""))
        if not isinstance(decision, str):
            raise HTTPException(
                status_code=400,
                detail="threshold payload requires string field 'decision'",
            )
        if not isinstance(hold_reason, str):
            raise HTTPException(
                status_code=400, detail="hold_reason must be a string when provided"
            )
        try:
            return _phase_json_response(
                API.operator_set_threshold_decision(
                    decision=decision, hold_reason=hold_reason
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator/commit")
    async def commit_operator_iteration(request: Request):
        body = await _read_json_body(request)
        carry_forward_frame = body.get(
            "carry_forward_frame", body.get("carryForwardFrame")
        )
        if carry_forward_frame is not None and not isinstance(
            carry_forward_frame, dict
        ):
            raise HTTPException(
                status_code=400,
                detail="carry_forward_frame must be an object when provided",
            )
        try:
            return _phase_json_response(
                API.operator_commit_iteration(
                    carry_forward_frame=carry_forward_frame,
                    request_context=_request_context(request),
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/operator/abandon")
    async def abandon_operator_session(request: Request):
        body = await _read_json_body(request)
        reason = body.get("reason", "")
        if not isinstance(reason, str):
            raise HTTPException(
                status_code=400, detail="reason must be a string when provided"
            )
        return API.operator_abandon_session(
            reason=reason, request_context=_request_context(request)
        )

    @app.get("/v1/sessions")
    async def list_sessions(request: Request, limit: int = 50, offset: int = 0):
        return API.list_sessions(
            limit=limit,
            offset=offset,
            owner_id=_request_owner_id(dict(request.headers)),
        )

    @app.post("/v1/sessions")
    async def create_session(request: Request):
        body = await _read_json_body(request)
        family = body.get("family")
        if family not in {"puzzle", "clinical", "safety"}:
            raise HTTPException(
                status_code=400,
                detail="family must be one of: puzzle, clinical, safety",
            )
        governance = body.get("governance")
        if governance is not None and not isinstance(governance, dict):
            raise HTTPException(
                status_code=400, detail="governance must be an object when provided"
            )
        calibration = body.get("calibration")
        if calibration is not None and not isinstance(calibration, dict):
            raise HTTPException(
                status_code=400, detail="calibration must be an object when provided"
            )
        manifest_path = _validated_manifest_path(body.get("manifest_path"))
        return API.create_session(
            family=family,
            manifest_path=manifest_path,
            governance_costs=governance,
            governance_calibration=calibration,
            emit_packet=bool(body.get("emit_packet", True)),
            frame=body.get("frame"),
            owner_id=_request_owner_id(dict(request.headers)),
        )

    @app.get("/v1/sessions/{session_id}")
    async def get_session(session_id: str, request: Request):
        try:
            return API.get_session(
                session_id, owner_id=_request_owner_id(dict(request.headers))
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc

    @app.delete("/v1/sessions/{session_id}")
    async def delete_session(session_id: str, request: Request):
        try:
            return API.delete_session(
                session_id, owner_id=_request_owner_id(dict(request.headers))
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc

    @app.post("/v1/sessions/{session_id}/step")
    async def step_session(session_id: str, request: Request):
        body = await _read_json_body(request)
        sign = body.get("sign")
        if not isinstance(sign, dict):
            raise HTTPException(
                status_code=400, detail="step payload requires object field 'sign'"
            )
        try:
            return API.step_session(
                session_id,
                sign=sign,
                commit=bool(body.get("commit", False)),
                user_decision=body.get("user_decision"),
                override_reason=body.get("override_reason"),
                carry_forward=body.get("carry_forward"),
                owner_id=_request_owner_id(dict(request.headers)),
                request_context=_request_context(request),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/sessions/{session_id}/reframe")
    async def reframe_session(session_id: str, request: Request):
        body = await _read_json_body(request)
        frame = body.get("frame")
        if not isinstance(frame, dict):
            raise HTTPException(
                status_code=400, detail="reframe payload requires object field 'frame'"
            )
        branch_id = body.get("branch_id")
        if branch_id is not None and (
            not isinstance(branch_id, str) or not branch_id.strip()
        ):
            raise HTTPException(
                status_code=400,
                detail="branch_id must be a non-empty string when provided",
            )
        parent_frame_id = body.get("parent_frame_id")
        if parent_frame_id is not None and not isinstance(parent_frame_id, str):
            raise HTTPException(
                status_code=400, detail="parent_frame_id must be a string when provided"
            )
        try:
            return API.reframe_session(
                session_id,
                frame=frame,
                branch_id=branch_id.strip() if isinstance(branch_id, str) else None,
                parent_frame_id=(
                    parent_frame_id.strip()
                    if isinstance(parent_frame_id, str)
                    else None
                ),
                owner_id=_request_owner_id(dict(request.headers)),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/sessions/{session_id}/workspace")
    async def update_workspace_state(session_id: str, request: Request):
        body = await _read_json_body(request)
        workspace_state = body.get("workspace_state", body.get("state", body))
        if not isinstance(workspace_state, dict):
            raise HTTPException(
                status_code=400, detail="workspace_state must be an object"
            )
        try:
            return API.update_workspace_state(
                session_id,
                workspace_state=workspace_state,
                owner_id=_request_owner_id(dict(request.headers)),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/sessions/{session_id}/stage-audit")
    async def stage_audit_session(session_id: str, request: Request):
        try:
            return API.stage_audit_session(
                session_id,
                owner_id=_request_owner_id(dict(request.headers)),
                request_context=_request_context(request),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/sessions/{session_id}/stage-audit")
    async def stage_audit_session_with_context(session_id: str, request: Request):
        body = await _read_json_body(request)
        raw_context = body.get("context", body)
        if raw_context is None:
            context = None
        else:
            if not isinstance(raw_context, dict):
                raise HTTPException(
                    status_code=400,
                    detail="stage-audit payload 'context' must be an object when provided",
                )
            context = raw_context
        try:
            return API.stage_audit_session(
                session_id,
                context=context,
                persist_context=bool(body.get("persist_context", False)),
                owner_id=_request_owner_id(dict(request.headers)),
                request_context=_request_context(request),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/sessions/{session_id}/packets")
    async def packets(
        session_id: str, request: Request, limit: int = 100, offset: int = 0
    ):
        try:
            return API.get_packets(
                session_id,
                limit=limit,
                offset=offset,
                owner_id=_request_owner_id(dict(request.headers)),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc

    @app.get("/v1/sessions/{session_id}/provenance")
    async def packet_provenance(session_id: str, request: Request):
        try:
            return API.get_packet_provenance(
                session_id,
                owner_id=_request_owner_id(dict(request.headers)),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc

    @app.get("/v1/sessions/{session_id}/audit-export")
    async def audit_export(session_id: str, request: Request):
        try:
            return API.export_session_audit(
                session_id,
                owner_id=_request_owner_id(dict(request.headers)),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc

    @app.get("/v1/provenance/requests/{request_id}")
    async def request_provenance(request_id: str, request: Request):
        try:
            return API.get_request_provenance(
                request_id,
                owner_id=_request_owner_id(dict(request.headers)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=404, detail="Not found") from exc

    @app.get("/v1/provenance/packets/{packet_id}/lineage")
    async def packet_lineage(packet_id: str, request: Request):
        try:
            return API.get_packet_lineage(
                packet_id,
                owner_id=_request_owner_id(dict(request.headers)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.delete("/v1/sessions")
    async def purge_sessions(
        request: Request, max_age_seconds: float, dry_run: bool = False
    ):
        try:
            return API.purge_sessions(
                max_age_seconds=max_age_seconds,
                dry_run=dry_run,
                owner_id=_request_owner_id(dict(request.headers)),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def _auth_required() -> bool:
    return os.getenv("NEPSIS_API_ALLOW_ANON", "false").strip().lower() not in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _configured_api_token() -> str | None:
    raw = os.getenv("NEPSIS_API_TOKEN")
    if raw is None:
        return None
    token = raw.strip()
    return token or None


def _request_api_token(headers: dict[str, Any]) -> str | None:
    auth = headers.get("authorization") or headers.get("Authorization")
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    x_api_key = headers.get("x-api-key") or headers.get("X-API-Key")
    if isinstance(x_api_key, str):
        token = x_api_key.strip()
        if token:
            return token
    return None


def _api_token_matches(token: str | None, expected: str) -> bool:
    if token is None:
        return False
    return hmac.compare_digest(token, expected)


def _request_owner_id(headers: dict[str, Any]) -> str | None:
    owner_id = headers.get("x-nepsis-session-owner") or headers.get(
        "X-Nepsis-Session-Owner"
    )
    if not isinstance(owner_id, str):
        return None
    normalized = owner_id.strip().lower()
    if not normalized:
        return None
    if len(normalized) > 256:
        raise ValueError("X-Nepsis-Session-Owner must be 256 characters or fewer.")
    return normalized


def _allowed_origins() -> set[str]:
    raw = os.getenv("NEPSIS_API_ALLOWED_ORIGINS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _is_origin_allowed(origin: str) -> bool:
    allowed = _allowed_origins()
    if not allowed:
        return False
    if "*" in allowed and _wildcard_cors_forbidden():
        return False
    return "*" in allowed or origin in allowed


def _wildcard_cors_forbidden() -> bool:
    return (
        os.getenv("NODE_ENV", "").strip().lower() == "production"
        or os.getenv("NEPSIS_DEPLOYMENT_MODE", "").strip().lower() == "operator"
        or os.getenv("NEXT_PUBLIC_NEPSIS_OPERATOR_SITE", "").strip().lower()
        in {"1", "true", "yes", "y", "on"}
    )


def _max_request_body_bytes() -> int:
    raw = os.getenv("NEPSIS_API_MAX_REQUEST_BODY_BYTES", "1048576")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            "NEPSIS_API_MAX_REQUEST_BODY_BYTES must be an integer"
        ) from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_MAX_REQUEST_BODY_BYTES must be > 0")
    return value


async def _read_json_body(request):
    from fastapi import HTTPException

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            length = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Invalid Content-Length header"
            ) from exc
        if length > _max_request_body_bytes():
            raise HTTPException(status_code=413, detail="Request body too large")

    raw = await request.body()
    if len(raw) > _max_request_body_bytes():
        raise HTTPException(status_code=413, detail="Request body too large")

    if not raw:
        return {}

    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    return payload


def _phase_json_response(payload: dict[str, Any]):
    from fastapi.responses import JSONResponse

    status_code = 409 if payload.get("schema_id") == "nepsis.phase_rejection" else 200
    return JSONResponse(payload, status_code=status_code)


def _record_stateless_packet_result(
    payload: dict[str, Any], request: Any
) -> dict[str, Any]:
    if payload.get("schema_id") in {
        "nepsis.operator_packet",
        "nepsis.operator_packet_state",
        "nepsis.phase_rejection",
    }:
        record_packet_observation(
            packet=payload,
            source="stateless_operator_packet",
            retention_mode="hash_only",
            request_context=_request_context(request),
        )
    return payload


def _request_context(request: Any) -> dict[str, Any]:
    return {
        "request_id": getattr(request.state, "request_id", None),
        "method": request.method,
        "path": request.url.path,
    }


def _validated_manifest_path(manifest_path: Any) -> str | None:
    if manifest_path is None:
        return None
    if not isinstance(manifest_path, str) or not manifest_path.strip():
        raise ValueError("manifest_path must be a non-empty string when provided")
    resolved = Path(manifest_path).expanduser().resolve()
    for root in _allowed_manifest_roots():
        if _is_path_within(resolved, root):
            return str(resolved)
    allowed = ", ".join(
        str(root) for root in sorted(_allowed_manifest_roots(), key=str)
    )
    raise ValueError(f"manifest_path is not allowed. Allowed roots: {allowed}")


def _allowed_manifest_roots() -> set[Path]:
    roots = {default_manifest_path().resolve().parent}
    raw = os.getenv("NEPSIS_API_ALLOWED_MANIFEST_ROOTS", "")
    for item in raw.split(","):
        value = item.strip()
        if value:
            roots.add(Path(value).expanduser().resolve())
    return roots


def _is_path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _rate_limit_window_seconds() -> float:
    raw = os.getenv("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS", "60")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            "NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS must be a number"
        ) from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS must be > 0")
    return value


def _rate_limit_max_requests() -> int:
    raw = os.getenv("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS", "120")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            "NEPSIS_API_RATE_LIMIT_MAX_REQUESTS must be an integer"
        ) from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS must be > 0")
    return value


def _rate_limit_key(request: Any) -> str:
    forwarded = _trusted_forwarded_ip(request.headers)
    if forwarded:
        return f"ip:{forwarded}"
    client_ip = request.client.host if getattr(request, "client", None) else "unknown"
    return f"ip:{client_ip}"


def _trusted_forwarded_ip(headers: Any) -> str | None:
    if os.getenv("NEPSIS_API_TRUST_FORWARDED_FOR", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }:
        return None
    real_ip = headers.get("x-real-ip") or headers.get("X-Real-IP")
    if isinstance(real_ip, str) and real_ip.strip():
        return real_ip.strip()
    forwarded = headers.get("x-forwarded-for") or headers.get("X-Forwarded-For")
    if isinstance(forwarded, str) and forwarded.strip():
        return forwarded.split(",")[0].strip()
    return None


def _rate_limit_allow(key: str) -> bool:
    now = time.monotonic()
    cutoff = now - _rate_limit_window_seconds()
    max_requests = _rate_limit_max_requests()
    with _RATE_LIMIT_LOCK:
        bucket = _RATE_LIMIT_STATE.get(key, [])
        bucket = [ts for ts in bucket if ts >= cutoff]
        if len(bucket) >= max_requests:
            _RATE_LIMIT_STATE[key] = bucket
            return False
        bucket.append(now)
        _RATE_LIMIT_STATE[key] = bucket
    return True


def route_manifest() -> list[dict[str, str]]:
    return [
        {
            "method": "POST",
            "path": "/mcp",
            "description": "Model Context Protocol JSON-RPC tool endpoint",
        },
        {"method": "GET", "path": "/v1/health", "description": "Health check"},
        {"method": "GET", "path": "/v1/routes", "description": "API route manifest"},
        {
            "method": "GET",
            "path": "/v1/openapi.json",
            "description": "OpenAPI specification",
        },
        {
            "method": "POST",
            "path": "/v1/mvp",
            "description": "Run canonical MVP packet demo",
        },
        {
            "method": "POST",
            "path": "/v1/private-demo",
            "description": "Run no-PHI private demo runtime packet",
        },
        {
            "method": "POST",
            "path": "/v1/operator-packet/start",
            "description": "Start stateless operator packet",
        },
        {
            "method": "POST",
            "path": "/v1/operator-packet/state",
            "description": "Inspect stateless operator packet state",
        },
        {
            "method": "POST",
            "path": "/v1/operator-packet/frame",
            "description": "Lock frame into stateless operator packet",
        },
        {
            "method": "POST",
            "path": "/v1/operator-packet/report",
            "description": "Run report through stateless operator packet",
        },
        {
            "method": "POST",
            "path": "/v1/operator-packet/report/lock",
            "description": "Lock stateless operator packet report",
        },
        {
            "method": "POST",
            "path": "/v1/operator-packet/threshold",
            "description": "Set stateless operator packet threshold decision",
        },
        {
            "method": "POST",
            "path": "/v1/operator-packet/commit",
            "description": "Commit stateless operator packet iteration",
        },
        {
            "method": "POST",
            "path": "/v1/operator-packet/abandon",
            "description": "Abandon stateless operator packet loop",
        },
        {
            "method": "GET",
            "path": "/v1/operator/session",
            "description": "Get ambient operator session phase state",
        },
        {
            "method": "POST",
            "path": "/v1/operator/frame",
            "description": "Lock ambient operator frame",
        },
        {
            "method": "POST",
            "path": "/v1/operator/report",
            "description": "Run ambient operator report",
        },
        {
            "method": "POST",
            "path": "/v1/operator/report/lock",
            "description": "Lock ambient operator report",
        },
        {
            "method": "POST",
            "path": "/v1/operator/threshold",
            "description": "Set ambient operator threshold decision",
        },
        {
            "method": "POST",
            "path": "/v1/operator/commit",
            "description": "Commit ambient operator iteration audit",
        },
        {
            "method": "POST",
            "path": "/v1/operator/abandon",
            "description": "Abandon ambient operator session",
        },
        {
            "method": "POST",
            "path": "/v1/sessions",
            "description": "Create engine session",
        },
        {"method": "GET", "path": "/v1/sessions", "description": "List sessions"},
        {
            "method": "DELETE",
            "path": "/v1/sessions",
            "description": "Purge old sessions by TTL",
        },
        {
            "method": "GET",
            "path": "/v1/sessions/{session_id}",
            "description": "Get session summary",
        },
        {
            "method": "DELETE",
            "path": "/v1/sessions/{session_id}",
            "description": "Delete session",
        },
        {
            "method": "POST",
            "path": "/v1/sessions/{session_id}/step",
            "description": "Run one step",
        },
        {
            "method": "POST",
            "path": "/v1/sessions/{session_id}/reframe",
            "description": "Update frame version",
        },
        {
            "method": "POST",
            "path": "/v1/sessions/{session_id}/workspace",
            "description": "Persist UI workspace state",
        },
        {
            "method": "GET",
            "path": "/v1/sessions/{session_id}/stage-audit",
            "description": "Audit stage gate readiness",
        },
        {
            "method": "POST",
            "path": "/v1/sessions/{session_id}/stage-audit",
            "description": "Audit stage gate readiness with context",
        },
        {
            "method": "GET",
            "path": "/v1/sessions/{session_id}/packets",
            "description": "Get replay packets",
        },
        {
            "method": "GET",
            "path": "/v1/sessions/{session_id}/provenance",
            "description": "Get packet provenance graph",
        },
        {
            "method": "GET",
            "path": "/v1/sessions/{session_id}/audit-export",
            "description": "Export session audit trail",
        },
        {
            "method": "GET",
            "path": "/v1/provenance/requests/{request_id}",
            "description": "Reconstruct packet flow by request",
        },
        {
            "method": "GET",
            "path": "/v1/provenance/packets/{packet_id}/lineage",
            "description": "Get packet lineage graph",
        },
    ]


def openapi_spec() -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for route in route_manifest():
        path = route["path"]
        method = route["method"].lower()
        operation_id = f"{method}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '') or 'root'}"
        paths.setdefault(path, {})
        paths[path][method] = {
            "operationId": operation_id,
            "summary": route["description"],
            "responses": {
                "200": {"description": "Success"},
                "400": {"description": "Bad Request"},
                "401": {"description": "Unauthorized"},
                "404": {"description": "Not Found"},
                "429": {"description": "Rate Limit Exceeded"},
                "500": {"description": "Internal Server Error"},
            },
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "NepsisCGN Engine API",
            "version": "0.3.0",
            "description": "Engine control API for NepsisCGN session lifecycle and governance.",
        },
        "paths": paths,
    }


def entrypoint(argv: list[str] | None = None) -> None:  # pragma: no cover
    del argv
    if _auth_required() and _configured_api_token() is None:
        raise SystemExit(
            "NEPSIS_API_TOKEN is required when anonymous access is disabled "
            "(set NEPSIS_API_ALLOW_ANON=true only for local development)."
        )
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit(
            "uvicorn is required. Install optional deps: pip install 'nepsis-cgn[api]'"
        ) from exc

    logging.basicConfig(level=os.getenv("NEPSIS_API_LOG_LEVEL", "INFO"))
    host = os.getenv("NEPSIS_API_HOST", "127.0.0.1")
    port = int(os.getenv("NEPSIS_API_PORT", "8787"))
    uvicorn.run("nepsis_cgn.api.asgi:create_app", host=host, port=port, factory=True)


__all__ = [
    "create_app",
    "entrypoint",
]
