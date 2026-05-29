#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import selectors
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_TOOLS = {
    "run_mvp",
    "get_mvp_schema",
    "health",
    "start_operator_packet",
    "get_session_state",
    "lock_frame",
    "run_report",
    "lock_report",
    "set_threshold_decision",
    "commit_iteration",
}


class VerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class HostServerConfig:
    command: str
    args: list[str]
    cwd: str | None
    env: dict[str, str]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the local NepsisCGN MCP stdio entrypoint by reading a real "
            "Codex, Claude Code, or Gemini CLI host config."
        )
    )
    parser.add_argument("--client", choices=["codex", "claude", "gemini"], required=True)
    parser.add_argument("--config", required=True, help="Path to the host MCP config file.")
    parser.add_argument("--server", default="nepsiscgn", help="MCP server name in the host config.")
    parser.add_argument("--timeout", type=float, default=10.0, help="Seconds to wait for each MCP response.")
    args = parser.parse_args(argv)

    try:
        server_config = load_host_config(args.client, Path(args.config), args.server)
        result = verify_mcp_server(args.client, args.server, server_config, timeout=args.timeout)
    except Exception as exc:
        print(f"mcp-local-verify failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def load_host_config(client: str, path: Path, server: str) -> HostServerConfig:
    if not path.exists():
        raise VerificationError(f"config file not found: {path}")
    if client == "codex":
        with path.open("rb") as handle:
            config = tomllib.load(handle)
        servers = _as_object(config.get("mcp_servers"), "mcp_servers")
        entry_value = servers.get(server)
        if entry_value is None:
            raise VerificationError(_missing_server_message("Codex config", server))
        entry = _as_object(entry_value, f"mcp_servers.{server}")
    else:
        config = json.loads(path.read_text(encoding="utf-8"))
        entry = _json_mcp_server_entry(config, server)

    command = _required_string(entry, "command")
    raw_args = entry.get("args", [])
    if not isinstance(raw_args, list) or not all(isinstance(item, str) for item in raw_args):
        raise VerificationError("server args must be a list of strings")
    raw_env = entry.get("env", {})
    if raw_env is None:
        raw_env = {}
    if not isinstance(raw_env, dict) or not all(isinstance(key, str) for key in raw_env):
        raise VerificationError("server env must be an object with string keys")
    cwd = entry.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise VerificationError("server cwd must be a string when provided")

    return HostServerConfig(
        command=_expand_path(command),
        args=[_expand_value(item) for item in raw_args],
        cwd=_expand_path(cwd) if cwd else None,
        env={key: _expand_value(str(value)) for key, value in raw_env.items()},
    )


def verify_mcp_server(
    client: str,
    server: str,
    server_config: HostServerConfig,
    *,
    timeout: float,
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(server_config.env)
    command = [server_config.command, *server_config.args]
    proc = subprocess.Popen(
        command,
        cwd=server_config.cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        session = JsonRpcSession(proc, timeout=timeout)
        initialized = session.request("initialize", {})
        tools_response = session.request("tools/list", {})
        tools = tools_response.get("tools")
        if not isinstance(tools, list):
            raise VerificationError("tools/list response did not include a tools array")
        tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
        missing_tools = sorted(REQUIRED_TOOLS - tool_names)
        if missing_tools:
            raise VerificationError(f"missing required MCP tools: {', '.join(missing_tools)}")

        health = session.call_tool("health", {})
        if health.get("model_provider_keys_required") is not False:
            raise VerificationError("health tool must report model_provider_keys_required=false")

        mvp = session.call_tool("run_mvp", {"case_id": "jailing"})
        if mvp.get("schema_id") != "nepsis.mvp_packet":
            raise VerificationError("run_mvp did not return a nepsis.mvp_packet")

        started = session.call_tool("start_operator_packet", {})
        state = session.call_tool("get_session_state", {"packet": started})
        locked = session.call_tool(
            "lock_frame",
            {
                "packet": started,
                "family": "safety",
                "frame": _operator_frame(),
                "governance_costs": {"c_fp": 1, "c_fn": 9},
            },
        )
        reported = session.call_tool(
            "run_report",
            {
                "packet": locked,
                "report_text": "obs: critical signal present\nobs: no policy violation",
                "sign": {"critical_signal": True, "policy_violation": False},
                "interpretation": _report_interpretation(),
            },
        )
        report_locked = session.call_tool("lock_report", {"packet": reported})
        threshold = session.call_tool(
            "set_threshold_decision",
            {
                "packet": report_locked,
                "decision": "hold",
                "hold_reason": "Collect one additional discriminator before recommendation.",
            },
        )
        committed = session.call_tool(
            "commit_iteration",
            {
                "packet": threshold,
                "carry_forward_frame": {
                    "text": "Continue escalation assessment after the next discriminator.",
                    "rationale_for_change": "Carry forward held threshold decision.",
                },
            },
        )
    finally:
        proc.terminate()
        try:
            _, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, stderr = proc.communicate(timeout=5)
        if proc.returncode not in {0, -15, None} and stderr.strip():
            raise VerificationError(stderr.strip())

    last_commit = committed.get("last_commit_packet")
    if not isinstance(last_commit, dict):
        raise VerificationError("commit_iteration did not include last_commit_packet")

    return {
        "ok": True,
        "client": client,
        "server": server,
        "command": command,
        "initialized": initialized.get("serverInfo", {}),
        "tools": {
            "count": len(tool_names),
            "required_present": sorted(REQUIRED_TOOLS),
        },
        "health": health,
        "mvp": {
            "schema_id": mvp.get("schema_id"),
            "case_id": mvp.get("case_id"),
            "model_free": True,
        },
        "operator": {
            "started_schema_id": started.get("schema_id"),
            "state_schema_id": state.get("schema_id"),
            "committed_schema_id": committed.get("schema_id"),
            "committed_phase": committed.get("phase"),
            "last_commit_schema_id": last_commit.get("schema_id"),
            "phase_events": last_commit.get("phase_events", []),
        },
    }


class JsonRpcSession:
    def __init__(self, proc: subprocess.Popen[str], *, timeout: float) -> None:
        self._proc = proc
        self._timeout = timeout
        self._next_id = 1
        if proc.stdin is None or proc.stdout is None:
            raise VerificationError("MCP process did not expose stdin/stdout")
        self._stdin = proc.stdin
        self._stdout = proc.stdout
        self._selector = selectors.DefaultSelector()
        self._selector.register(self._stdout, selectors.EVENT_READ)

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self._stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self._stdin.flush()
        response = self._read_response()
        if response.get("id") != request_id:
            raise VerificationError(f"unexpected JSON-RPC id: {response.get('id')!r}")
        if "error" in response:
            raise VerificationError(f"{method} failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise VerificationError(f"{method} result was not an object")
        return result

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError") is True:
            raise VerificationError(f"{name} returned MCP isError=true: {_tool_payload(result)}")
        return _tool_payload(result)

    def _read_response(self) -> dict[str, Any]:
        events = self._selector.select(self._timeout)
        if not events:
            raise VerificationError(f"timed out waiting {self._timeout}s for MCP response")
        line = self._stdout.readline()
        if not line:
            raise VerificationError("MCP process exited before responding")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise VerificationError(f"MCP response was not JSON: {line!r}") from exc
        if not isinstance(response, dict):
            raise VerificationError("MCP response was not an object")
        return response


def _json_mcp_server_entry(config: Any, server: str) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise VerificationError("JSON config root must be an object")
    servers = config.get("mcpServers")
    if isinstance(servers, dict) and isinstance(servers.get(server), dict):
        return servers[server]

    projects = config.get("projects")
    if isinstance(projects, dict):
        for project_config in projects.values():
            if not isinstance(project_config, dict):
                continue
            project_servers = project_config.get("mcpServers")
            if isinstance(project_servers, dict) and isinstance(project_servers.get(server), dict):
                return project_servers[server]

    raise VerificationError(_missing_server_message("JSON MCP config", server))


def _tool_payload(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("content")
    if not isinstance(content, list) or not content:
        raise VerificationError("MCP tool result did not include content")
    first = content[0]
    if not isinstance(first, dict) or first.get("type") != "text":
        raise VerificationError("MCP tool result first content item was not text")
    text = first.get("text")
    if not isinstance(text, str):
        raise VerificationError("MCP tool result text was not a string")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise VerificationError("MCP tool payload was not an object")
    return payload


def _operator_frame() -> dict[str, Any]:
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


def _report_interpretation() -> dict[str, Any]:
    return {
        "report_text": "obs: critical signal present\nobs: no policy violation",
        "evidence_count": 2,
        "report_synced": True,
        "contradictions_status": "none_identified",
        "contradictions_note": "",
        "contradiction_density": 0.0,
    }


def _as_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationError(f"{name} must be an object")
    return value


def _required_string(value: dict[str, Any], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise VerificationError(f"server {name} must be a non-empty string")
    return item


def _expand_path(value: str) -> str:
    return os.path.expanduser(os.path.expandvars(value))


def _expand_value(value: str) -> str:
    return os.path.expandvars(value)


def _missing_server_message(config_label: str, server: str) -> str:
    documented_command = Path("/Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp")
    local_command = Path(__file__).resolve().parents[1] / ".venv" / "bin" / "nepsiscgn-mcp"
    local_hint = ""
    if local_command != documented_command:
        local_hint = f" Current checkout command: codex mcp add {server} -- {local_command}"
    return (
        f"server {server!r} not found in {config_label}. "
        f"For Codex, add it with: codex mcp add {server} -- {documented_command}.{local_hint}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
