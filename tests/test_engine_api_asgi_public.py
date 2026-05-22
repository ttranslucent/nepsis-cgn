from __future__ import annotations

import hashlib

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


def test_asgi_mvp_cors_allows_configured_origin(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")
    monkeypatch.setenv("NEPSIS_API_ALLOWED_ORIGINS", "https://nepsis-cgn.vercel.app")

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/mvp",
        json={"case_id": "clinical"},
        headers={
            "Authorization": "Bearer test-token",
            "Origin": "https://nepsis-cgn.vercel.app",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://nepsis-cgn.vercel.app"


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


def test_asgi_mcp_runs_stateless_tool_with_capability_token(monkeypatch, tmp_path) -> None:
    token = "capability-test-token"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)
    monkeypatch.setenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", f"test-token:{digest}")
    monkeypatch.setenv("NEPSIS_API_STORE_PATH", str(tmp_path / "mcp-should-not-exist.json"))

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

    assert response.status_code == 401


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
    assert payload["legal_next_tools"] == ["get_session_state", "lock_frame", "abandon_session"]


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
