from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest

import nepsis_cgn.api.operator_packet as operator_packet
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
    _request_owner_id,
    _rate_limit_key,
    _validated_manifest_path,
    route_manifest,
)


def _start_test_server() -> tuple[api_server.ThreadingHTTPServer, threading.Thread, int]:
    try:
        httpd = api_server.ThreadingHTTPServer(("127.0.0.1", 0), api_server.EngineApiHandler)
    except OSError as exc:
        pytest.skip(f"local bind unavailable in this environment: {exc}")

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd, thread, int(httpd.server_address[1])


def _stop_test_server(httpd: api_server.ThreadingHTTPServer, thread: threading.Thread) -> None:
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=2)


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_guide_text_sha256_canonicalizes_browser_paste_artifacts() -> None:
    browser_paste = "Cafe\u0301 concern\r\nline with trailing spaces   \r\n"
    server_text = "Café concern\nline with trailing spaces"

    assert operator_packet.canonical_guide_text(browser_paste) == server_text
    assert operator_packet.guide_text_sha256(browser_paste) == operator_packet.guide_text_sha256(server_text)


def _operator_frame() -> dict[str, object]:
    return {
        "text": "Decide whether to escalate response.",
        "objective_type": "decide",
        "domain": "safety",
        "time_horizon": "short",
        "rationale_for_change": (
            "Red channel: avoid missing a catastrophic incident | "
            "Blue channel: protect users while minimizing disruption | "
            "Uncertainty: signal quality from the first report"
        ),
        "constraints_hard": ["No policy breach"],
        "constraints_soft": ["Minimize disruption"],
    }


def _v3_field(
    state: str = "present", items: list[str] | None = None, rationale: str = "Reviewed."
) -> dict[str, object]:
    return {
        "status": state,
        "items": items if items is not None else ["captured"],
        "rationale": rationale,
    }


def _v3_intake_artifact() -> dict[str, object]:
    return {
        "layer": "intake",
        "summary": "intake layer artifact.",
        "goal_scope": _v3_field(items=["goal", "scope"]),
        "red_triggers": _v3_field(),
        "blue_opportunity_space": _v3_field(),
        "constraints": _v3_field(),
        "manifold_match_mismatch": _v3_field(),
        "still_blockers": _v3_field(
            "none_found", [], "No blocker found at this layer."
        ),
        "unresolved_questions": _v3_field(
            "none_found", [], "No unresolved question found at this layer."
        ),
        "audit_notes": _v3_field(items=["packet visible"]),
        "proposed_status": _v3_field(items=["ready"]),
        "lock_eligibility": _v3_field(items=["eligible"]),
        "layer_findings": {"risk": [], "ruin": [], "win": [], "recommendations": []},
        "intake": {
            "goal": "Prototype V3 layer locks.",
            "scope": "Operator packet layer loop.",
            "assumptions": ["Frame is locked."],
            "unresolved_questions": ["None for the prototype slice."],
        },
    }


_PROPOSAL_SECRET = "unit-test-proposal-receipt-secret"


def _receipt(
    packet: dict[str, object],
    *,
    target: str,
    model: str = "gpt-4.1-mini",
    proposed_text: str,
    receipt_id: str | None = None,
    loop_id: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_id": "nepsis.operator_model_proposal_receipt",
        "schema_version": "1.0.0",
        "receipt_id": receipt_id or str(uuid4()),
        "issued_at": "2026-06-12T00:00:00.000Z",
        "route": "/api/operator/model",
        "mode": "suggest_field",
        "target": target,
        "model": model,
        "loop_id": loop_id or str(packet["loop_id"]),
        "proposed_value_hash": _h(proposed_text),
    }
    signed = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body["signature"] = {
        "algorithm": "hmac-sha256",
        "key_id": "default",
        "signature": hmac.new(_PROPOSAL_SECRET.encode("utf-8"), signed, hashlib.sha256).hexdigest(),
        "signed_at": "2026-06-12T00:00:00.000Z",
    }
    return body


def _post_json(port: int, path: str, payload: dict[str, object]) -> tuple[int, dict[str, object]]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(
        "POST",
        path,
        body=json.dumps(payload),
        headers={"Content-Type": "application/json"},
    )
    response = conn.getresponse()
    body = response.read()
    conn.close()
    return response.status, json.loads(body.decode("utf-8"))


def test_bind_error_message_contains_actionable_steps() -> None:
    msg = _bind_error_message("127.0.0.1", 8787, PermissionError("Operation not permitted"))
    assert "127.0.0.1:8787" in msg
    assert "Use a different" in msg
    assert "Run outside restricted sandbox" in msg


