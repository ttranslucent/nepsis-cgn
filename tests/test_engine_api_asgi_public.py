from __future__ import annotations

import hashlib
from types import SimpleNamespace

from fastapi.testclient import TestClient

from nepsis_cgn.api import asgi
from nepsis_cgn.api.service import EngineApiService


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


def test_asgi_mvp_requires_token_in_production_mode(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")

    client = TestClient(asgi.create_app())
    unauthorized = client.post("/v1/mvp", json={"case_id": "jailing"})
    authorized = client.post(
        "/v1/mvp",
        json={"case_id": "jailing"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["schema_id"] == "nepsis.mvp_packet"


def test_asgi_api_token_compare_uses_constant_time_helper() -> None:
    assert asgi._api_token_matches("test-token", "test-token") is True
    assert asgi._api_token_matches("wrong-token", "test-token") is False
    assert asgi._api_token_matches(None, "test-token") is False


def test_asgi_failed_auth_consumes_rate_limit(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")
    monkeypatch.setenv("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS", "1")
    monkeypatch.setenv("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS", "60")
    asgi._RATE_LIMIT_STATE.clear()

    client = TestClient(asgi.create_app())
    first = client.post(
        "/v1/mvp",
        json={"case_id": "jailing"},
        headers={"Authorization": "Bearer wrong"},
    )
    second = client.post(
        "/v1/mvp",
        json={"case_id": "jailing"},
        headers={"Authorization": "Bearer wrong"},
    )

    asgi._RATE_LIMIT_STATE.clear()
    assert first.status_code == 401
    assert second.status_code == 429


def test_asgi_rate_limit_key_ignores_spoofed_x_forwarded_for() -> None:
    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.5"},
        client=SimpleNamespace(host="198.51.100.7"),
    )

    assert asgi._rate_limit_key(request) == "ip:198.51.100.7"


def test_asgi_mvp_cors_allows_configured_origin(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")
    monkeypatch.setenv("NEPSIS_API_ALLOWED_ORIGINS", "https://nepsis-cgn.vercel.app")

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/mvp",
        json={"case_id": "sea_ivdu"},
        headers={
            "Authorization": "Bearer test-token",
            "Origin": "https://nepsis-cgn.vercel.app",
        },
    )

    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"]
        == "https://nepsis-cgn.vercel.app"
    )
    assert response.json()["case_id"] == "sea_ivdu"


def test_asgi_mvp_rejects_retired_public_clinical_case_id(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)

    client = TestClient(asgi.create_app())
    response = client.post("/v1/mvp", json={"case_id": "clinical"})

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "case_id must be one of: jailing, sea_ivdu, wirecard"
    )


def test_asgi_wildcard_cors_rejected_in_operator_mode(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("NEPSIS_DEPLOYMENT_MODE", "operator")

    try:
        assert asgi._is_origin_allowed("https://example.com") is False
    finally:
        monkeypatch.delenv("NEPSIS_DEPLOYMENT_MODE", raising=False)


def test_asgi_mvp_accepts_input_text_for_direct_packet_builder_callers(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)
    direct_input = (
        "Direct caller compatibility: source says JINGALL, candidate says JAILING."
    )

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/mvp",
        json={"case_id": "jailing", "input_text": direct_input},
    )

    assert response.status_code == 200
    packet = response.json()
    assert packet["schema_id"] == "nepsis.mvp_packet"
    assert packet["case_id"] == "jailing"
    assert packet["input_text"] == direct_input
    assert packet["red_channel"]["escalation_required"] is True


def test_asgi_mcp_lists_without_capability_token(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)
    monkeypatch.delenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", raising=False)

    client = TestClient(asgi.create_app())
    initialized = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}},
    )
    listed = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )

    assert initialized.status_code == 200
    assert initialized.json()["result"]["serverInfo"]["name"] == "nepsis-cgn"
    assert listed.status_code == 200
    tool_names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert {
        "run_mvp",
        "get_mvp_schema",
        "health",
        "start_operator_packet",
        "lock_frame",
        "run_report",
        "lock_report",
        "set_threshold_decision",
        "commit_iteration",
        "abandon_packet",
    } <= tool_names


def test_asgi_mcp_rejects_tool_call_without_capability_token(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)
    monkeypatch.delenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", raising=False)

    client = TestClient(asgi.create_app())
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_routes", "arguments": {}},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32001
    assert "capability" in payload["error"]["message"].lower()


