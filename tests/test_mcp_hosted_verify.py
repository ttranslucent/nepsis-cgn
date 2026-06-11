from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "mcp-hosted-verify.py"
DOC = ROOT / "docs" / "hosted-mcp-codex.md"


def test_hosted_mcp_docs_include_codex_http_config_and_mvp_boundary() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "codex mcp add nepsiscgn-hosted --url" in text
    assert "--bearer-token-env-var NEPSIS_MCP_CAPABILITY_TOKEN" in text
    assert "NEPSIS_MCP_CAPABILITY_TOKEN_HASHES" in text
    assert "/mvp remains frozen, public, deterministic, and model-free" in text
    assert "scripts/mcp-hosted-verify.py" in text


def test_mcp_hosted_verifier_is_valid_python() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(VERIFIER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_mcp_hosted_verifier_accepts_codex_streamable_http_config(tmp_path: Path) -> None:
    requests: list[dict[str, Any]] = []
    token = "hosted-capability-token"

    class HostedMcpHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw)
            requests.append(
                {
                    "path": self.path,
                    "body": body,
                    "authorization": self.headers.get("Authorization"),
                }
            )

            if self.path != "/mcp":
                self._send_json(404, {"error": "not found"})
                return

            method = body.get("method")
            if method == "initialize":
                self._send_json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "result": {
                            "protocolVersion": "2025-06-18",
                            "serverInfo": {"name": "nepsis-cgn", "version": "0.3.0"},
                            "capabilities": {"tools": {}},
                        },
                    },
                )
                return
            if method == "tools/list":
                self._send_json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "result": {
                            "tools": [
                                {"name": "run_mvp"},
                                {"name": "get_mvp_schema"},
                                {"name": "health"},
                                {"name": "get_routes"},
                                {"name": "start_operator_packet"},
                            ]
                        },
                    },
                )
                return
            if method == "tools/call":
                if self.headers.get("Authorization") != f"Bearer {token}":
                    self._send_json(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "id": body.get("id"),
                            "error": {
                                "code": -32001,
                                "message": "MCP tool requires a valid Nepsis capability token.",
                            },
                        },
                    )
                    return
                self._send_json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {
                                            "schema_id": "nepsis.operator_packet",
                                            "schema_version": "2.1.0",
                                            "phase": "frame_draft",
                                            "legal_next_tools": [
                                                "start_operator_packet",
                                                "lock_frame",
                                                "abandon_packet",
                                            ],
                                            "integrity": {
                                                "seal_version": "hmac-sha256:v1",
                                                "counter": 0,
                                                "sealed_fields": ["audit_trace"],
                                                "seal": "mocked-seal",
                                            },
                                        }
                                    ),
                                }
                            ],
                            "isError": False,
                        },
                    },
                )
                return
            self._send_json(400, {"error": "unsupported"})

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), HostedMcpHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = tmp_path / "config.toml"
        config.write_text(
            "\n".join(
                [
                    "[mcp_servers.nepsiscgn-hosted]",
                    f'url = "http://127.0.0.1:{server.server_port}/mcp"',
                    'bearer_token_env_var = "NEPSIS_MCP_CAPABILITY_TOKEN"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        env = {**os.environ, "NEPSIS_MCP_CAPABILITY_TOKEN": token}
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                "--client",
                "codex",
                "--config",
                str(config),
                "--server",
                "nepsiscgn-hosted",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["client"] == "codex"
    assert payload["server"] == "nepsiscgn-hosted"
    assert payload["endpoint"].endswith("/mcp")
    assert payload["initialized"]["name"] == "nepsis-cgn"
    assert payload["tools"]["required_present"] == ["get_routes", "start_operator_packet"]
    assert payload["operator"]["started_schema_id"] == "nepsis.operator_packet"

    assert [request["body"]["method"] for request in requests] == [
        "initialize",
        "tools/list",
        "tools/call",
    ]
    assert requests[0]["authorization"] is None
    assert requests[1]["authorization"] is None
    assert requests[2]["authorization"] == f"Bearer {token}"


def test_mcp_hosted_verifier_requires_codex_bearer_env_var(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        "\n".join(
            [
                "[mcp_servers.nepsiscgn-hosted]",
                'url = "https://example.com/mcp"',
                'bearer_token_env_var = "NEPSIS_MCP_CAPABILITY_TOKEN"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.pop("NEPSIS_MCP_CAPABILITY_TOKEN", None)

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--client",
            "codex",
            "--config",
            str(config),
            "--server",
            "nepsiscgn-hosted",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert "NEPSIS_MCP_CAPABILITY_TOKEN" in result.stderr


def test_mcp_hosted_verifier_reports_missing_codex_server_with_add_command(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("[mcp_servers.playwright]\ncommand = \"npx\"\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--client",
            "codex",
            "--config",
            str(config),
            "--server",
            "nepsiscgn-hosted",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert "server 'nepsiscgn-hosted' not found in Codex config" in result.stderr
    assert "codex mcp add nepsiscgn-hosted --url" in result.stderr
    assert "--bearer-token-env-var NEPSIS_MCP_CAPABILITY_TOKEN" in result.stderr
