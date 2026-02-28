from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from ..core.runtime import default_manifest_path
from .service import EngineApiService

LOGGER = logging.getLogger("nepsis_cgn.api")
_RATE_LIMIT_LOCK = RLock()
_RATE_LIMIT_STATE: dict[str, list[float]] = {}


class _RequestBodyError(ValueError):
    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


def _default_store_path() -> str:
    configured = os.getenv("NEPSIS_API_STORE_PATH")
    if configured and configured.strip():
        return configured
    return str((Path.cwd() / "ledger" / "sessions" / "engine_api_sessions.db").resolve())


API = EngineApiService(store_path=_default_store_path())
ROUTES = (
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
)


class EngineApiHandler(BaseHTTPRequestHandler):
    server_version = "NepsisApi/0.2"

    def setup(self) -> None:  # noqa: D401
        super().setup()
        timeout = _request_timeout_seconds()
        if timeout > 0:
            self.connection.settimeout(timeout)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._initialize_request_context()
        origin = self.headers.get("Origin")
        if origin and not _is_origin_allowed(origin):
            self._send_json(403, {"error": "CORS origin not allowed"})
            return
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        self._initialize_request_context()
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=False)
        if not self._authorize_request("GET", path):
            return
        if path in {"/health", "/v1/health"}:
            self._send_json(200, {"ok": True})
            return
        if path == "/v1/routes":
            self._send_json(200, {"routes": route_manifest()})
            return
        if path == "/v1/openapi.json":
            self._send_json(200, openapi_spec())
            return
        if path == "/v1/sessions":
            self._safe(lambda: self._list_sessions(query))
            return

        m_session = re.fullmatch(r"/v1/sessions/([^/]+)", path)
        if m_session:
            session_id = m_session.group(1)
            self._safe(lambda: API.get_session(session_id))
            return

        m_packets = re.fullmatch(r"/v1/sessions/([^/]+)/packets", path)
        if m_packets:
            session_id = m_packets.group(1)
            self._safe(lambda: self._get_packets(session_id, query))
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        self._initialize_request_context()
        path = urlparse(self.path).path
        if not self._authorize_request("POST", path):
            return

        try:
            body = self._read_json()
        except _RequestBodyError as exc:
            self._send_json(exc.status, {"error": str(exc)})
            return

        if path == "/v1/sessions":
            self._safe(lambda: self._create_session(body))
            return

        m_step = re.fullmatch(r"/v1/sessions/([^/]+)/step", path)
        if m_step:
            session_id = m_step.group(1)
            self._safe(lambda: self._step_session(session_id, body))
            return

        m_reframe = re.fullmatch(r"/v1/sessions/([^/]+)/reframe", path)
        if m_reframe:
            session_id = m_reframe.group(1)
            self._safe(lambda: self._reframe_session(session_id, body))
            return

        self._send_json(404, {"error": "Not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        self._initialize_request_context()
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=False)
        if not self._authorize_request("DELETE", path):
            return
        if path == "/v1/sessions":
            self._safe(lambda: self._purge_sessions(query))
            return
        m_session = re.fullmatch(r"/v1/sessions/([^/]+)", path)
        if m_session:
            session_id = m_session.group(1)
            self._safe(lambda: API.delete_session(session_id))
            return
        self._send_json(404, {"error": "Not found"})

    def _create_session(self, body: dict[str, Any]) -> dict[str, Any]:
        family = body.get("family")
        if family not in {"puzzle", "clinical", "safety"}:
            raise ValueError("family must be one of: puzzle, clinical, safety")
        governance = body.get("governance")
        if governance is not None and not isinstance(governance, dict):
            raise ValueError("governance must be an object when provided")
        calibration = body.get("calibration")
        if calibration is not None and not isinstance(calibration, dict):
            raise ValueError("calibration must be an object when provided")
        manifest_path = _validated_manifest_path(body.get("manifest_path"))
        return API.create_session(
            family=family,
            manifest_path=manifest_path,
            governance_costs=governance,
            governance_calibration=calibration,
            emit_packet=bool(body.get("emit_packet", True)),
            frame=body.get("frame"),
        )

    def _step_session(self, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
        sign = body.get("sign")
        if not isinstance(sign, dict):
            raise ValueError("step payload requires object field 'sign'")
        return API.step_session(
            session_id,
            sign=sign,
            commit=bool(body.get("commit", False)),
            user_decision=body.get("user_decision"),
            override_reason=body.get("override_reason"),
            carry_forward=body.get("carry_forward"),
        )

    def _reframe_session(self, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
        frame = body.get("frame")
        if not isinstance(frame, dict):
            raise ValueError("reframe payload requires object field 'frame'")
        return API.reframe_session(session_id, frame=frame)

    def _list_sessions(self, query: dict[str, list[str]]) -> dict[str, Any]:
        limit = _query_optional_int(query, "limit", default=50)
        offset = _query_optional_int(query, "offset", default=0)
        return API.list_sessions(limit=limit, offset=offset)

    def _get_packets(self, session_id: str, query: dict[str, list[str]]) -> dict[str, Any]:
        limit = _query_optional_int(query, "limit", default=100)
        offset = _query_optional_int(query, "offset", default=0)
        return API.get_packets(session_id, limit=limit, offset=offset)

    def _purge_sessions(self, query: dict[str, list[str]]) -> dict[str, Any]:
        max_age_seconds = _query_required_float(query, "max_age_seconds")
        dry_run = _query_optional_bool(query, "dry_run", default=False)
        return API.purge_sessions(max_age_seconds=max_age_seconds, dry_run=dry_run)

    def _safe(self, op: Callable[[], dict[str, Any]]) -> None:
        try:
            payload = op()
            self._send_json(200, payload)
        except KeyError as exc:
            self._send_json(404, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception:  # pragma: no cover
            LOGGER.exception(
                "request_failed",
                extra={
                    "request_id": self._request_id,
                    "method": self.command,
                    "path": self.path,
                },
            )
            self._send_json(500, {"error": "Internal server error", "request_id": self._request_id})

    def _read_json(self) -> dict[str, Any]:
        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError as exc:
            raise _RequestBodyError("Invalid Content-Length header", status=400) from exc
        if length < 0:
            raise _RequestBodyError("Content-Length must be >= 0", status=400)

        max_bytes = _max_request_body_bytes()
        if length > max_bytes:
            raise _RequestBodyError(
                f"Request body too large (max {max_bytes} bytes)",
                status=413,
            )

        try:
            raw = self.rfile.read(length) if length > 0 else b"{}"
        except TimeoutError as exc:
            raise _RequestBodyError("Request body read timeout", status=408) from exc
        except OSError as exc:
            raise _RequestBodyError("Request body read failed", status=400) from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise _RequestBodyError("Invalid JSON body", status=400) from exc

        if not isinstance(data, dict):
            raise _RequestBodyError("JSON body must be an object", status=400)
        return data

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-ID", self._request_id)

        allowed_origin = self._allowed_origin_for_request()
        if allowed_origin is not None:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key, X-Request-ID")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")

        self.end_headers()
        self.wfile.write(body)
        if not self._response_logged:
            duration_ms = int((time.perf_counter() - self._request_started_at) * 1000)
            LOGGER.info(
                json.dumps(
                    {
                        "event": "api_response",
                        "request_id": self._request_id,
                        "method": self.command,
                        "path": urlparse(self.path).path,
                        "status": status,
                        "duration_ms": duration_ms,
                        "remote_addr": self.client_address[0] if self.client_address else None,
                    }
                )
            )
            self._response_logged = True

    def _allowed_origin_for_request(self) -> str | None:
        origin = self.headers.get("Origin")
        if not origin:
            return None
        if not _is_origin_allowed(origin):
            return None
        if "*" in _allowed_origins():
            return "*"
        return origin

    def _initialize_request_context(self) -> None:
        incoming_request_id = self.headers.get("X-Request-ID")
        if incoming_request_id and incoming_request_id.strip():
            self._request_id = incoming_request_id.strip()[:128]
        else:
            self._request_id = str(uuid4())
        self._request_started_at = time.perf_counter()
        self._response_logged = False

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
        return

    def _authorize_request(self, method: str, path: str) -> bool:
        origin = self.headers.get("Origin")
        if origin and not _is_origin_allowed(origin):
            self._send_json(403, {"error": "CORS origin not allowed"})
            return False

        if method == "OPTIONS":
            return True
        if path in {"/health", "/v1/health", "/v1/routes", "/v1/openapi.json"}:
            return True

        expected_token = _configured_api_token()
        if _auth_required() and expected_token is None:
            self._send_json(503, {"error": "Server auth misconfigured"})
            return False
        if expected_token is None:
            return self._enforce_rate_limit(path)

        token = _request_api_token(self.headers)
        if token == expected_token:
            return self._enforce_rate_limit(path)

        self._send_json(401, {"error": "Unauthorized"})
        return False

    def _enforce_rate_limit(self, path: str) -> bool:
        # Public informational routes are not rate-limited.
        if path in {"/health", "/v1/health", "/v1/routes", "/v1/openapi.json"}:
            return True
        key = _rate_limit_key(self)
        window_seconds = _rate_limit_window_seconds()
        max_requests = _rate_limit_max_requests()
        now = time.monotonic()
        cutoff = now - window_seconds

        with _RATE_LIMIT_LOCK:
            bucket = _RATE_LIMIT_STATE.get(key, [])
            bucket = [ts for ts in bucket if ts >= cutoff]
            if len(bucket) >= max_requests:
                _RATE_LIMIT_STATE[key] = bucket
                self._send_json(
                    429,
                    {
                        "error": "Rate limit exceeded",
                        "retry_after_seconds": int(max(window_seconds - (now - bucket[0]), 1)),
                    },
                )
                return False
            bucket.append(now)
            _RATE_LIMIT_STATE[key] = bucket
        return True


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    _assert_runtime_auth_configuration()
    try:
        server = ThreadingHTTPServer((host, port), EngineApiHandler)
    except PermissionError as exc:
        raise SystemExit(_bind_error_message(host, port, exc)) from exc
    except OSError as exc:
        raise SystemExit(_bind_error_message(host, port, exc)) from exc

    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.server_close()


def _bind_error_message(host: str, port: int, exc: OSError) -> str:
    suggested = _suggest_open_port(host, port)
    suggestion_text = f"1) Use a different port, e.g. --port {suggested}" if suggested is not None else "1) Use a different free port"
    return (
        f"Failed to bind Nepsis API on {host}:{port}: {exc}\n"
        "Try one of:\n"
        f"{suggestion_text}\n"
        "2) Use host 127.0.0.1 explicitly\n"
        "3) Run outside restricted sandbox/container if local bind is blocked"
    )


def _suggest_open_port(host: str, port: int, span: int = 20) -> int | None:
    candidates: list[int] = []
    for offset in range(1, span + 1):
        plus = port + offset
        minus = port - offset
        if plus <= 65535:
            candidates.append(plus)
        if minus >= 1:
            candidates.append(minus)

    for candidate in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
            except OSError:
                continue
            return candidate
    return None


def _auth_required() -> bool:
    return os.getenv("NEPSIS_API_ALLOW_ANON", "false").strip().lower() not in {"1", "true", "yes", "y", "on"}


def _assert_runtime_auth_configuration() -> None:
    if _auth_required() and _configured_api_token() is None:
        raise SystemExit(
            "NEPSIS_API_TOKEN is required when anonymous access is disabled "
            "(set NEPSIS_API_ALLOW_ANON=true only for local development)."
        )


def _configured_api_token() -> str | None:
    raw = os.getenv("NEPSIS_API_TOKEN")
    if raw is None:
        return None
    token = raw.strip()
    return token or None


def _request_api_token(headers: Any) -> str | None:
    auth = headers.get("Authorization")
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    x_api_key = headers.get("X-API-Key")
    if isinstance(x_api_key, str):
        token = x_api_key.strip()
        if token:
            return token
    return None


def _query_required_float(query: dict[str, list[str]], name: str) -> float:
    values = query.get(name)
    if not values:
        raise ValueError(f"Missing required query param: {name}")
    raw = values[0]
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid float for query param '{name}': {raw}") from exc


def _query_optional_bool(query: dict[str, list[str]], name: str, *, default: bool) -> bool:
    values = query.get(name)
    if not values:
        return default
    raw = values[0].strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean for query param '{name}': {values[0]}")


def _query_optional_int(query: dict[str, list[str]], name: str, *, default: int) -> int:
    values = query.get(name)
    if not values:
        return default
    raw = values[0]
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid integer for query param '{name}': {raw}") from exc
    return value


def _request_timeout_seconds() -> float:
    raw = os.getenv("NEPSIS_API_REQUEST_TIMEOUT_SECONDS", "15")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("NEPSIS_API_REQUEST_TIMEOUT_SECONDS must be a number") from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_REQUEST_TIMEOUT_SECONDS must be > 0")
    return value


def _max_request_body_bytes() -> int:
    raw = os.getenv("NEPSIS_API_MAX_REQUEST_BODY_BYTES", "1048576")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("NEPSIS_API_MAX_REQUEST_BODY_BYTES must be an integer") from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_MAX_REQUEST_BODY_BYTES must be > 0")
    return value


def _allowed_origins() -> set[str]:
    raw = os.getenv("NEPSIS_API_ALLOWED_ORIGINS", "")
    items = {item.strip() for item in raw.split(",") if item.strip()}
    return items


def _is_origin_allowed(origin: str) -> bool:
    allowed = _allowed_origins()
    if not allowed:
        return False
    return "*" in allowed or origin in allowed


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


def _rate_limit_key(handler: EngineApiHandler) -> str:
    token = _request_api_token(handler.headers)
    if token:
        return f"token:{token[:16]}"
    forwarded = handler.headers.get("X-Forwarded-For")
    if isinstance(forwarded, str) and forwarded.strip():
        return f"ip:{forwarded.split(',')[0].strip()}"
    client_ip = handler.client_address[0] if handler.client_address else "unknown"
    return f"ip:{client_ip}"


def route_manifest() -> list[dict[str, str]]:
    return [dict(route) for route in ROUTES]


def openapi_spec() -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for route in ROUTES:
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


def entrypoint(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=os.getenv("NEPSIS_API_LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser(prog="nepsiscgn-api", description="NepsisCGN backend API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    run(host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    entrypoint(sys.argv[1:])