def test_route_manifest_contains_routes_endpoint() -> None:
    routes = route_manifest()
    assert any(r["path"] == "/v1/routes" and r["method"] == "GET" for r in routes)
    assert any(r["path"] == "/v1/openapi.json" and r["method"] == "GET" for r in routes)
    assert any(r["path"] == "/v1/mvp" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator-packet/start" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator-packet/report" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator-packet/commit" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator-packet/guide" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator-packet/guide/patch-action" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator-packet/v3/start" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator-packet/v3/field" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator-packet/v3/propose" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator-packet/v3/lock" and r["method"] == "POST" for r in routes)
    assert any(r["path"] == "/v1/operator/session" and r["method"] == "GET" for r in routes)
    assert any(r["path"] == "/v1/operator/report" and r["method"] == "POST" for r in routes)
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


def test_api_token_compare_uses_constant_time_helper() -> None:
    assert api_server._api_token_matches("secret-token", "secret-token") is True
    assert api_server._api_token_matches("wrong-token", "secret-token") is False
    assert api_server._api_token_matches(None, "secret-token") is False


def test_rate_limit_key_ignores_spoofed_x_forwarded_for() -> None:
    handler = SimpleNamespace(
        headers={"X-Forwarded-For": "203.0.113.5", "Authorization": "Bearer attacker-controlled"},
        client_address=("198.51.100.7", 12345),
    )

    assert _rate_limit_key(handler) == "ip:198.51.100.7"


def test_request_owner_id_normalizes_header() -> None:
    assert _request_owner_id({"X-Nepsis-Session-Owner": " Alice@Example.com "}) == "alice@example.com"


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


def test_wildcard_cors_rejected_in_operator_mode(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("NEPSIS_DEPLOYMENT_MODE", "operator")

    assert _is_origin_allowed("https://example.com") is False


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


def test_validated_manifest_path_rejects_symlink_escape(tmp_path, monkeypatch) -> None:
    allowed_root = tmp_path / "manifests"
    outside_root = tmp_path / "outside"
    allowed_root.mkdir(parents=True)
    outside_root.mkdir(parents=True)
    outside = outside_root / "demo.yaml"
    outside.write_text("manifests: []", encoding="utf-8")
    link = allowed_root / "linked.yaml"
    link.symlink_to(outside)
    monkeypatch.setenv("NEPSIS_API_ALLOWED_MANIFEST_ROOTS", str(allowed_root))

    with pytest.raises(ValueError):
        _validated_manifest_path(str(link))


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
    assert "/v1/mvp" in spec["paths"]
    assert "post" in spec["paths"]["/v1/mvp"]
    assert "/v1/sessions/{session_id}/stage-audit" in spec["paths"]
    assert "get" in spec["paths"]["/v1/sessions/{session_id}/stage-audit"]
    assert "post" in spec["paths"]["/v1/sessions/{session_id}/stage-audit"]
    assert "/v1/sessions/{session_id}/workspace" in spec["paths"]
    assert "post" in spec["paths"]["/v1/sessions/{session_id}/workspace"]


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


def test_mvp_post_handler_emits_canonical_packet() -> None:
    result = api_server.EngineApiHandler._run_mvp(
        object(),
        {
            "case_id": "jailing",
            "input_text": "The source says JINGALL but candidate says JAILING.",
        },
    )
    assert result["schema_id"] == "nepsis.mvp_packet"
    assert result["red_channel"]["escalation_required"] is True
    assert result["denominator_collapse"]["retessellation_required"] is True


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


def test_workspace_post_handler_persists_state(monkeypatch) -> None:
    svc = EngineApiService()
    created = svc.create_session(family="safety", frame={"text": "Assess whether to escalate."})
    sid = created["session_id"]
    monkeypatch.setattr(api_server, "API", svc)

    result = api_server.EngineApiHandler._update_workspace_state(
        object(),
        sid,
        {
            "workspace_state": {
                "schema_version": "2026-05-19",
                "frame_locked": True,
                "report_locked": False,
                "stage_audit_context": {"frame": {"problem_statement": "Assess whether to escalate."}},
            }
        },
    )

    assert result["workspace_state"]["frame_locked"] is True
    assert svc.get_session(sid)["workspace_state"]["stage_audit_context"]["frame"]["problem_statement"]


def test_http_rejects_missing_api_token(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "secret-token")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/v1/mvp",
            body=json.dumps({"case_id": "jailing"}),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        body = response.read()
        conn.close()
    finally:
        _stop_test_server(httpd, thread)

    assert response.status == 401
    assert json.loads(body.decode("utf-8"))["error"] == "Unauthorized"


def test_http_failed_auth_consumes_rate_limit(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "secret-token")
    monkeypatch.setenv("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS", "1")
    monkeypatch.setenv("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(api_server, "API", EngineApiService())
    api_server._RATE_LIMIT_STATE.clear()

    httpd, thread, port = _start_test_server()
    try:
        statuses: list[int] = []
        for _ in range(2):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "POST",
                "/v1/mvp",
                body=json.dumps({"case_id": "jailing"}),
                headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
            )
            response = conn.getresponse()
            response.read()
            statuses.append(response.status)
            conn.close()
    finally:
        _stop_test_server(httpd, thread)
        api_server._RATE_LIMIT_STATE.clear()

    assert statuses == [401, 429]


def test_http_owner_header_blocks_cross_owner_session_access(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/v1/sessions",
            body=json.dumps({"family": "safety"}),
            headers={
                "Content-Type": "application/json",
                "X-Nepsis-Session-Owner": "alice@example.com",
            },
        )
        created_response = conn.getresponse()
        created_body = created_response.read()
        conn.close()

        created = json.loads(created_body.decode("utf-8"))
        sid = created["session_id"]

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "GET",
            f"/v1/sessions/{sid}",
            headers={"X-Nepsis-Session-Owner": "bob@example.com"},
        )
        blocked_response = conn.getresponse()
        blocked_body = blocked_response.read()
        conn.close()
    finally:
        _stop_test_server(httpd, thread)

    assert created_response.status == 200
    assert created["owner_id"] == "alice@example.com"
    assert blocked_response.status == 404
    assert json.loads(blocked_body.decode("utf-8"))["error"] == "Not found"


def test_http_rate_limit_returns_429(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS", "1")
    monkeypatch.setenv("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(api_server, "API", EngineApiService())
    api_server._RATE_LIMIT_STATE.clear()

    httpd, thread, port = _start_test_server()
    try:
        statuses: list[int] = []
        for _ in range(2):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request(
                "POST",
                "/v1/mvp",
                body=json.dumps({"case_id": "jailing"}),
                headers={"Content-Type": "application/json"},
            )
            response = conn.getresponse()
            response.read()
            statuses.append(response.status)
            conn.close()
    finally:
        _stop_test_server(httpd, thread)
        api_server._RATE_LIMIT_STATE.clear()

    assert statuses == [200, 429]


def test_http_request_body_limit_returns_413(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_API_MAX_REQUEST_BODY_BYTES", "8")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/v1/mvp",
            body=json.dumps({"case_id": "jailing"}),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        body = response.read()
        conn.close()
    finally:
        _stop_test_server(httpd, thread)

    assert response.status == 413
    assert "too large" in json.loads(body.decode("utf-8"))["error"].lower()


def test_http_operator_phase_rejection_returns_409(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "POST",
            "/v1/operator/report",
            body=json.dumps(
                {
                    "report_text": "obs: critical signal present",
                    "sign": {"critical_signal": True, "policy_violation": False},
                }
            ),
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        body = response.read()
        conn.close()
    finally:
        _stop_test_server(httpd, thread)

    parsed = json.loads(body.decode("utf-8"))
    assert response.status == 409
    assert parsed["schema_id"] == "nepsis.phase_rejection"
    assert parsed["attempted_tool"] == "run_report"


def test_http_operator_packet_flow_is_stateless_and_commits(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    monkeypatch.setattr(api_server, "API", EngineApiService())
    hard_text = "Maintain RED before BLUE sequencing."

    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        assert packet["schema_id"] == "nepsis.operator_packet"
        assert packet["phase"] == "frame_draft"

        status, packet = _post_json(
            port,
            "/v1/operator-packet/frame",
            {
                "packet": packet,
                "family": "safety",
                "governance": {"c_fp": 1, "c_fn": 9},
                "frame": {
                    "text": "Decide whether to escalate response.",
                    "objective_type": "decide",
                    "domain": "safety",
                    "time_horizon": "short",
                    "rationale_for_change": (
                        "Red channel: avoid missing a catastrophic incident | "
                        "Blue channel: minimize unnecessary disruption | "
                        "Uncertainty: first report quality"
                    ),
                    "constraints_hard": [hard_text],
                    "constraints_soft": ["Keep the audit trace concise."],
                },
                "assist_acceptances": [
                    {
                        "target": "frame.constraints_hard",
                        "source": "model_suggestion",
                        "model": "gpt-4.1-mini",
                        "disposition": "accepted",
                        "proposed_value_hash": _h(hard_text),
                        "final_value_hash": _h(hard_text),
                        "proposal_receipt": _receipt(
                            packet,
                            target="frame.constraints_hard",
                            proposed_text=hard_text,
                        ),
                        "summary": "Preserve sequencing.",
                    }
                ],
            },
        )
        assert status == 200
        assert packet["phase"] == "frame_locked"
        assert [entry["event"] for entry in packet["audit_trace"]] == ["LOCK_FRAME"]
        assert packet["audit_trace"][-1]["arguments"]["assist_acceptances"][0]["target"] == "frame.constraints_hard"

        restored = json.loads(json.dumps(packet))
        status, packet = _post_json(
            port,
            "/v1/operator-packet/report",
            {
                "packet": restored,
                "report_text": "obs: critical signal present\nobs: no policy violation",
                "sign": {"critical_signal": True, "policy_violation": False},
                "interpretation": {
                    "report_text": "obs: critical signal present\nobs: no policy violation",
                    "evidence_count": 2,
                    "report_synced": True,
                    "contradictions_status": "none_identified",
                    "contradictions_note": "",
                },
            },
        )
        assert status == 200
        assert packet["phase"] == "report_evaluated"
        assert packet["latest_step"]["governance"]["warning_level"] == "red"

        status, packet = _post_json(port, "/v1/operator-packet/report/lock", {"packet": packet})
        assert status == 200
        assert packet["phase"] == "report_locked"

        status, packet = _post_json(
            port,
            "/v1/operator-packet/threshold",
            {
                "packet": packet,
                "decision": "hold",
                "hold_reason": "Collect one additional discriminator before recommendation.",
                "cost_review_acknowledged": True,
                "cost_review_rationale": "Expected-loss tradeoff reviewed before holding.",
            },
        )
        assert status == 200
        assert packet["phase"] == "threshold_set"
        threshold_args = packet["audit_trace"][-1]["arguments"]
        assert threshold_args["cost_review_acknowledged"] is True
        assert (
            threshold_args["cost_review_rationale"]
            == "Expected-loss tradeoff reviewed before holding."
        )

        status, committed = _post_json(
            port,
            "/v1/operator-packet/commit",
            {
                "packet": packet,
                "carry_forward_frame": {
                    "text": "Continue escalation assessment after the next discriminator.",
                    "rationale_for_change": "Carry forward held threshold decision.",
                },
            },
        )
        assert status == 200
    finally:
        _stop_test_server(httpd, thread)

    assert committed["schema_id"] == "nepsis.operator_packet"
    assert committed["phase"] == "frame_draft"
    assert committed["audit_trace"] == []
    assert committed["previous_trace"][-1]["event"] == "COMMIT_ITERATION"
    assert committed["last_commit_packet"]["schema_id"] == "nepsis.operator_audit_packet"


def test_http_operator_packet_threshold_rejects_non_boolean_cost_review_acknowledgment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setattr(api_server, "API", EngineApiService())
    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        status, result = _post_json(
            port,
            "/v1/operator-packet/threshold",
            {
                "packet": packet,
                "decision": "hold",
                "cost_review_acknowledged": "yes",
            },
        )
    finally:
        _stop_test_server(httpd, thread)

    assert 400 <= status < 500
    assert "cost_review_acknowledged must be a boolean" in json.dumps(result)


def test_http_operator_packet_v3_layer_loop_is_stateless_and_inspectable(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_V3_PACKET_SEAL_SECRET", "unit-test-v3-layer-secret")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        status, packet = _post_json(
            port,
            "/v1/operator-packet/frame",
            {"packet": packet, "family": "safety", "frame": _operator_frame()},
        )
        assert status == 200
        status, packet = _post_json(
            port,
            "/v1/operator-packet/v3/start",
            {
                "packet": packet,
                "goal": "Prototype V3 layer locks.",
                "scope": "Operator packet layer loop.",
                "initial_context": "Use the locked frame.",
            },
        )
        assert status == 200
        status, rejection = _post_json(
            port,
            "/v1/operator-packet/v3/field",
            {
                "packet": packet,
                "layer": "blue",
                "field": "blue",
                "value": {"wins": ["Too early"]},
            },
        )
        assert status == 409
        assert rejection["failed_precondition"] == "v3_layer_order_required"
        assert rejection["current_layer"] == "intake"

        restored = json.loads(json.dumps(packet))
        packet = restored
        for field, value in _v3_intake_artifact().items():
            status, packet = _post_json(
                port,
                "/v1/operator-packet/v3/field",
                {
                    "packet": packet,
                    "layer": "intake",
                    "field": field,
                    "value": value,
                },
            )
            assert status == 200
        status, packet = _post_json(
            port,
            "/v1/operator-packet/v3/propose",
            {"packet": packet, "layer": "intake"},
        )
        assert status == 200
        proposal = packet["v3_layer_loop"]["packet"]["current_proposal"]
        status, packet = _post_json(
            port,
            "/v1/operator-packet/v3/lock",
            {
                "packet": packet,
                "layer": "intake",
                "lock_assertion": {
                    "asserted": True,
                    "assertion_text": "I explicitly lock the intake layer.",
                    "proposal_hash": proposal["artifact_hash"],
                    "lock_nonce": "operator-intake-nonce",
                },
            },
        )
        assert status == 200
        status, inspected = _post_json(
            port, "/v1/operator-packet/state", {"packet": packet}
        )
        assert status == 200
    finally:
        _stop_test_server(httpd, thread)

    assert packet["v3_layer_loop"]["packet"]["current_layer"] == "red"
    assert packet["v3_layer_loop"]["navigation_shortcuts"]["next_layer"] == "Meta+ArrowRight"
    assert "set_v3_layer_field" in inspected["legal_next_tools"]
    events = [entry["event"] for entry in packet["audit_trace"]]
    assert events[:2] == ["LOCK_FRAME", "START_V3_LAYER_LOOP"]
    assert events.count("SET_V3_LAYER_FIELD") == len(_v3_intake_artifact())
    assert events[-2:] == ["PROPOSE_V3_LAYER_LOCK", "LOCK_V3_LAYER"]


def test_http_operator_packet_guide_turn_is_packet_visible_and_sealed(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-operator-seal")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200

        status, guided = _post_json(
            port,
            "/v1/operator-packet/guide",
            {
                "packet": packet,
                "domain_adapter": "clinical",
                "user_message": "I am worried this is sepsis but something feels off.",
                "guide": {
                    "next_question": "What irreversible action are you considering first?",
                    "visible_scaffold": {
                        "current_frame": "Possible sepsis with alternate frame open.",
                        "open_constraint": "Do not close before a discriminator addresses the miss risk.",
                        "red_concern": "Delayed source control or undertreatment.",
                        "ready_to_lock": ["Empiric antibiotics are reasonable to consider."],
                    },
                    "packet_delta_preview": {
                        "frame.text": "Decide the next irreversible action under possible sepsis.",
                        "frame.constraints_hard": [
                            "Do not close the alternate frame until a discriminator addresses high-cost miss risk."
                        ],
                    },
                    "proposed_updates": [
                        {
                            "target": "frame.text",
                            "proposed_value": "Decide the next irreversible action under possible sepsis.",
                            "rationale": "User supplied a vague concern that needs a decision frame.",
                        },
                        {
                            "target": "frame.constraints_soft",
                            "proposed_value": [
                                "Avoid unnecessary intervention if a discriminator safely shifts the frame."
                            ],
                            "rationale": "Low-consequence wording refinement.",
                        },
                    ],
                    "fields_ready_to_lock": ["frame.text"],
                    "blocking_uncertainties": ["first irreversible action"],
                    "ranked_discriminators": [
                        {
                            "label": "irreversible action",
                            "question": "Antibiotics, fluids, transfer, imaging, or observation?",
                            "why_it_moves_decision": "Separates safety action from diagnostic closure.",
                            "basis": "consequence asymmetry",
                            "rank": 1,
                        }
                    ],
                },
            },
        )
        assert status == 200
        status, inspected = _post_json(port, "/v1/operator-packet/state", {"packet": guided})
        tampered_guide_state = json.loads(json.dumps(guided))
        tampered_guide_state["guide_state"]["last_turn"]["next_question"] = "Tampered question"
        state_status, state_rejected = _post_json(
            port, "/v1/operator-packet/state", {"packet": tampered_guide_state}
        )
        tampered_audit_trace = json.loads(json.dumps(guided))
        tampered_audit_trace["audit_trace"][-1]["arguments"]["next_question"] = "Tampered question"
        audit_status, audit_rejected = _post_json(
            port, "/v1/operator-packet/state", {"packet": tampered_audit_trace}
        )
    finally:
        _stop_test_server(httpd, thread)

    assert guided["schema_id"] == "nepsis.operator_packet"
    assert guided["phase"] == "frame_draft"
    assert guided["guide_state"]["schema_id"] == "nepsis.operator_guide_state"
    assert guided["guide_state"]["domain_adapter"] == "clinical"
    assert guided["guide_state"]["message_count"] == 1
    assert guided["guide_state"]["last_turn"]["user_message_hash"] == _h(
        "I am worried this is sepsis but something feels off."
    )
    assert guided["guide_state"]["last_turn"]["user_message_excerpt"].endswith("feels off.")
    assert guided["guide_state"]["last_turn"]["ranked_discriminators"][0]["rank"] == 1
    assert guided["guide_state"]["last_turn"]["ranked_discriminators"][0]["basis"] == "consequence asymmetry"
    assert guided["guide_state"]["last_turn"]["proposed_updates"][0]["consequence_level"] == "high"
    assert guided["guide_state"]["last_turn"]["proposed_updates"][0]["requires_echo_confirmation"] is True
    assert guided["guide_state"]["last_turn"]["proposed_updates"][1]["consequence_level"] == "low"
    assert guided["guide_state"]["last_turn"]["proposed_updates"][1]["requires_echo_confirmation"] is False
    assert guided["audit_trace"][-1]["event"] == "GUIDE_TURN"
    assert guided["audit_trace"][-1]["arguments"]["domain_adapter"] == "clinical"
    assert inspected["guide_state"]["last_turn"]["next_question"] == (
        "What irreversible action are you considering first?"
    )
    assert state_status == 400
    assert "integrity seal" in state_rejected["error"]
    assert audit_status == 400
    assert "integrity seal" in audit_rejected["error"]


def test_http_operator_packet_guide_projection_rejects_resealed_tamper(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-operator-seal")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        status, guided = _post_json(
            port,
            "/v1/operator-packet/guide",
            {
                "packet": packet,
                "domain_adapter": "general",
                "user_message": "Should we expand hours?",
                "guide": {
                    "next_question": "What is the irreversible commitment?",
                    "proposed_updates": [
                        {
                            "patch_id": "patch_frame_text",
                            "target": "frame.text",
                            "proposed_value": "Decide whether to expand hours.",
                        }
                    ],
                },
            },
        )
        assert status == 200

        tampered_event = json.loads(json.dumps(guided))
        tampered_event["audit_trace"][-1]["arguments"]["turn"]["next_question"] = "Tampered"
        tampered_event = operator_packet._seal_packet(tampered_event)
        event_status, event_rejected = _post_json(
            port, "/v1/operator-packet/state", {"packet": tampered_event}
        )

        tampered_projection = json.loads(json.dumps(guided))
        tampered_projection["guide_state"]["last_turn"]["next_question"] = "Tampered"
        tampered_projection = operator_packet._seal_packet(tampered_projection)
        projection_status, projection_rejected = _post_json(
            port, "/v1/operator-packet/state", {"packet": tampered_projection}
        )
    finally:
        _stop_test_server(httpd, thread)

    assert event_status == 400
    assert "guide event chain breaks" in event_rejected["error"]
    assert projection_status == 400
    assert "guide_state does not match" in projection_rejected["error"]


def test_http_operator_packet_guide_patch_action_requires_fresh_confirmation(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-operator-seal")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    proposed = "Decide whether to expand urgent care coverage."
    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        status, guided = _post_json(
            port,
            "/v1/operator-packet/guide",
            {
                "packet": packet,
                "domain_adapter": "general",
                "user_message": "Should we go 24/7?",
                "guide": {
                    "next_question": "What downside can you not walk back?",
                    "proposed_updates": [
                        {
                            "patch_id": "patch_frame_text",
                            "target": "frame.text",
                            "proposed_value": proposed,
                        }
                    ],
                },
            },
        )
        assert status == 200

        status, stale = _post_json(
            port,
            "/v1/operator-packet/guide/patch-action",
            {
                "packet": guided,
                "patch_id": "patch_frame_text",
                "action": "accept",
                "confirmation": {
                    "checked": True,
                    "text_sha256": operator_packet.guide_text_sha256("stale"),
                },
            },
        )
        assert status == 400

        status, accepted = _post_json(
            port,
            "/v1/operator-packet/guide/patch-action",
            {
                "packet": guided,
                "patch_id": "patch_frame_text",
                "action": "accept",
                "confirmation": {
                    "checked": True,
                    "text_sha256": operator_packet.guide_text_sha256(proposed),
                },
            },
        )
    finally:
        _stop_test_server(httpd, thread)

    assert "confirmation hash does not match" in stale["error"]
    assert status == 200
    assert accepted["audit_trace"][-1]["event"] == "GUIDE_PATCH_ACTION"
    patch = accepted["guide_state"]["patches"][0]
    assert patch["status"] == "accepted"
    assert patch["confirmation_hash"] == operator_packet.guide_text_sha256(proposed)


def test_http_operator_packet_guide_turn_supersedes_pending_patch(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-operator-seal")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        status, first = _post_json(
            port,
            "/v1/operator-packet/guide",
            {
                "packet": packet,
                "domain_adapter": "general",
                "user_message": "I need a frame.",
                "guide": {
                    "next_question": "What is the first constraint?",
                    "proposed_updates": [
                        {
                            "patch_id": "patch_old",
                            "target": "frame.text",
                            "proposed_value": "Old frame.",
                        }
                    ],
                },
            },
        )
        assert status == 200
        status, second = _post_json(
            port,
            "/v1/operator-packet/guide",
            {
                "packet": first,
                "domain_adapter": "general",
                "user_message": "Actually the decision is narrower.",
                "guide": {
                    "next_question": "What would reopen the frame?",
                    "proposed_updates": [
                        {
                            "patch_id": "patch_new",
                            "target": "frame.text",
                            "proposed_value": "New frame.",
                        }
                    ],
                },
            },
        )
    finally:
        _stop_test_server(httpd, thread)

    assert status == 200
    patches = {row["patch_id"]: row for row in second["guide_state"]["patches"]}
    assert patches["patch_old"]["status"] == "superseded"
    assert patches["patch_old"]["superseded_by"] == "patch_new"
    assert patches["patch_new"]["status"] == "proposed"


def test_http_operator_packet_lock_frame_records_guide_refusal_event(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-operator-seal")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        status, guided = _post_json(
            port,
            "/v1/operator-packet/guide",
            {
                "packet": packet,
                "domain_adapter": "general",
                "user_message": "Can we lock this?",
                "guide": {
                    "next_question": "What is still blocking?",
                    "blocking_uncertainties": ["downside is unbounded"],
                },
            },
        )
        assert status == 200
        status, refused = _post_json(
            port,
            "/v1/operator-packet/frame",
            {"packet": guided, "family": "safety", "frame": _operator_frame()},
        )
    finally:
        _stop_test_server(httpd, thread)

    assert status == 200
    assert refused["phase"] == "frame_draft"
    assert refused["audit_trace"][-1]["event"] == "GUIDE_LOCK_REFUSAL"
    assert refused["audit_trace"][-1]["arguments"]["reason"] == "blocking_uncertainties_present"
    assert refused["guide_state"]["convergence"]["lock_refusal_count"] == 1


def test_http_operator_packet_guide_turn_remains_available_after_frame_lock(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setattr(api_server, "API", EngineApiService())

    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        status, locked = _post_json(
            port,
            "/v1/operator-packet/frame",
            {"packet": packet, "family": "safety", "frame": _operator_frame()},
        )
        assert status == 200
        status, guided = _post_json(
            port,
            "/v1/operator-packet/guide",
            {
                "packet": locked,
                "domain_adapter": "general",
                "user_message": "Can you keep guiding?",
                "guide": {"next_question": "What is still uncertain?"},
            },
        )
    finally:
        _stop_test_server(httpd, thread)

    assert status == 200
    assert guided["schema_id"] == "nepsis.operator_packet"
    assert guided["phase"] == "frame_locked"
    assert guided["audit_trace"][-1]["event"] == "GUIDE_TURN"
    assert guided["guide_state"]["last_turn"]["next_question"] == "What is still uncertain?"
    assert "guide_turn" in guided["legal_next_tools"]


def test_http_operator_packet_frame_rejects_assist_hash_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    monkeypatch.setattr(api_server, "API", EngineApiService())
    proposed_text = "wrong"
    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        status, result = _post_json(
            port,
            "/v1/operator-packet/frame",
            {
                "packet": packet,
                "family": "safety",
                "frame": {
                    "text": "Decide whether to escalate response.",
                    "objective_type": "decide",
                    "domain": "safety",
                    "time_horizon": "short",
                    "rationale_for_change": (
                        "Red channel: avoid missing harm | "
                        "Blue channel: minimize disruption | "
                        "Uncertainty: signal quality"
                    ),
                    "constraints_hard": ["Maintain RED before BLUE sequencing."],
                    "constraints_soft": ["Keep the audit trace concise."],
                },
                "assist_acceptances": [
                    {
                        "target": "frame.constraints_hard",
                        "model": "gpt-4.1-mini",
                        "disposition": "accepted",
                        "proposed_value_hash": _h(proposed_text),
                        "final_value_hash": _h(proposed_text),
                        "proposal_receipt": _receipt(
                            packet,
                            target="frame.constraints_hard",
                            proposed_text=proposed_text,
                        ),
                        "summary": "False claim.",
                    }
                ],
            },
        )
    finally:
        _stop_test_server(httpd, thread)

    assert 400 <= status < 500
    assert "final_value_hash mismatch" in json.dumps(result)


def test_http_operator_packet_frame_rejects_tampered_proposal_receipt(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    monkeypatch.setattr(api_server, "API", EngineApiService())
    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        hard_text = "Maintain RED before BLUE sequencing."
        receipt = _receipt(packet, target="frame.constraints_hard", proposed_text=hard_text)
        receipt["target"] = "frame.text"
        status, result = _post_json(
            port,
            "/v1/operator-packet/frame",
            {
                "packet": packet,
                "family": "safety",
                "frame": {
                    "text": "Decide whether to escalate response.",
                    "objective_type": "decide",
                    "domain": "safety",
                    "time_horizon": "short",
                    "rationale_for_change": (
                        "Red channel: avoid missing harm | "
                        "Blue channel: minimize disruption | "
                        "Uncertainty: signal quality"
                    ),
                    "constraints_hard": [hard_text],
                    "constraints_soft": ["Keep the audit trace concise."],
                },
                "assist_acceptances": [
                    {
                        "target": "frame.constraints_hard",
                        "source": "model_suggestion",
                        "model": "gpt-4.1-mini",
                        "disposition": "accepted",
                        "proposed_value_hash": _h(hard_text),
                        "final_value_hash": _h(hard_text),
                        "proposal_receipt": receipt,
                        "summary": "Tampered receipt target.",
                    }
                ],
            },
        )
    finally:
        _stop_test_server(httpd, thread)

    assert 400 <= status < 500
    assert "proposal_receipt target mismatch" in json.dumps(result)


def test_http_operator_packet_threshold_rejects_wrong_assist_scope(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    monkeypatch.setattr(api_server, "API", EngineApiService())
    proposed_text = "Decide whether to escalate response."
    httpd, thread, port = _start_test_server()
    try:
        status, packet = _post_json(port, "/v1/operator-packet/start", {})
        assert status == 200
        status, packet = _post_json(
            port,
            "/v1/operator-packet/frame",
            {
                "packet": packet,
                "family": "safety",
                "frame": {
                    "text": "Decide whether to escalate response.",
                    "objective_type": "decide",
                    "domain": "safety",
                    "time_horizon": "short",
                    "rationale_for_change": (
                        "Red channel: avoid missing harm | "
                        "Blue channel: minimize disruption | "
                        "Uncertainty: signal quality"
                    ),
                    "constraints_hard": ["Maintain RED before BLUE sequencing."],
                    "constraints_soft": ["Keep the audit trace concise."],
                },
            },
        )
        assert status == 200
        status, packet = _post_json(
            port,
            "/v1/operator-packet/report",
            {
                "packet": packet,
                "report_text": "obs: critical signal present\nobs: no policy violation",
                "sign": {"critical_signal": True, "policy_violation": False},
            },
        )
        assert status == 200
        status, packet = _post_json(port, "/v1/operator-packet/report/lock", {"packet": packet})
        assert status == 200
        status, result = _post_json(
            port,
            "/v1/operator-packet/threshold",
            {
                "packet": packet,
                "decision": "hold",
                "hold_reason": "Collect one additional discriminator.",
                "assist_acceptances": [
                    {
                        "target": "frame.text",
                        "model": "gpt-4.1-mini",
                        "disposition": "accepted",
                        "proposed_value_hash": _h(proposed_text),
                        "final_value_hash": _h(proposed_text),
                        "proposal_receipt": _receipt(packet, target="frame.text", proposed_text=proposed_text),
                        "summary": "Wrong transition.",
                    }
                ],
            },
        )
    finally:
        _stop_test_server(httpd, thread)

    assert 400 <= status < 500
    assert "not part of this transition" in json.dumps(result)


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
