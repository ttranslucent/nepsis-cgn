from __future__ import annotations

import logging
import os
import json
import time
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..core.runtime import default_manifest_path
from .service import EngineApiService

LOGGER = logging.getLogger("nepsis_cgn.api.asgi")
_RATE_LIMIT_LOCK = RLock()
_RATE_LIMIT_STATE: dict[str, list[float]] = {}


def _default_store_path() -> str:
    configured = os.getenv("NEPSIS_API_STORE_PATH")
    if configured and configured.strip():
        return configured
    return str((Path.cwd() / "ledger" / "sessions" / "engine_api_sessions.db").resolve())


API = EngineApiService(store_path=_default_store_path())
PUBLIC_PATHS = {"/v1/health", "/v1/routes", "/v1/openapi.json", "/docs", "/openapi.json"}


def create_app():
    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import JSONResponse
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI runtime is not installed. Install optional deps: pip install 'nepsis-cgn[api]'"
        ) from exc

    app = FastAPI(title="NepsisCGN API", version="0.2.0")

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):  # type: ignore[override]
        started = time.perf_counter()
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id

        origin = request.headers.get("origin")
        if origin and not _is_origin_allowed(origin):
            return JSONResponse({"error": "CORS origin not allowed", "request_id": request_id}, status_code=403)

        if request.method != "OPTIONS" and request.url.path not in PUBLIC_PATHS:
            expected = _configured_api_token()
            if _auth_required() and expected is None:
                return JSONResponse({"error": "Server auth misconfigured", "request_id": request_id}, status_code=503)
            if expected is not None:
                token = _request_api_token(dict(request.headers))
                if token != expected:
                    return JSONResponse({"error": "Unauthorized", "request_id": request_id}, status_code=401)
            if not _rate_limit_allow(_rate_limit_key(request)):
                return JSONResponse({"error": "Rate limit exceeded", "request_id": request_id}, status_code=429)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if origin and _is_origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin if "*" not in _allowed_origins() else "*"
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-API-Key, X-Request-ID"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
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

    @app.get("/v1/sessions")
    async def list_sessions(limit: int = 50, offset: int = 0):
        return API.list_sessions(limit=limit, offset=offset)

    @app.post("/v1/sessions")
    async def create_session(request: Request):
        body = await _read_json_body(request)
        family = body.get("family")
        if family not in {"puzzle", "clinical", "safety"}:
            raise HTTPException(status_code=400, detail="family must be one of: puzzle, clinical, safety")
        governance = body.get("governance")
        if governance is not None and not isinstance(governance, dict):
            raise HTTPException(status_code=400, detail="governance must be an object when provided")
        calibration = body.get("calibration")
        if calibration is not None and not isinstance(calibration, dict):
            raise HTTPException(status_code=400, detail="calibration must be an object when provided")
        manifest_path = _validated_manifest_path(body.get("manifest_path"))
        return API.create_session(
            family=family,
            manifest_path=manifest_path,
            governance_costs=governance,
            governance_calibration=calibration,
            emit_packet=bool(body.get("emit_packet", True)),
            frame=body.get("frame"),
        )

    @app.get("/v1/sessions/{session_id}")
    async def get_session(session_id: str):
        try:
            return API.get_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/v1/sessions/{session_id}")
    async def delete_session(session_id: str):
        try:
            return API.delete_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/sessions/{session_id}/step")
    async def step_session(session_id: str, request: Request):
        body = await _read_json_body(request)
        sign = body.get("sign")
        if not isinstance(sign, dict):
            raise HTTPException(status_code=400, detail="step payload requires object field 'sign'")
        try:
            return API.step_session(
                session_id,
                sign=sign,
                commit=bool(body.get("commit", False)),
                user_decision=body.get("user_decision"),
                override_reason=body.get("override_reason"),
                carry_forward=body.get("carry_forward"),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/sessions/{session_id}/reframe")
    async def reframe_session(session_id: str, request: Request):
        body = await _read_json_body(request)
        frame = body.get("frame")
        if not isinstance(frame, dict):
            raise HTTPException(status_code=400, detail="reframe payload requires object field 'frame'")
        try:
            return API.reframe_session(session_id, frame=frame)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/sessions/{session_id}/packets")
    async def packets(session_id: str, limit: int = 100, offset: int = 0):
        try:
            return API.get_packets(session_id, limit=limit, offset=offset)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.delete("/v1/sessions")
    async def purge_sessions(max_age_seconds: float, dry_run: bool = False):
        try:
            return API.purge_sessions(max_age_seconds=max_age_seconds, dry_run=dry_run)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app


def _auth_required() -> bool:
    return os.getenv("NEPSIS_API_ALLOW_ANON", "false").strip().lower() not in {"1", "true", "yes", "y", "on"}


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


def _allowed_origins() -> set[str]:
    raw = os.getenv("NEPSIS_API_ALLOWED_ORIGINS", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _is_origin_allowed(origin: str) -> bool:
    allowed = _allowed_origins()
    if not allowed:
        return False
    return "*" in allowed or origin in allowed


def _max_request_body_bytes() -> int:
    raw = os.getenv("NEPSIS_API_MAX_REQUEST_BODY_BYTES", "1048576")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("NEPSIS_API_MAX_REQUEST_BODY_BYTES must be an integer") from exc
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
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc
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


def _validated_manifest_path(manifest_path: Any) -> str | None:
    if manifest_path is None:
        return None
    if not isinstance(manifest_path, str) or not manifest_path.strip():
        raise ValueError("manifest_path must be a non-empty string when provided")
    resolved = Path(manifest_path).expanduser().resolve()
    for root in _allowed_manifest_roots():
        if _is_path_within(resolved, root):
            return str(resolved)
    allowed = ", ".join(str(root) for root in sorted(_allowed_manifest_roots(), key=str))
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
        raise ValueError("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS must be a number") from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS must be > 0")
    return value


def _rate_limit_max_requests() -> int:
    raw = os.getenv("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS", "120")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS must be an integer") from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS must be > 0")
    return value


def _rate_limit_key(request: Any) -> str:
    token = _request_api_token(dict(request.headers))
    if token:
        return f"token:{token[:16]}"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    client_ip = request.client.host if getattr(request, "client", None) else "unknown"
    return f"ip:{client_ip}"


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
        {"method": "GET", "path": "/v1/health", "description": "Health check"},
        {"method": "GET", "path": "/v1/routes", "description": "API route manifest"},
        {"method": "GET", "path": "/v1/openapi.json", "description": "OpenAPI specification"},
        {"method": "POST", "path": "/v1/sessions", "description": "Create engine session"},
        {"method": "GET", "path": "/v1/sessions", "description": "List sessions"},
        {"method": "DELETE", "path": "/v1/sessions", "description": "Purge old sessions by TTL"},
        {"method": "GET", "path": "/v1/sessions/{session_id}", "description": "Get session summary"},
        {"method": "DELETE", "path": "/v1/sessions/{session_id}", "description": "Delete session"},
        {"method": "POST", "path": "/v1/sessions/{session_id}/step", "description": "Run one step"},
        {"method": "POST", "path": "/v1/sessions/{session_id}/reframe", "description": "Update frame version"},
        {"method": "GET", "path": "/v1/sessions/{session_id}/packets", "description": "Get replay packets"},
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
            "version": "0.2.0",
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
        raise SystemExit("uvicorn is required. Install optional deps: pip install 'nepsis-cgn[api]'") from exc

    logging.basicConfig(level=os.getenv("NEPSIS_API_LOG_LEVEL", "INFO"))
    host = os.getenv("NEPSIS_API_HOST", "127.0.0.1")
    port = int(os.getenv("NEPSIS_API_PORT", "8787"))
    uvicorn.run("nepsis_cgn.api.asgi:create_app", host=host, port=port, factory=True)


__all__ = [
    "create_app",
    "entrypoint",
]
