from __future__ import annotations

import pytest

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