def test_asgi_mcp_runs_stateless_tool_with_capability_token(
    monkeypatch, tmp_path
) -> None:
    token = "capability-test-token"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)
    monkeypatch.setenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", f"test-token:{digest}")
    monkeypatch.setenv(
        "NEPSIS_API_STORE_PATH", str(tmp_path / "mcp-should-not-exist.json")
    )

    client = TestClient(asgi.create_app())
    response = client.post(
        "/mcp",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "start_operator_packet", "arguments": {}},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    content = payload["result"]["content"]
    assert content[0]["type"] == "text"
    assert "nepsis.operator_packet" in content[0]["text"]
    assert not (tmp_path / "mcp-should-not-exist.json").exists()


def test_asgi_operator_routes_require_token(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")
    monkeypatch.setattr(asgi, "API", EngineApiService())

    client = TestClient(asgi.create_app())
    response = client.get("/v1/operator/session")
    packet_response = client.post("/v1/operator-packet/start", json={})

    assert response.status_code == 401
    assert packet_response.status_code == 401


def test_asgi_owner_header_returns_generic_404_for_cross_owner_session(
    monkeypatch,
) -> None:
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)
    monkeypatch.setattr(asgi, "API", EngineApiService())

    client = TestClient(asgi.create_app())
    created = client.post(
        "/v1/sessions",
        json={"family": "safety"},
        headers={"X-Nepsis-Session-Owner": "alice@example.com"},
    )
    blocked = client.get(
        f"/v1/sessions/{created.json()['session_id']}",
        headers={"X-Nepsis-Session-Owner": "bob@example.com"},
    )

    assert created.status_code == 200
    assert blocked.status_code == 404
    assert blocked.json()["detail"] == "Not found"


def test_asgi_operator_packet_phase_rejection_maps_to_409(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")
    headers = {"Authorization": "Bearer test-token"}

    client = TestClient(asgi.create_app())
    started = client.post("/v1/operator-packet/start", headers=headers, json={})
    response = client.post(
        "/v1/operator-packet/report",
        headers=headers,
        json={
            "packet": started.json(),
            "report_text": "obs: critical signal present",
            "sign": {"critical_signal": True, "policy_violation": False},
        },
    )

    assert started.status_code == 200
    assert response.status_code == 409
    payload = response.json()
    assert payload["schema_id"] == "nepsis.phase_rejection"
    assert payload["attempted_tool"] == "run_report"
    assert payload["legal_next_tools"] == [
        "start_operator_packet",
        "lock_frame",
        "abandon_packet",
    ]


def test_asgi_operator_phase_rejection_maps_to_409(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")
    monkeypatch.setattr(asgi, "API", EngineApiService())

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/operator/report",
        headers={"Authorization": "Bearer test-token"},
        json={
            "report_text": "obs: critical signal present",
            "sign": {"critical_signal": True, "policy_violation": False},
        },
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["schema_id"] == "nepsis.phase_rejection"
    assert payload["attempted_tool"] == "run_report"
    assert payload["legal_next_tools"] == [
        "get_session_state",
        "lock_frame",
        "abandon_session",
    ]


def test_asgi_operator_lock_report_preserves_passing_gate_state(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")
    monkeypatch.setattr(asgi, "API", EngineApiService())
    headers = {"Authorization": "Bearer test-token"}

    client = TestClient(asgi.create_app())
    locked = client.post(
        "/v1/operator/frame",
        headers=headers,
        json={
            "family": "safety",
            "governance": {"c_fp": 1, "c_fn": 9},
            "frame": _operator_frame(),
        },
    )
    reported = client.post(
        "/v1/operator/report",
        headers=headers,
        json={
            "report_text": "obs: critical signal present\nobs: no policy violation",
            "sign": {"critical_signal": True, "policy_violation": False},
            "interpretation": {
                "report_text": "obs: critical signal present\nobs: no policy violation",
                "evidence_count": 2,
                "contradictions_status": "none_identified",
                "contradictions_note": "",
                "contradiction_density": 0.0,
            },
        },
    )
    report_locked = client.post("/v1/operator/report/lock", headers=headers)

    assert locked.status_code == 200
    assert reported.status_code == 200
    assert report_locked.status_code == 200
    payload = report_locked.json()
    assert payload["phase"] == "report_locked"
    assert payload["audit"]["interpretation"]["status"] == "PASS"
    assert payload["audit"]["threshold"]["status"] == "BLOCK"
