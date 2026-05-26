#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_TOOLS = {"get_routes", "start_operator_packet"}


class VerificationError(RuntimeError):
    pass


@dataclass(frozen=True)
class HostedServerConfig:
    url: str
    bearer_token_env_var: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a hosted NepsisCGN streamable-HTTP MCP endpoint using a "
            "real Codex MCP server config."
        )
    )
    parser.add_argument("--client", choices=["codex"], required=True)
    parser.add_argument("--config", required=True, help="Path to the Codex config.toml file.")
    parser.add_argument("--server", default="nepsiscgn-hosted", help="MCP server name in the Codex config.")
    parser.add_argument("--timeout", type=float, default=20.0, help="Seconds to wait for each HTTP response.")
    parser.add_argument(
        "--family",
        choices=["puzzle", "clinical", "safety"],
        default="safety",
        help="Operator packet family for the authenticated start_operator_packet call.",
    )
    args = parser.parse_args(argv)

    try:
        server_config = load_codex_hosted_config(Path(args.config), args.server)
        token = _required_secret_env(server_config.bearer_token_env_var)
        result = verify_hosted_mcp(
            args.client,
            args.server,
            server_config,
            token=token,
            timeout=args.timeout,
            family=args.family,
        )
    except Exception as exc:
        print(f"mcp-hosted-verify failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def load_codex_hosted_config(path: Path, server: str) -> HostedServerConfig:
    if not path.exists():
        raise VerificationError(f"config file not found: {path}")
    with path.open("rb") as handle:
        config = tomllib.load(handle)
    servers = _as_object(config.get("mcp_servers"), "mcp_servers")
    entry = _as_object(servers.get(server), f"mcp_servers.{server}")
    url = _required_string(entry, "url")
    bearer_token_env_var = _required_string(entry, "bearer_token_env_var")
    if "command" in entry:
        raise VerificationError("hosted verifier expects a Codex streamable-HTTP MCP server, not stdio command")
    if not url.startswith(("http://", "https://")):
        raise VerificationError("server url must start with http:// or https://")
    return HostedServerConfig(url=url, bearer_token_env_var=bearer_token_env_var)


def verify_hosted_mcp(
    client: str,
    server: str,
    server_config: HostedServerConfig,
    *,
    token: str,
    timeout: float,
    family: str,
) -> dict[str, Any]:
    session = HostedJsonRpcSession(server_config.url, timeout=timeout)

    initialized = session.request("initialize", {}, request_id=1)
    init_result = _as_object(initialized.get("result"), "initialize.result")
    server_info = _as_object(init_result.get("serverInfo"), "initialize.result.serverInfo")
    if server_info.get("name") != "nepsis-cgn":
        raise VerificationError("initialize did not report serverInfo.name=nepsis-cgn")

    listed = session.request("tools/list", {}, request_id=2)
    list_result = _as_object(listed.get("result"), "tools/list.result")
    tools = list_result.get("tools")
    if not isinstance(tools, list):
        raise VerificationError("tools/list response did not include a tools array")
    tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
    missing = sorted(REQUIRED_TOOLS - tool_names)
    if missing:
        raise VerificationError(f"missing required hosted MCP tools: {', '.join(missing)}")

    called = session.request(
        "tools/call",
        {
            "name": "start_operator_packet",
            "arguments": {
                "family": family,
                "frame": {
                    "text": "Hosted MCP verification packet.",
                    "objective_type": "verify",
                    "domain": "safety",
                    "time_horizon": "short",
                    "rationale_for_change": "Verify authenticated hosted MCP packet start.",
                    "constraints_hard": ["Keep RED before BLUE."],
                    "constraints_soft": ["Keep verification payload concise."],
                },
                "governance_costs": {"c_fp": 1, "c_fn": 9},
            },
        },
        request_id=3,
        bearer_token=token,
    )
    operator_packet = _tool_payload(called)
    if operator_packet.get("schema_id") != "nepsis.operator_packet":
        raise VerificationError("start_operator_packet did not return nepsis.operator_packet")

    return {
        "ok": True,
        "client": client,
        "server": server,
        "endpoint": server_config.url,
        "initialized": server_info,
        "tools": {
            "count": len(tool_names),
            "required_present": sorted(REQUIRED_TOOLS),
        },
        "operator": {
            "started_schema_id": operator_packet.get("schema_id"),
            "started_phase": operator_packet.get("phase"),
            "legal_next_tools": operator_packet.get("legal_next_tools"),
        },
    }


class HostedJsonRpcSession:
    def __init__(self, url: str, *, timeout: float) -> None:
        self._url = url
        self._timeout = timeout

    def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        request_id: int,
        bearer_token: str | None = None,
    ) -> dict[str, Any]:
        body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "nepsis-mcp-hosted-verify/1.0",
        }
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"

        request = urllib.request.Request(
            self._url,
            data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                payload = response.read().decode("utf-8", errors="replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            raise VerificationError(f"{method} returned HTTP {exc.code}: {payload[:500]}") from exc
        except urllib.error.URLError as exc:
            raise VerificationError(f"{method} request failed: {exc}") from exc

        if status != 200:
            raise VerificationError(f"{method} returned HTTP {status}: {payload[:500]}")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise VerificationError(f"{method} did not return JSON: {payload[:500]}") from exc
        if not isinstance(data, dict):
            raise VerificationError(f"{method} JSON-RPC response must be an object")
        if data.get("id") != request_id:
            raise VerificationError(f"{method} returned unexpected JSON-RPC id: {data.get('id')!r}")
        if "error" in data:
            error = data.get("error")
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise VerificationError(f"{method} returned JSON-RPC error: {message}")
        return data


def _tool_payload(response: dict[str, Any]) -> dict[str, Any]:
    result = _as_object(response.get("result"), "tools/call.result")
    content = result.get("content")
    if not isinstance(content, list) or not content:
        raise VerificationError("tools/call result did not include content")
    first = content[0]
    if not isinstance(first, dict) or first.get("type") != "text":
        raise VerificationError("tools/call first content item must be text")
    text = first.get("text")
    if not isinstance(text, str):
        raise VerificationError("tools/call text content must be a string")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise VerificationError("tools/call text content was not JSON") from exc
    if not isinstance(payload, dict):
        raise VerificationError("tools/call JSON payload must be an object")
    return payload


def _required_secret_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise VerificationError(f"required bearer token env var is not set: {name}")
    return value.strip()


def _as_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise VerificationError(f"{name} must be an object")
    return value


def _required_string(entry: dict[str, Any], name: str) -> str:
    value = entry.get(name)
    if not isinstance(value, str) or not value.strip():
        raise VerificationError(f"server config requires string field '{name}'")
    return value.strip()


if __name__ == "__main__":
    raise SystemExit(main())
