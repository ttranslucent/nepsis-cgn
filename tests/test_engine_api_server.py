from __future__ import annotations

import http.client
import json
import threading

import pytest

import nepsis_cgn.api.server as api_server
from nepsis_cgn.api.service import EngineApiService
from nepsis_cgn.api.server import (
    _assert_runtime_auth_configuration,
    _auth_required,
    _bind_error_message,
    _configured_api_token,
    _is_origin_allowed,
    _max_request_body_bytes,
    openapi_spec,
    _query_optional_bool,
    _query_optional_int,
    _query_required_float,
    _rate_limit_max_requests,
    _rate_limit_window_seconds,
    _request_timeout_seconds,
    _request_api_token,
    _validated_manifest_path,
    route_manifest,
)


def test_bind_error_message_contains_actionable_steps() -> None:
    msg = _bind_error_message("127.0.0.1", 8787, PermissionError("Operation not permitted"))
    assert "127.0.0.1:8787" in msg
    assert "Use a different" in msg
    assert "Run outside restricted sandbox" in msg


def test_route_manifest_contains_routes_endpoint() -> None:
    routes = route_manifest()
    assert any(r["path"] == "/v1/routes" and r["method"] == "GET" for r in routes)
    assert any(r["path"] == "/v1/openapi.json" and r["method"] == "GET" for r in routes)
    assert any(r["path"] == "/v1/sessions/{session_id}/step" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/sessions/{session_id}/stage-audit" and r["method"] == "GET" for r in routes)
    assert any(r["path"] == "/v1/sessions/{session_id}/stage-audit" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/sessions/{session_id}" and r["method"] == "DELETE" for r in routes)
    assert any(r["path"] == "/v1/sessions" and r["method"] == "DELETE" for r in routes)


def test_request_api_token_supports_bearer() -> None:
    token = _request_api_token({"Authorization": "Bearer secret-token"})
    assert token == "secret-token"


def test_request_api_token_supports_x_api_key() -> None:
    token = _request_api_token({"X-API-Key": "secret-token"})
    assert token == "secret-token"


def test_configured_api_token_none_when_empty(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_TOKEN", "   ")
    assert _configured_api_token() is None


def test_auth_required_by_default(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    assert _auth_required() is True


def test_assert_runtime_auth_configuration_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        _assert_runtime_auth_configuration()


def test_assert_runtime_auth_configuration_allows_dev_override(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)
    _assert_runtime_auth_configuration()


def test_origin_not_allowed_without_allowlist(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOWED_ORIGINS", raising=False)
    assert _is_origin_allowed("https://example.com") is False


def test_origin_allowed_with_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOWED_ORIGINS", "https://example.com")
    assert _is_origin_allowed("https://example.com") is True


def test_validated_manifest_path_rejects_unapproved_path(tmp_path, monkeypatch) -> None:
    disallowed = tmp_path / "outside.yaml"
    disallowed.write_text("manifests: []", encoding="utf-8")
    monkeypatch.delenv("NEPSIS_API_ALLOWED_MANIFEST_ROOTS", raising=False)
    with pytest.raises(ValueError):
        _validated_manifest_path(str(disallowed))


def test_validated_manifest_path_allows_env_root(tmp_path, monkeypatch) -> None:
    allowed_root = tmp_path / "manifests"
    allowed_root.mkdir(parents=True)
    allowed = allowed_root / "demo.yaml"
    allowed.write_text("manifests: []", encoding="utf-8")
    monkeypatch.setenv("NEPSIS_API_ALLOWED_MANIFEST_ROOTS", str(allowed_root))
    assert _validated_manifest_path(str(allowed)) == str(allowed.resolve())


def test_request_limit_env_parsers(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_MAX_REQUEST_BODY_BYTES", "2048")
    monkeypatch.setenv("NEPSIS_API_REQUEST_TIMEOUT_SECONDS", "3")
    assert _max_request_body_bytes() == 2048
    assert _request_timeout_seconds() == 3


def test_query_required_float_parses_value() -> None:
    assert _query_required_float({"max_age_seconds": ["3600"]}, "max_age_seconds") == 3600.0


def test_query_required_float_requires_param() -> None:
    with pytest.raises(ValueError):
        _query_required_float({}, "max_age_seconds")


def test_query_optional_bool_parses_values() -> None:
    assert _query_optional_bool({"dry_run": ["true"]}, "dry_run", default=False) is True
    assert _query_optional_bool({"dry_run": ["0"]}, "dry_run", default=True) is False


def test_query_optional_int_parses_values() -> None:
    assert _query_optional_int({"limit": ["25"]}, "limit", default=10) == 25
    assert _query_optional_int({}, "limit", default=10) == 10


def test_rate_limit_env_parsers(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS", "30")
    monkeypatch.setenv("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS", "99")
    assert _rate_limit_window_seconds() == 30
    assert _rate_limit_max_requests() == 99


def test_openapi_spec_contains_route_paths() -> None:
    spec = openapi_spec()
    assert spec["openapi"] == "3.1.0"
    assert "/v1/sessions" in spec["paths"]
    assert "get" in spec["paths"]["/v1/sessions"]
    assert "/v1/sessions/{session_id}/stage-audit" in spec["paths"]
    assert "get" in spec["paths"]["/v1/sessions/{session_id}/stage-audit"]
    assert "post" in spec["paths"]["/v1/sessions/{session_id}/stage-audit"]


def test_stage_audit_post_handler_accepts_context_payload(monkeypatch) -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={"text": "Decide escalation."},
    )
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True, "policy_violation": False})
    monkeypatch.setattr(api_server, "API", svc)

    result = api_server.EngineApiHandler._stage_audit_session(
        object(),
        sid,
        {
            "context": {
                "frame": {
                    "problem_statement": "Decide escalation now.",
                    "catastrophic_outcome": "Miss critical incident.",
                    "optimization_goal": "Protect users and reduce disruption.",
                    "decision_horizon": "short",
                    "key_uncertainty": "Signal quality from first report.",
                    "hard_constraints": ["No policy breach"],
                    "soft_constraints": ["Minimize disruption"],
                },
                "interpretation": {
                    "report_text": "obs: critical signal present\nobs: no policy violation",
                    "evidence_count": 2,
                    "report_synced": True,
                    "contradictions_status": "none_identified",
                    "contradictions_note": "",
                },
                "threshold": {
                    "loss_treat": 1.0,
                    "loss_not_treat": 9.0,
                    "warning_level": "red",
                    "gate_crossed": True,
                    "recommendation": "escalate",
                    "decision": "hold",
                    "hold_reason": "Need one more discriminator before recommendation.",
                },
            }
        },
    )
    assert result["policy"]["name"] == "nepsis_cgn.stage_audit"
    assert result["frame"]["status"] == "PASS"
    assert result["interpretation"]["status"] == "PASS"
    assert result["threshold"]["status"] == "PASS"
    assert result["source"]["context_applied"] is True


def test_stage_audit_post_handler_rejects_non_object_context(monkeypatch) -> None:
    svc = EngineApiService()
    created = svc.create_session(family="safety")
    sid = created["session_id"]
    monkeypatch.setattr(api_server, "API", svc)

    with pytest.raises(ValueError):
        api_server.EngineApiHandler._stage_audit_session(
            object(),
            sid,
            {"context": "invalid"},
        )


def test_stage_audit_http_post_route_accepts_context_payload(monkeypatch) -> None:
    svc = EngineApiService()
    created = svc.create_session(
        family="safety",
        governance_costs={"c_fp": 1, "c_fn": 9},
        frame={"text": "Decide escalation."},
    )
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True, "policy_violation": False})
    monkeypatch.setattr(api_server, "API", svc)
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")

    try:
        httpd = api_server.ThreadingHTTPServer(("127.0.0.1", 0), api_server.EngineApiHandler)
    except OSError as exc:
        pytest.skip(f"local bind unavailable in this environment: {exc}")

    thread: threading.Thread | None = None
    try:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        port = int(httpd.server_address[1])

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        payload = {
            "context": {
                "frame": {
                    "problem_statement": "Decide escalation now.",
                    "catastrophic_outcome": "Miss critical incident.",
                    "optimization_goal": "Protect users and reduce disruption.",
                    "decision_horizon": "short",
                    "key_uncertainty": "Signal quality from first report.",
                    "hard_constraints": ["No policy breach"],
                    "soft_constraints": ["Minimize disruption"],
                },
                "interpretation": {
                    "report_text": "obs: critical signal present\nobs: no policy violation",
                    "evidence_count": 2,
                    "report_synced": True,
                    "contradictions_status": "none_identified",
                    "contradictions_note": "",
                },
                "threshold": {
                    "loss_treat": 1.0,
                    "loss_not_treat": 9.0,
                    "warning_level": "red",
                    "gate_crossed": True,
                    "recommendation": "escalate",
                    "decision": "hold",
                    "hold_reason": "Need one more discriminator before recommendation.",
                },
            }
        }
        conn.request(
            "POST",
            f"/v1/sessions/{sid}/stage-audit",
            body=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        body = response.read()
        conn.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        if thread is not None:
            thread.join(timeout=2)

    assert response.status == 200
    parsed = json.loads(body.decode("utf-8"))
    assert parsed["policy"]["name"] == "nepsis_cgn.stage_audit"
    assert parsed["frame"]["status"] == "PASS"
    assert parsed["interpretation"]["status"] == "PASS"
    assert parsed["threshold"]["status"] == "PASS"
    assert parsed["source"]["context_applied"] is True
