#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${NEPSIS_API_BASE_URL:-https://nepsis-cgn-api.vercel.app}"
API_TOKEN="${NEPSIS_API_TOKEN:-}"
MCP_CAPABILITY_TOKEN="${NEPSIS_MCP_CAPABILITY_TOKEN:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" - "$API_BASE_URL" "$API_TOKEN" "$MCP_CAPABILITY_TOKEN" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


base_url = sys.argv[1].rstrip("/")
api_token = sys.argv[2].strip()
mcp_capability_token = sys.argv[3].strip()
failed = False
OPERATOR_V3_ROUTES = {
    "/v1/operator-packet/v3/start",
    "/v1/operator-packet/v3/field",
    "/v1/operator-packet/v3/propose",
    "/v1/operator-packet/v3/lock",
}


def request(
    target: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    bearer_token: str | None = None,
) -> tuple[int, str]:
    data = None
    headers = {"User-Agent": "nepsis-api-smoke/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    url = target if target.startswith(("http://", "https://")) else f"{base_url}{target}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def check(
    target: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    bearer_token: str | None = None,
    expected: set[int] | None = None,
    label: str | None = None,
) -> tuple[int, str]:
    global failed
    expected = expected or {200}
    status, payload = request(target, method=method, body=body, bearer_token=bearer_token)
    ok = status in expected
    print(f"{method:4} {(label or target):34} {status}")
    if not ok:
        failed = True
        print(payload[:500])
    return status, payload


def as_json(label: str, payload: str) -> dict:
    global failed
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        failed = True
        print(f"{label} did not return JSON: {exc}")
        return {}
    if not isinstance(data, dict):
        failed = True
        print(f"{label} JSON response was not an object")
        return {}
    return data


def require(condition: bool, message: str) -> None:
    global failed
    if not condition:
        failed = True
        print(message)


