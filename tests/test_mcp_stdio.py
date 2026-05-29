from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _start_mcp_stdio(tmp_path: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env["NEPSIS_API_STORE_PATH"] = str(tmp_path / "mcp-sessions.json")
    return subprocess.Popen(
        [sys.executable, "-m", "nepsis_cgn.mcp.stdio"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def _send(proc: subprocess.Popen[str], payload: dict[str, Any]) -> dict[str, Any]:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    assert line, "MCP stdio process exited before responding"
    return json.loads(line)


def _tool_text(response: dict[str, Any]) -> dict[str, Any]:
    content = response["result"]["content"]
    assert content[0]["type"] == "text"
    return json.loads(content[0]["text"])


def test_mcp_stdio_lists_public_and_operator_phase_tools(tmp_path: Path) -> None:
    proc = _start_mcp_stdio(tmp_path)
    try:
        initialized = _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        listed = _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    finally:
        proc.terminate()
        _, stderr = proc.communicate(timeout=5)

    assert initialized["result"]["serverInfo"]["name"] == "nepsis-cgn-local"
    tool_names = {tool["name"] for tool in listed["result"]["tools"]}
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
    assert "step_session" not in tool_names
    assert "reframe_session" not in tool_names
    assert not stderr.strip()


def test_mcp_stdio_get_routes_returns_route_manifest(tmp_path: Path) -> None:
    proc = _start_mcp_stdio(tmp_path)
    try:
        response = _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "get_routes", "arguments": {}},
            },
        )
    finally:
        proc.terminate()
        _, stderr = proc.communicate(timeout=5)

    routes = _tool_text(response)["routes"]
    assert any(route["path"] == "/mcp" and route["method"] == "POST" for route in routes)
    assert any(route["path"] == "/v1/mvp" and route["method"] == "POST" for route in routes)
    assert not stderr.strip()


def test_mcp_stdio_run_mvp_and_stateless_phase_rejection_are_json_rpc(tmp_path: Path) -> None:
    store_path = tmp_path / "mcp-sessions.json"
    proc = _start_mcp_stdio(tmp_path)
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        mvp = _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "run_mvp", "arguments": {"case_id": "jailing"}},
            },
        )
        started = _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "start_operator_packet", "arguments": {}},
            },
        )
        packet = _tool_text(started)
        rejected = _send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "run_report",
                    "arguments": {
                        "packet": packet,
                        "report_text": "obs: critical signal present",
                        "sign": {"critical_signal": True, "policy_violation": False},
                    },
                },
            },
        )
    finally:
        proc.terminate()
        _, stderr = proc.communicate(timeout=5)

    assert mvp["result"]["isError"] is False
    assert _tool_text(mvp)["schema_id"] == "nepsis.mvp_packet"
    assert started["result"]["isError"] is False
    assert packet["schema_id"] == "nepsis.operator_packet"
    assert rejected["result"]["isError"] is True
    rejection = _tool_text(rejected)
    assert rejection["schema_id"] == "nepsis.phase_rejection"
    assert rejection["attempted_tool"] == "run_report"
    assert rejection["current_phase"] == "frame_draft"
    assert not stderr.strip()
    assert not store_path.exists()
