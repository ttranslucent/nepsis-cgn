from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "local-mcp-harness.md"
CODEX_DEMO_DOC = ROOT / "docs" / "codex-local-mcp-demo.md"
CODEX_DEMO_SCRIPT = ROOT / "scripts" / "codex-mcp-demo.sh"
VERIFIER = ROOT / "scripts" / "mcp-local-verify.py"
REQUIRED_LOCAL_MCP_TOOLS = [
    "commit_iteration",
    "get_mvp_schema",
    "get_session_state",
    "health",
    "lock_frame",
    "lock_report",
    "run_mvp",
    "run_report",
    "set_threshold_decision",
    "start_operator_packet",
]


def test_local_mcp_harness_docs_include_copy_paste_host_configs() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "~/.codex/config.toml" in text
    assert "codex mcp add nepsiscgn -- /Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp" in text
    assert "[mcp_servers.nepsiscgn]" in text
    assert 'command = "/Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp"' in text
    assert 'cwd = "/Users/trentthorn/Code/nepsiscgn"' in text
    assert 'command = "/Users/trentthorn/Code/nepsiscgn/.venv/bin/python"' in text
    assert 'args = ["-m", "nepsis_cgn.mcp.stdio"]' in text
    assert 'PYTHONPATH = "/Users/trentthorn/Code/nepsiscgn/src"' in text

    assert ".mcp.json" in text
    assert 'claude mcp add --transport stdio --scope project nepsiscgn -- /Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp' in text
    assert '"mcpServers"' in text
    assert '"/Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp"' in text

    assert "~/.gemini/settings.json" in text
    assert '"nepsiscgn"' in text
    assert '"timeout": 30000' in text

    assert "ChatGPT web does not run local stdio MCP servers" in text
    assert "/mvp remains deterministic and model-free" in text
    assert "nepsiscgn-mcp" in text


