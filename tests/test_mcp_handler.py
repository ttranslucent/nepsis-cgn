from __future__ import annotations

import hashlib
import json
import logging

from nepsis_cgn.mcp.handler import handle_mcp_request


def _tool_payload(response: dict[str, object]) -> dict[str, object]:
    result = response["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    text = first["text"]
    assert isinstance(text, str)
    return json.loads(text)


def test_remote_tool_call_without_capability_token_rejects(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", raising=False)

    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "start_operator_packet", "arguments": {}},
        },
        headers={},
        require_capability_token=True,
        server_name="nepsis-cgn",
    )

    assert response is not None
    assert response["error"]["code"] == -32001
    assert "capability" in response["error"]["message"].lower()


def test_capability_token_logs_metadata_without_raw_token(monkeypatch, caplog) -> None:
    token = "capability-test-token-for-log-check"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    monkeypatch.setenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", f"log-token:{digest}")
    caplog.set_level(logging.INFO, logger="nepsis_cgn.mcp.handler")

    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "start_operator_packet", "arguments": {}},
        },
        headers={"Authorization": f"Bearer {token}"},
        require_capability_token=True,
        server_name="nepsis-cgn",
    )

    assert response is not None
    assert _tool_payload(response)["schema_id"] == "nepsis.operator_packet"
    assert token not in caplog.text
    assert "Authorization" not in caplog.text
    assert '"token_id": "log-token"' in caplog.text
    assert '"packet_hash": "' in caplog.text
