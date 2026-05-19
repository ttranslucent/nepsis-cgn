from __future__ import annotations

from fastapi.testclient import TestClient

from nepsis_cgn.api import asgi


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


def test_asgi_mcp_lists_and_runs_public_mvp_tool(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.delenv("NEPSIS_API_TOKEN", raising=False)

    client = TestClient(asgi.create_app())
    listed = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    called = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "run_mvp", "arguments": {"case_id": "jailing"}},
        },
    )

    assert listed.status_code == 200
    tool_names = {tool["name"] for tool in listed.json()["result"]["tools"]}
    assert {"run_mvp", "get_mvp_schema", "health", "get_routes"} <= tool_names
    assert called.status_code == 200
    content = called.json()["result"]["content"]
    assert content[0]["type"] == "text"
    assert "nepsis.mvp_packet" in content[0]["text"]


def test_asgi_mcp_rejects_protected_tool_without_token(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")

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
    assert "authorization" in payload["error"]["message"].lower()