def test_mcp_local_verifier_is_valid_python() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(VERIFIER)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_codex_mcp_demo_runbook_is_copy_pasteable() -> None:
    text = CODEX_DEMO_DOC.read_text(encoding="utf-8")
    script = CODEX_DEMO_SCRIPT.read_text(encoding="utf-8")

    assert "Codex Local MCP Demo" in text
    assert "scripts/mvp-local.sh" in text
    assert "NEPSIS_SITE_BASE_URL=http://127.0.0.1:3000 scripts/codex-mcp-demo.sh" in text
    assert "/api/status" in text
    assert 'scripts/mcp-local-verify.py --client codex --config "$CODEX_CONFIG" --server "$SERVER"' in text
    assert "run_mvp" in text
    assert "start_operator_packet" in text
    assert "codex mcp add nepsiscgn -- /Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp" in text
    assert "Use only the NepsisCGN MCP server named nepsiscgn" in text
    assert "/mvp remains deterministic and model-free" in text

    assert "scripts/mcp-local-verify.py" in script
    assert '--config "$CODEX_CONFIG"' in script
    assert '--server "$SERVER"' in script
    assert "NEPSIS_SITE_BASE_URL" in script
    assert "/api/status" in script
    assert 'args = ["-m", "nepsis_cgn.mcp.stdio"]' in script
    assert "run_mvp" in script
    assert "start_operator_packet" in script

    result = subprocess.run(
        ["bash", "-n", str(CODEX_DEMO_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_mcp_local_verifier_accepts_real_host_configs(tmp_path: Path) -> None:
    wrapper = _write_nepsiscgn_mcp_wrapper(tmp_path)
    cases = {
        "codex": _write_codex_config(tmp_path, wrapper),
        "claude": _write_claude_config(tmp_path, wrapper),
        "gemini": _write_gemini_config(tmp_path, wrapper),
    }

    for client, config in cases.items():
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                "--client",
                client,
                "--config",
                str(config),
                "--server",
                "nepsiscgn",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["client"] == client
        assert payload["server"] == "nepsiscgn"
        assert payload["mvp"]["schema_id"] == "nepsis.mvp_packet"
        assert payload["operator"]["started_schema_id"] == "nepsis.operator_packet"
        assert payload["operator"]["committed_schema_id"] == "nepsis.operator_packet"
        assert payload["operator"]["last_commit_schema_id"] == "nepsis.operator_audit_packet"
        assert payload["operator"]["phase_events"] == [
            "LOCK_FRAME",
            "RUN_REPORT",
            "LOCK_REPORT",
            "SET_THRESHOLD_DECISION",
            "COMMIT_ITERATION",
        ]
        assert not (tmp_path / "mcp-sessions.json").exists()


def test_mcp_local_verifier_validates_codex_fixture_stdio_entrypoint(tmp_path: Path) -> None:
    store_path = tmp_path / "mcp-sessions.json"
    config = _write_codex_stdio_config(tmp_path, store_path)

    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--client",
            "codex",
            "--config",
            str(config),
            "--server",
            "nepsiscgn",
            "--timeout",
            "5",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["client"] == "codex"
    assert payload["server"] == "nepsiscgn"
    assert payload["command"] == [sys.executable, "-m", "nepsis_cgn.mcp.stdio"]
    assert payload["initialized"]["name"] == "nepsis-cgn-local"
    assert payload["tools"]["required_present"] == REQUIRED_LOCAL_MCP_TOOLS
    assert payload["tools"]["count"] >= len(REQUIRED_LOCAL_MCP_TOOLS)
    assert payload["health"]["model_provider_keys_required"] is False
    assert payload["mvp"] == {
        "schema_id": "nepsis.mvp_packet",
        "case_id": "jailing",
        "model_free": True,
    }
    assert payload["operator"]["started_schema_id"] == "nepsis.operator_packet"
    assert payload["operator"]["state_schema_id"] == "nepsis.operator_packet_state"
    assert payload["operator"]["committed_schema_id"] == "nepsis.operator_packet"
    assert payload["operator"]["committed_phase"] == "frame_draft"
    assert payload["operator"]["last_commit_schema_id"] == "nepsis.operator_audit_packet"
    assert payload["operator"]["phase_events"] == [
        "LOCK_FRAME",
        "RUN_REPORT",
        "LOCK_REPORT",
        "SET_THRESHOLD_DECISION",
        "COMMIT_ITERATION",
    ]
    assert not store_path.exists()


def test_mcp_local_verifier_reports_missing_codex_server_with_add_command(tmp_path: Path) -> None:
    config = tmp_path / "codex-config.toml"
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
            "nepsiscgn",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "server 'nepsiscgn' not found in Codex config" in result.stderr
    assert "codex mcp add nepsiscgn -- /Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp" in result.stderr
    assert 'args = ["-m", "nepsis_cgn.mcp.stdio"]' in result.stderr


def _write_nepsiscgn_mcp_wrapper(tmp_path: Path) -> Path:
    wrapper = tmp_path / "nepsiscgn-mcp"
    wrapper.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                f"export PYTHONPATH={ROOT / 'src'}",
                f"export NEPSIS_API_STORE_PATH={tmp_path / 'mcp-sessions.json'}",
                f"exec {sys.executable} -m nepsis_cgn.mcp.stdio",
                "",
            ]
        ),
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    return wrapper


def _write_codex_config(tmp_path: Path, wrapper: Path) -> Path:
    config = tmp_path / "codex-config.toml"
    config.write_text(
        "\n".join(
            [
                "[mcp_servers.nepsiscgn]",
                f'command = "{wrapper}"',
                'args = []',
                f'cwd = "{ROOT}"',
                "startup_timeout_sec = 10",
                "tool_timeout_sec = 30",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config


def _write_codex_stdio_config(tmp_path: Path, store_path: Path) -> Path:
    config = tmp_path / "codex-stdio-config.toml"
    config.write_text(
        "\n".join(
            [
                "[mcp_servers.nepsiscgn]",
                f"command = {json.dumps(sys.executable)}",
                'args = ["-m", "nepsis_cgn.mcp.stdio"]',
                f"cwd = {json.dumps(str(ROOT))}",
                "startup_timeout_sec = 10",
                "tool_timeout_sec = 30",
                "",
                "[mcp_servers.nepsiscgn.env]",
                f"PYTHONPATH = {json.dumps(str(ROOT / 'src'))}",
                f"NEPSIS_API_STORE_PATH = {json.dumps(str(store_path))}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config


def _write_claude_config(tmp_path: Path, wrapper: Path) -> Path:
    config = tmp_path / ".mcp.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "nepsiscgn": {
                        "command": str(wrapper),
                        "args": [],
                        "env": {"PYTHONPATH": str(ROOT / "src")},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return config


def _write_gemini_config(tmp_path: Path, wrapper: Path) -> Path:
    config = tmp_path / "settings.json"
    config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "nepsiscgn": {
                        "command": str(wrapper),
                        "args": [],
                        "cwd": str(ROOT),
                        "env": {"PYTHONPATH": str(ROOT / "src")},
                        "timeout": 30000,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return config