def mcp_jsonrpc(
    method: str,
    request_id: int,
    params: dict | None = None,
    *,
    bearer_token: str | None = None,
) -> dict:
    status, payload = check(
        "/mcp",
        method="POST",
        body={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        bearer_token=bearer_token,
        label=f"/mcp {method}",
    )
    if status != 200:
        return {}
    return as_json(f"/mcp {method}", payload)


def mcp_tool_payload(response: dict, label: str) -> dict:
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    content = result.get("content")
    if not isinstance(content, list) or not content:
        require(False, f"{label} did not return MCP content")
        return {}
    first = content[0]
    if not isinstance(first, dict) or first.get("type") != "text" or not isinstance(first.get("text"), str):
        require(False, f"{label} did not return text content")
        return {}
    return as_json(label, first["text"])


status, payload = check("/v1/health")
if status == 200:
    data = as_json("/v1/health", payload)
    require(data.get("ok") is True, "/v1/health did not report ok=true")

status, payload = check("/v1/routes")
if status == 200:
    data = as_json("/v1/routes", payload)
    routes = data.get("routes")
    route_methods = {
        (route.get("method"), route.get("path"))
        for route in routes
        if isinstance(route, dict)
    } if isinstance(routes, list) else set()
    paths = {path for _, path in route_methods}
    require("/v1/mvp" in paths, "/v1/routes did not include /v1/mvp")
    require("/v1/private-demo" in paths, "/v1/routes did not include /v1/private-demo")
    require("/mcp" in paths, "/v1/routes did not include /mcp")
    for route in sorted(OPERATOR_V3_ROUTES):
        require(("POST", route) in route_methods, f"/v1/routes did not include POST {route}")

private_demo_body = {
    "case_id": "jailing",
    "prompt": (
        "No PHI. Source token is JINGALL and the candidate answer collapses to "
        "JAILING; preserve the mismatch and show the packet audit."
    ),
    "no_phi_acknowledged": True,
    "thread_id": "api-smoke-private-demo",
    "user_id": "api-smoke-private-demo",
}

check("/v1/mvp", method="POST", body={"case_id": "jailing"}, expected={401}, label="/v1/mvp unauth")
check(
    "/v1/private-demo",
    method="POST",
    body=private_demo_body,
    expected={401},
    label="/v1/private-demo unauth",
)

if api_token:
    status, payload = check(
        "/v1/mvp",
        method="POST",
        body={"case_id": "jailing"},
        bearer_token=api_token,
        label="/v1/mvp authenticated",
    )
    if status == 200:
        data = as_json("/v1/mvp authenticated", payload)
        require(data.get("schema_id") == "nepsis.mvp_packet", "/v1/mvp did not return nepsis.mvp_packet")

    status, payload = check(
        "/v1/private-demo",
        method="POST",
        body=private_demo_body,
        bearer_token=api_token,
        expected={200, 503},
        label="/v1/private-demo authenticated",
    )
    data = as_json("/v1/private-demo authenticated", payload)
    if status == 200:
        operator_packet = data.get("operator_packet") if isinstance(data.get("operator_packet"), dict) else {}
        audit_trace = data.get("audit_trace") if isinstance(data.get("audit_trace"), list) else []
        audit_events = [entry.get("event") for entry in audit_trace if isinstance(entry, dict)]
        require(
            data.get("schema_id") == "nepsis.private_demo_runtime_packet",
            "/v1/private-demo did not return nepsis.private_demo_runtime_packet",
        )
        require(data.get("mode") == "external-private-runtime", "/v1/private-demo mode was not external-private-runtime")
        require(operator_packet.get("schema_id") == "nepsis.operator_packet", "/v1/private-demo did not include operator packet")
        require(
            audit_events == ["LOCK_FRAME", "RUN_REPORT", "LOCK_REPORT", "SET_THRESHOLD_DECISION"],
            "/v1/private-demo audit trace did not preserve RED-before-BLUE operator events",
        )
    elif status == 503:
        require(
            data.get("detail") == "Private demo runtime is not configured.",
            "/v1/private-demo misconfiguration did not fail closed with the generic detail",
        )

    for route in sorted(OPERATOR_V3_ROUTES):
        check(
            route,
            method="POST",
            body={},
            bearer_token=api_token,
            expected={400, 422},
            label=f"operator V3 route reachability {route.rsplit('/', 1)[-1]}",
        )

initialized = mcp_jsonrpc("initialize", 101)
init_result = initialized.get("result") if isinstance(initialized.get("result"), dict) else {}
server_info = init_result.get("serverInfo") if isinstance(init_result.get("serverInfo"), dict) else {}
if initialized:
    require(server_info.get("name") == "nepsis-cgn", "/mcp initialize did not report nepsis-cgn")

listed = mcp_jsonrpc("tools/list", 102)
list_result = listed.get("result") if isinstance(listed.get("result"), dict) else {}
tools = list_result.get("tools")
tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)} if isinstance(tools, list) else set()
if listed:
    require({"run_mvp", "get_routes", "start_operator_packet"} <= tool_names, "/mcp tools/list missed expected tools")

rejected = mcp_jsonrpc("tools/call", 103, {"name": "get_routes", "arguments": {}})
error = rejected.get("error") if isinstance(rejected.get("error"), dict) else {}
if rejected:
    require(error.get("code") == -32001, "/mcp tools/call without capability token was not rejected")

if mcp_capability_token:
    started = mcp_jsonrpc(
        "tools/call",
        104,
        {
            "name": "start_operator_packet",
            "arguments": {
                "family": "safety",
                "frame": {
                    "text": "Hosted API smoke packet.",
                    "objective_type": "verify",
                    "domain": "safety",
                    "time_horizon": "short",
                    "rationale_for_change": "Verify authenticated hosted MCP tool call.",
                    "constraints_hard": ["Keep RED before BLUE."],
                    "constraints_soft": ["Keep smoke payload concise."],
                },
                "governance_costs": {"c_fp": 1, "c_fn": 9},
            },
        },
        bearer_token=mcp_capability_token,
    )
    operator_packet = mcp_tool_payload(started, "/mcp start_operator_packet")
    if started:
        require(operator_packet.get("schema_id") == "nepsis.operator_packet", "/mcp start_operator_packet did not return operator packet")

if failed:
    raise SystemExit(1)
PY
