#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${NEPSIS_SITE_BASE_URL:-https://nepsis-cgn.vercel.app}"
MCP_ENDPOINT="${NEPSIS_MCP_ENDPOINT:-}"
MCP_CAPABILITY_TOKEN="${NEPSIS_MCP_CAPABILITY_TOKEN:-}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" - "$BASE_URL" "$MCP_ENDPOINT" "$MCP_CAPABILITY_TOKEN" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


base_url = sys.argv[1].rstrip("/")
mcp_endpoint_override = sys.argv[2].strip()
mcp_capability_token = sys.argv[3].strip()


def request(
    target: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    data = None
    headers = {"User-Agent": "nepsis-site-smoke/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if extra_headers:
        headers.update(extra_headers)
    url = target if target.startswith(("http://", "https://")) else f"{base_url}{target}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


failed = False


def check(
    target: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
    expected: set[int] | None = None,
    label: str | None = None,
) -> tuple[int, str]:
    global failed
    expected = expected or {200}
    status, payload = request(target, method=method, body=body, extra_headers=extra_headers)
    ok = status in expected
    print(f"{method:4} {(label or target):34} {status}")
    if not ok:
        failed = True
        print(payload[:500])
    return status, payload


def as_json(path: str, payload: str) -> dict:
    global failed
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        failed = True
        print(f"{path} did not return JSON: {exc}")
        return {}
    if not isinstance(data, dict):
        failed = True
        print(f"{path} JSON response was not an object")
        return {}
    return data


def require_bool(data: dict, name: str, expected: bool, message: str) -> None:
    global failed
    if data.get(name) is not expected:
        failed = True
        print(message)


def has_all_strings(value: object, required: set[str]) -> bool:
    return isinstance(value, list) and required <= {item for item in value if isinstance(item, str)}


def mcp_tool_payload(response: dict, label: str) -> dict:
    global failed
    result = response.get("result") if isinstance(response.get("result"), dict) else {}
    content = result.get("content")
    if not isinstance(content, list) or not content:
        failed = True
        print(f"{label} did not return MCP content")
        return {}
    first = content[0]
    if not isinstance(first, dict) or first.get("type") != "text" or not isinstance(first.get("text"), str):
        failed = True
        print(f"{label} did not return text content")
        return {}
    return as_json(label, first["text"])


def mcp_jsonrpc(
    endpoint: str,
    method: str,
    request_id: int,
    params: dict | None = None,
    *,
    bearer_token: str | None = None,
) -> dict:
    extra_headers = {"Authorization": f"Bearer {bearer_token}"} if bearer_token else None
    status, payload = check(
        endpoint,
        method="POST",
        body={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        extra_headers=extra_headers,
        label=f"/mcp {method}",
    )
    if status != 200:
        return {}
    return as_json(f"/mcp {method}", payload)


mcp_endpoint = mcp_endpoint_override

check("/")
check("/mvp")
check("/login")
check("/engine")
check("/operator")

status_code, payload = check("/api/status")
if status_code == 200:
    data = as_json("/api/status", payload)
    mvp = data.get("mvp") if isinstance(data.get("mvp"), dict) else {}
    auth = data.get("auth") if isinstance(data.get("auth"), dict) else {}
    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    operator = data.get("operator") if isinstance(data.get("operator"), dict) else {}
    mcp = data.get("mcp") if isinstance(data.get("mcp"), dict) else {}
    setup = data.get("setup") if isinstance(data.get("setup"), dict) else {}
    hosted_mcp = mcp.get("hosted") if isinstance(mcp.get("hosted"), dict) else {}
    public_setup = setup.get("publicSite") if isinstance(setup.get("publicSite"), dict) else {}
    operator_setup = setup.get("operatorMode") if isinstance(setup.get("operatorMode"), dict) else {}
    if mvp.get("schemaId") != "nepsis.mvp_packet" or not mvp.get("available"):
        failed = True
        print("/api/status did not report the frozen MVP as available")
    require_bool(mvp, "noLoginRequired", True, "/api/status did not report no-login MVP access")
    require_bool(
        auth,
        "previewCodesEnabled",
        False,
        "/api/status did not report disabled public preview codes",
    )
    if auth.get("emailConfigured") is False and auth.get("operatorLoginReady") is not False:
        failed = True
        print("/api/status reported operator login ready without email delivery")
    if models.get("enabled") is not False or models.get("hasServerOpenAiKey") is not False:
        failed = True
        print("/api/status did not report model routes disabled without server provider keys")
    if operator.get("enabled") not in {False, None}:
        failed = True
        print("/api/status unexpectedly reported live operator enabled on the public site")
    require_bool(
        public_setup,
        "ready",
        True,
        "/api/status did not report the public-site setup path as ready",
    )
    if public_setup.get("envExample") != "nepsis-web/.env.public.example":
        failed = True
        print("/api/status did not point public setup at nepsis-web/.env.public.example")
    if operator_setup.get("ready") is not False:
        failed = True
        print("/api/status did not keep private operator setup unready on the public site")
    if operator_setup.get("envExample") != "nepsis-web/.env.operator.example":
        failed = True
        print("/api/status did not point operator setup at nepsis-web/.env.operator.example")
    if not has_all_strings(mcp.get("discoverableMethods"), {"initialize", "tools/list"}):
        failed = True
        print("/api/status did not report public MCP discovery methods")
    if not has_all_strings(mcp.get("protectedTools"), {"run_mvp", "get_routes", "start_operator_packet"}):
        failed = True
        print("/api/status did not report protected hosted MCP tools")
    require_bool(
        hosted_mcp,
        "requiresBackendAuth",
        False,
        "/api/status reported backend auth on hosted MCP discovery",
    )
    require_bool(
        hosted_mcp,
        "requiresCapabilityToken",
        True,
        "/api/status did not report capability-token MCP tool calls",
    )
    require_bool(
        hosted_mcp,
        "modelKeysRequired",
        False,
        "/api/status reported MCP server model-key requirements",
    )
    if hosted_mcp.get("available") is False and hosted_mcp.get("deferred") is not True:
        failed = True
        print("/api/status reported hosted MCP unavailable without deferred posture")
    if hosted_mcp.get("available") is True and not (
        isinstance(hosted_mcp.get("endpoint"), str) and hosted_mcp.get("endpoint").strip()
    ):
        failed = True
        print("/api/status reported hosted MCP available without an endpoint")
    if not mcp_endpoint:
        endpoint = hosted_mcp.get("endpoint") or mcp.get("endpoint")
        if isinstance(endpoint, str) and endpoint.strip():
            mcp_endpoint = endpoint.strip()

status_code, payload = check("/api/auth/session")
if status_code == 200:
    data = as_json("/api/auth/session", payload)
    if data.get("authenticated") is not False:
        failed = True
        print("/api/auth/session unexpectedly reported an authenticated visitor")
    if data.get("engineControlAllowed") is not False:
        failed = True
        print("/api/auth/session unexpectedly allowed anonymous engine controls")

status_code, payload = check("/api/playground-nepsis")
if status_code == 200:
    data = as_json("/api/playground-nepsis", payload)
    if data.get("modelRoutesEnabled") is not False:
        failed = True
        print("/api/playground-nepsis did not report disabled model routes")
    if data.get("hasServerKey") is not False:
        failed = True
        print("/api/playground-nepsis reported a server provider key on the public site")

check("/api/playground-nepsis", method="POST", body={"prompt": "smoke", "packId": "jailing_jingall"}, expected={403})
check("/api/run-with-nepsis", method="POST", body={"prompt": "smoke"}, expected={403})
check("/api/operator/model", method="POST", body={"mode": "draft_frame", "input": "smoke"}, expected={401, 403})
check("/api/engine/health")

if mcp_endpoint:
    initialized = mcp_jsonrpc(mcp_endpoint, "initialize", 101)
    init_result = initialized.get("result") if isinstance(initialized.get("result"), dict) else {}
    server_info = init_result.get("serverInfo") if isinstance(init_result.get("serverInfo"), dict) else {}
    if initialized and server_info.get("name") != "nepsis-cgn":
        failed = True
        print("/mcp initialize did not report the hosted nepsis-cgn server")

    listed = mcp_jsonrpc(mcp_endpoint, "tools/list", 102)
    list_result = listed.get("result") if isinstance(listed.get("result"), dict) else {}
    tools = list_result.get("tools")
    tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)} if isinstance(tools, list) else set()
    if listed and {"run_mvp", "get_routes", "start_operator_packet"} - tool_names:
        failed = True
        print("/mcp tools/list did not expose the expected hosted MCP tools")

    rejected = mcp_jsonrpc(
        mcp_endpoint,
        "tools/call",
        103,
        {"name": "get_routes", "arguments": {}},
    )
    error = rejected.get("error") if isinstance(rejected.get("error"), dict) else {}
    if rejected and error.get("code") != -32001:
        failed = True
        print("/mcp tools/call without a capability token was not rejected")

    if mcp_capability_token:
        started = mcp_jsonrpc(
            mcp_endpoint,
            "tools/call",
            104,
            {
                "name": "start_operator_packet",
                "arguments": {
                    "family": "safety",
                    "frame": {
                        "text": "Public deployment MCP smoke packet.",
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
        if started and operator_packet.get("schema_id") != "nepsis.operator_packet":
            failed = True
            print("/mcp authenticated start_operator_packet did not return nepsis.operator_packet")

status_code, payload = check("/api/engine/mvp", method="POST", body={"case_id": "jailing"})
if status_code == 200 and "nepsis.mvp_packet" not in payload:
    failed = True
    print("MVP response did not include nepsis.mvp_packet")

if failed:
    raise SystemExit(1)
PY
