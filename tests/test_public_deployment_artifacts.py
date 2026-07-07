from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPERATOR_PACKET_PROXY_ROUTES = [
    "start",
    "state",
    "frame",
    "report",
    "report/lock",
    "threshold",
    "commit",
    "abandon",
]


def _env_assignments(path: Path) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        assignments[name.strip()] = value.strip().strip("\"'")
    return assignments


def test_web_env_examples_separate_public_site_and_operator_mode() -> None:
    public_env = ROOT / "nepsis-web" / ".env.public.example"
    operator_env = ROOT / "nepsis-web" / ".env.operator.example"

    assert public_env.exists()
    assert operator_env.exists()
    gitignore = (ROOT / "nepsis-web" / ".gitignore").read_text(encoding="utf-8")
    assert "!.env.public.example" in gitignore
    assert "!.env.operator.example" in gitignore

    public = _env_assignments(public_env)
    operator = _env_assignments(operator_env)

    assert public["NEXT_PUBLIC_NEPSIS_PUBLIC_SITE"] == "true"
    assert public["NEPSIS_MODEL_ROUTES_ENABLED"] == "false"
    assert public["NEPSIS_API_BASE_URL"] == "https://nepsis-cgn-api.vercel.app"
    assert public["NEPSIS_ENGINE_ALLOW_ANON"] == "false"
    assert public["NEPSIS_AUTH_ALLOW_CODE_PREVIEW"] == "false"
    assert public.get("NEPSIS_AUTH_ALLOWED_EMAILS", "") == ""
    assert public.get("NEPSIS_AUTH_SESSION_REVOKE_BEFORE", "") == ""
    assert public.get("NEPSIS_DEPLOYMENT_MODE", "") != "operator"
    assert public.get("NEXT_PUBLIC_NEPSIS_OPERATOR_SITE", "") != "true"
    assert public.get("NEPSIS_LIVE_OPERATOR_ENABLED", "") != "true"
    assert public.get("OPENAI_API_KEY", "") == ""
    assert public.get("NEPSIS_OPENAI_API_KEY", "") == ""
    assert public.get("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", "") == ""

    assert operator["NEXT_PUBLIC_NEPSIS_PUBLIC_SITE"] == "false"
    assert operator["NEPSIS_DEPLOYMENT_MODE"] == "operator"
    assert operator["NEXT_PUBLIC_NEPSIS_OPERATOR_SITE"] == "true"
    assert operator["NEPSIS_LIVE_OPERATOR_ENABLED"] == "true"
    assert operator["NEPSIS_MODEL_ROUTES_ENABLED"] == "true"
    assert operator["NEPSIS_API_BASE_URL"] == "https://nepsis-cgn-api.vercel.app"
    assert operator["NEPSIS_ENGINE_ALLOW_ANON"] == "false"
    assert operator["NEPSIS_AUTH_ALLOW_CODE_PREVIEW"] == "false"
    assert operator["NEPSIS_AUTH_ALLOWED_EMAILS"]
    assert operator.get("NEPSIS_AUTH_SESSION_REVOKE_BEFORE", "") == ""
    assert operator["NEPSIS_AUTH_SECRET"]
    assert operator["RESEND_API_KEY"]
    assert operator["NEPSIS_AUTH_FROM_EMAIL"]
    assert operator["OPENAI_API_KEY"]
    assert operator["NEPSIS_V3_PACKET_SEAL_SECRET"]
    assert operator["NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET"]


def test_web_env_examples_are_linked_from_docs() -> None:
    public_example = "nepsis-web/.env.public.example"
    operator_example = "nepsis-web/.env.operator.example"
    sources = [
        ROOT / "README.md",
        ROOT / "nepsis-web" / "README.md",
        ROOT / "docs" / "public-api.md",
        ROOT / "docs" / "operator-runbook.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in sources)

    assert public_example in combined
    assert operator_example in combined
    assert "https://nepsis-cgn-api.vercel.app" in combined
    assert "scripts/api-smoke.sh" in combined
    assert "Public site setup" in combined
    assert "Private operator deployment" in combined


def test_public_mvp_page_declares_v04_deterministic_triad() -> None:
    page = (ROOT / "nepsis-web" / "src" / "app" / "mvp" / "page.tsx").read_text(
        encoding="utf-8"
    )
    fallback = (ROOT / "nepsis-web" / "src" / "lib" / "mvpFallback.ts").read_text(
        encoding="utf-8"
    )

    assert "Public MVP v0.4" in page
    assert "Deterministic packet proof" in page
    assert "Model-free deterministic run; no login or API key required." in page
    assert 'id: "jailing"' in page
    assert 'id: "sea_ivdu"' in page
    assert 'id: "wirecard"' in page
    assert 'id: "clinical"' not in page
    assert "live model" not in page.lower()
    assert "bundled frozen v0.4 packet" in fallback


def test_status_api_exposes_public_and_operator_readiness_paths() -> None:
    route = ROOT / "nepsis-web" / "src" / "app" / "api" / "status" / "route.ts"
    text = route.read_text(encoding="utf-8")

    assert "setup" in text
    assert "publicSite" in text
    assert "operatorMode" in text
    assert "nepsis-web/.env.public.example" in text
    assert "nepsis-web/.env.operator.example" in text
    assert "docs/public-api.md#public-site-setup" in text
    assert "docs/operator-runbook.md#private-operator-deployment" in text
    assert "NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true" in text
    assert "NEPSIS_DEPLOYMENT_MODE=operator" in text
    assert "RESEND_API_KEY" in text
    assert "OPENAI_API_KEY or NEPSIS_OPENAI_API_KEY" in text


def test_status_api_exposes_provider_access_custody_boundary() -> None:
    route = ROOT / "nepsis-web" / "src" / "app" / "api" / "status" / "route.ts"
    page = ROOT / "nepsis-web" / "src" / "app" / "status" / "page.tsx"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in [route, page])

    assert "providerAccess" in combined
    assert "userProviderKeysAccepted: false" in route.read_text(encoding="utf-8")
    assert "server-side-operator-or-mcp-host" in combined
    assert "approved users sign in" in combined.lower()
    assert "Supabase OTP" in combined


def test_operator_login_supports_supabase_otp_without_replacing_local_session() -> None:
    package = json.loads((ROOT / "nepsis-web" / "package.json").read_text(encoding="utf-8"))
    auth_helper = (ROOT / "nepsis-web" / "src" / "lib" / "nepsisAuth.ts").read_text(
        encoding="utf-8"
    )
    request_route = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "auth" / "request-code" / "route.ts"
    ).read_text(encoding="utf-8")
    verify_route = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "auth" / "verify-code" / "route.ts"
    ).read_text(encoding="utf-8")
    status_route = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "status" / "route.ts"
    ).read_text(encoding="utf-8")
    operator_env = (ROOT / "nepsis-web" / ".env.operator.example").read_text(
        encoding="utf-8"
    )

    assert "@supabase/supabase-js" in package["dependencies"]
    assert "NEXT_PUBLIC_SUPABASE_URL" in auth_helper
    assert "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY" in auth_helper
    assert "NEXT_PUBLIC_SUPABASE_ANON_KEY" in auth_helper
    assert "supabaseOtpConfigured" in auth_helper
    assert "signInWithOtp" in auth_helper
    assert "shouldCreateUser: false" in auth_helper
    assert "normalizeLoginCode" in auth_helper
    assert 'verifyOtp({ email, token: normalizedCode, type: "email" })' in auth_helper
    assert "replaced by a newer email" in auth_helper
    assert "NEPSIS_SUPABASE_OTP_SENT_COOKIE" in auth_helper
    assert "createSupabaseOtpPending" in auth_helper
    assert "readSupabaseOtpPendingFromCookieValue" in auth_helper
    assert "requestSupabaseLoginCode" in request_route
    assert "loginEmailConfigured()" in request_route
    assert "reusedExistingCode: true" in request_route
    assert "forceNewCode" in request_route
    assert "allowCodeEntry: delivery.status === 429" in request_route
    assert "verifySupabaseLoginCode" in verify_route
    assert "NEPSIS_SUPABASE_OTP_SENT_COOKIE" in verify_route
    assert "createLoginSession" in verify_route
    assert "createCsrfToken" in verify_route
    assert "NEPSIS_USER_COOKIE" in verify_route
    assert "NEPSIS_CSRF_COOKIE" in verify_route
    assert "supabaseOtpConfigured" in status_route
    assert "NEXT_PUBLIC_SUPABASE_URL" in operator_env
    assert "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY" in operator_env


def test_browser_provider_key_storage_is_removed_from_web_runtime() -> None:
    src = ROOT / "nepsis-web" / "src"
    files = [
        src / "lib" / "clientStorage.ts",
        src / "lib" / "publicMode.ts",
        src / "app" / "page.tsx",
        src / "app" / "settings" / "page.tsx",
        src / "app" / "playground" / "page.tsx",
        src / "app" / "engine" / "page.tsx",
        src / "app" / "api" / "playground-nepsis" / "route.ts",
        src / "app" / "api" / "run-with-nepsis" / "route.ts",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "browserModelKeysAllowed" not in combined
    assert "getStoredOpenAiKey" not in combined
    assert "hasStoredOpenAiKey" not in combined
    assert "localStorage.setItem(OPENAI_KEY_STORAGE_KEY" not in combined
    assert "OPENAI_KEY_STORAGE_KEY" not in combined
    assert "nepsis_openai_key" in combined
    assert "clearLegacyOpenAiKey" in combined
    assert "apiKey:" not in (src / "app" / "playground" / "page.tsx").read_text(
        encoding="utf-8"
    )
    assert "apiKey:" not in (src / "app" / "engine" / "page.tsx").read_text(
        encoding="utf-8"
    )


def test_model_sandbox_routes_require_server_side_provider_key_only() -> None:
    playground = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "playground-nepsis" / "route.ts"
    ).read_text(encoding="utf-8")
    run_with_nepsis = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "run-with-nepsis" / "route.ts"
    ).read_text(encoding="utf-8")

    for text in (playground, run_with_nepsis):
        assert "requireEngineControlAuth" in text
        assert "requireCsrfToken" in text
        assert "hasConfiguredOpenAiKey" in text
        assert "createOpenAiClient()" in text
        assert "apiKey" not in text
        assert "apiKeyOverride" not in text
        assert "browserModelKeysAllowed" not in text


@pytest.mark.parametrize("route", OPERATOR_PACKET_PROXY_ROUTES)
def test_operator_packet_proxy_routes_require_auth_and_csrf(route: str) -> None:
    path = (
        ROOT
        / "nepsis-web"
        / "src"
        / "app"
        / "api"
        / "engine"
        / "operator-packet"
        / route
        / "route.ts"
    )
    text = path.read_text(encoding="utf-8")
    assert "requireEngineControlAuth" in text
    assert "requireCsrfToken" in text


def test_private_demo_proxy_requires_operator_auth_and_csrf() -> None:
    route = (
        ROOT
        / "nepsis-web"
        / "src"
        / "app"
        / "api"
        / "engine"
        / "private-demo"
        / "route.ts"
    )
    assert route.exists()
    text = route.read_text(encoding="utf-8")

    assert "requireEngineControlAuth" in text
    assert "requireCsrfToken" in text
    assert "engineControlOwner" in text
    assert 'proxyEngineRequest("/v1/private-demo"' in text
    assert "proxyJsonResponse(upstream)" in text
    assert "buildBundledMvpFallbackResponse" not in text
    assert '"/v1/mvp"' not in text


def test_private_demo_client_contract_is_explicit() -> None:
    client = (ROOT / "nepsis-web" / "src" / "lib" / "engineClient.ts").read_text(
        encoding="utf-8"
    )

    assert "export type NepsisPrivateDemoPayload" in client
    assert "export type NepsisPrivateDemoRuntimePacket" in client
    assert 'schema_id: "nepsis.private_demo_runtime_packet"' in client
    assert 'schema_id: "nepsis.case_reasoning_compiler"' in client
    assert (
        "runPrivateDemo(payload: NepsisPrivateDemoPayload): Promise<NepsisPrivateDemoRuntimePacket>"
        in client
    )
    assert '"/private-demo"' in client


def test_private_demo_page_uses_private_runtime_not_public_mvp() -> None:
    page = ROOT / "nepsis-web" / "src" / "app" / "private-demo" / "page.tsx"
    assert page.exists()
    text = page.read_text(encoding="utf-8")

    assert "engineClient.runPrivateDemo" in text
    assert "PrivateDemoPacketView" in text
    assert "no_phi_acknowledged" in text
    assert "/api/auth/session" in text
    assert "OperatorAccessNotice" in text
    assert "runMvp" not in text
    assert "/api/engine/mvp" not in text
    assert "buildBundledMvpFallbackResponse" not in text


def test_status_api_exposes_private_demo_readiness_metadata() -> None:
    route = ROOT / "nepsis-web" / "src" / "app" / "api" / "status" / "route.ts"
    page = ROOT / "nepsis-web" / "src" / "app" / "status" / "page.tsx"
    combined = "\n".join(path.read_text(encoding="utf-8") for path in [route, page])

    assert "privateDemo" in combined
    assert 'proxyPath: "/api/engine/private-demo"' in route.read_text(encoding="utf-8")
    assert 'backendPath: "/v1/private-demo"' in route.read_text(encoding="utf-8")
    assert "requiresNoPhiAcknowledgement" in combined
    assert "Private demo" in page.read_text(encoding="utf-8")


def test_operator_frontend_uses_packet_proxy_routes() -> None:
    root = ROOT / "nepsis-web" / "src"
    client = (root / "lib" / "engineClient.ts").read_text(encoding="utf-8")
    hook = (root / "lib" / "useEngineSession.ts").read_text(encoding="utf-8")
    page = (root / "app" / "engine" / "page.tsx").read_text(encoding="utf-8")
    operator_assist = (root / "app" / "engine" / "operatorAssist.ts").read_text(
        encoding="utf-8"
    )
    assert "/operator-packet/start" in client
    assert "/operator-packet/frame" in client
    assert "/operator/frame" not in client
    assert "operatorPacket" in hook
    assert "operatorPacketToResponse" in hook
    assert "assist_acceptances" in page
    assert "operatorPacket" in page
    assert "operator_loop_id" in page
    assert "proposal_receipt" in operator_assist


def test_operator_packet_state_contract_is_explicit() -> None:
    root = ROOT / "nepsis-web" / "src"
    client = (root / "lib" / "engineClient.ts").read_text(encoding="utf-8")
    hook = (root / "lib" / "useEngineSession.ts").read_text(encoding="utf-8")

    assert "export type EngineOperatorPacketState" in client
    assert 'schema_id: "nepsis.operator_packet_state"' in client
    assert (
        "getOperatorSessionState(payload: { packet?: EngineOperatorPacket } = {}): Promise<EngineOperatorPacketState>"
        in client
    )
    assert "type EngineOperatorPacketState" in hook
    assert "isOperatorPacketState" in hook
    assert "operatorPacketStateToResponse" in hook
    assert "operatorPacketState" in hook


def test_operator_model_route_is_field_level_and_excludes_threshold_decision() -> None:
    text = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "operator" / "model" / "route.ts"
    ).read_text(encoding="utf-8")
    assert "requireEngineControlAuth" in text
    assert "requireCsrfToken" in text
    assert "suggest_field" in text
    assert "threshold.hold_reason" in text
    assert "threshold.decision" not in text
    assert "target: requestedTarget" in text
    assert "frameDraft" not in text


def test_operator_model_route_signs_packet_bound_proposal_receipts() -> None:
    route = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "operator" / "model" / "route.ts"
    ).read_text(encoding="utf-8")
    helper = (
        ROOT / "nepsis-web" / "src" / "lib" / "operatorProposalReceipt.ts"
    ).read_text(encoding="utf-8")
    client = (ROOT / "nepsis-web" / "src" / "lib" / "operatorModelClient.ts").read_text(
        encoding="utf-8"
    )

    assert "operator_loop_id" in route
    assert "operator_loop_id is required" in route
    assert "Server proposal receipt secret required" in route
    assert "hasConfiguredProposalReceiptSecret" in route
    assert "signOperatorProposalReceipt" in route
    assert "proposedValueHash" in route
    assert "proposalReceipt" in route
    assert "createHmac" in helper
    assert "NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET" in helper
    assert "loop_id" in helper
    assert "proposalReceipt" in client


def test_operator_guide_route_is_protected_and_packet_delta_scoped() -> None:
    route = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "operator" / "guide" / "route.ts"
    ).read_text(encoding="utf-8")
    patch_action_route = (
        ROOT
        / "nepsis-web"
        / "src"
        / "app"
        / "api"
        / "engine"
        / "operator-packet"
        / "guide"
        / "patch-action"
        / "route.ts"
    ).read_text(encoding="utf-8")
    client = (ROOT / "nepsis-web" / "src" / "lib" / "operatorGuideClient.ts").read_text(
        encoding="utf-8"
    )
    engine_client = (ROOT / "nepsis-web" / "src" / "lib" / "engineClient.ts").read_text(
        encoding="utf-8"
    )

    assert "requireEngineControlAuth" in route
    assert "requireCsrfToken" in route
    assert "modelRoutesEnabled" in route
    assert "hasConfiguredOpenAiKey" in route
    assert "hasConfiguredProposalReceiptSecret" in route
    assert "signOperatorProposalReceipt" in route
    assert "threshold.decision" not in route
    assert "packet_delta_preview" in route
    assert "consequenceLevel" in route
    assert "requiresEchoConfirmation" in route
    assert "basis" in route
    assert "fields_ready_to_lock" in route
    assert "blocking_uncertainties" in route
    assert "ranked_discriminators" in route
    assert "requestOperatorGuide" in client
    assert "/api/operator/guide" in client
    assert "guideOperatorPacket" in engine_client
    assert "/operator-packet/guide" in engine_client
    assert "guidePatchAction" in engine_client
    assert "/operator-packet/guide/patch-action" in engine_client
    assert "requireEngineControlAuth" in patch_action_route
    assert "requireCsrfToken" in patch_action_route
    assert "/v1/operator-packet/guide/patch-action" in patch_action_route

    operator_page = (ROOT / "nepsis-web" / "src" / "app" / "engine" / "page.tsx").read_text(
        encoding="utf-8"
    )
    assert "Frame convergence" in operator_page
    assert "Discriminator queue" in operator_page
    assert "Guide next move" in operator_page
    assert "guideSurfaceEnabled" in operator_page
    assert "Accept low-consequence drafts" in operator_page
    assert "I confirm this patch may narrow" in operator_page


def test_guided_operator_completion_does_not_touch_public_mvp() -> None:
    mvp_page = (ROOT / "nepsis-web" / "src" / "app" / "mvp" / "page.tsx").read_text(
        encoding="utf-8"
    )
    assert "requestOperatorModel" not in mvp_page
    assert "requestOperatorGuide" not in mvp_page
    assert "/api/operator/model" not in mvp_page
    assert "/api/operator/guide" not in mvp_page
    assert "guidePatchAction" not in mvp_page
    assert "/operator-packet/guide/patch-action" not in mvp_page
    assert "Run Demo" in mvp_page
    assert "Model-free deterministic run" in mvp_page


def test_public_mvp_fallback_discloses_reason() -> None:
    helper = (ROOT / "nepsis-web" / "src" / "lib" / "mvpFallback.ts").read_text(
        encoding="utf-8"
    )
    route = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "engine" / "mvp" / "route.ts"
    ).read_text(encoding="utf-8")

    assert "fallback_source" in helper
    assert "fallback_reason" in helper
    assert "backend_unconfigured" in route
    assert "upstream_non_ok" in route
    assert "public_fallback_after_proxy_error" in route


def test_engine_proxy_preserves_upstream_json_text_for_sealed_packets() -> None:
    helper = (ROOT / "nepsis-web" / "src" / "lib" / "engineApi.ts").read_text(
        encoding="utf-8"
    )
    proxy = helper[helper.index("export async function proxyJsonResponse") :]

    assert "const text = await res.text();" in proxy
    assert "return new Response(text" in proxy
    assert "await res.json()" not in proxy


def test_render_blueprint_deploys_existing_asgi_entrypoint() -> None:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "nepsiscgn-api-asgi" in text
    assert "NEPSIS_API_HOST" in text
    assert "0.0.0.0" in text
    assert "NEPSIS_API_PORT" in text
    assert "$PORT" in text
    assert "NEPSIS_API_TOKEN" in text
    assert "NEPSIS_MCP_CAPABILITY_TOKEN_HASHES" in text
    assert "NEPSIS_API_ALLOW_ANON" in text
    assert 'value: "false"' in text
    assert "NEPSIS_API_ALLOWED_ORIGINS" in text
    assert "OPENAI_API_KEY" not in text
    assert "NEPSIS_OPENAI_API_KEY" not in text


def test_api_smoke_script_checks_vercel_backend_boundary() -> None:
    script = ROOT / "scripts" / "api-smoke.sh"
    text = script.read_text(encoding="utf-8")
    syntax = subprocess.run(
        ["bash", "-n", str(script)], cwd=ROOT, capture_output=True, text=True
    )

    assert syntax.returncode == 0, syntax.stderr
    assert "urllib.request" in text
    assert "curl" not in text
    assert "https://nepsis-cgn-api.vercel.app" in text
    assert "/v1/health" in text
    assert "/v1/routes" in text
    assert "/v1/mvp" in text
    assert "/v1/private-demo" in text
    assert "/v1/operator-packet/v3/start" in text
    assert "/v1/operator-packet/v3/field" in text
    assert "/v1/operator-packet/v3/propose" in text
    assert "/v1/operator-packet/v3/lock" in text
    assert "operator V3 route reachability" in text
    assert "/mcp" in text
    assert "expected={401}" in text
    assert "nepsis.private_demo_runtime_packet" in text
    assert "Private demo runtime is not configured." in text
    assert "LOCK_FRAME" in text
    assert "RUN_REPORT" in text
    assert "LOCK_REPORT" in text
    assert "SET_THRESHOLD_DECISION" in text
    assert "-32001" in text


def test_site_smoke_script_is_stdlib_python_and_has_expected_routes() -> None:
    script = ROOT / "scripts" / "site-smoke.sh"
    text = script.read_text(encoding="utf-8")
    syntax = subprocess.run(
        ["bash", "-n", str(script)], cwd=ROOT, capture_output=True, text=True
    )

    assert syntax.returncode == 0, syntax.stderr
    assert "urllib.request" in text
    assert "curl" not in text
    assert "/login" in text
    assert "/engine" in text
    assert "/api/engine/mvp" in text
    assert "/api/engine/health" in text
    assert "/api/auth/session" in text
    assert "/api/playground-nepsis" in text
    assert "/api/run-with-nepsis" in text
    assert "authenticated" in text
    assert "engineControlAllowed" in text
    assert "operatorLoginReady" in text
    assert "modelRoutesEnabled" in text
    assert "hasServerKey" in text
    assert "publicSite" in text
    assert "operatorMode" in text
    assert "nepsis-web/.env.public.example" in text
    assert "nepsis-web/.env.operator.example" in text
    assert "NEPSIS_MCP_CAPABILITY_TOKEN" in text
    assert "start_operator_packet" in text


def test_site_smoke_script_checks_hosted_mcp_boundary() -> None:
    requests: list[dict[str, Any]] = []

    class SmokeHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            requests.append({"method": "GET", "path": self.path})
            if self.path in {"/", "/mvp", "/login", "/engine", "/operator"}:
                self._send(200, "ok", content_type="text/plain")
                return
            if self.path == "/api/status":
                endpoint = f"http://127.0.0.1:{self.server.server_port}/mcp"
                self._send_json(
                    200,
                    {
                        "mvp": {
                            "available": True,
                            "schemaId": "nepsis.mvp_packet",
                            "noLoginRequired": True,
                        },
                        "auth": {
                            "previewCodesEnabled": False,
                            "allowedEmailsConfigured": False,
                            "persistentSessionDays": 30,
                            "sessionRevokeBeforeConfigured": False,
                            "emailConfigured": False,
                            "operatorLoginReady": False,
                        },
                        "models": {"enabled": False, "hasServerOpenAiKey": False},
                        "operator": {"enabled": False},
                        "setup": {
                            "publicSite": {
                                "ready": True,
                                "envExample": "nepsis-web/.env.public.example",
                                "assertions": [],
                            },
                            "operatorMode": {
                                "ready": False,
                                "envExample": "nepsis-web/.env.operator.example",
                                "assertions": [],
                            },
                        },
                        "mcp": {
                            "discoverableMethods": ["initialize", "tools/list"],
                            "protectedTools": [
                                "run_mvp",
                                "get_routes",
                                "start_operator_packet",
                            ],
                            "hosted": {
                                "available": True,
                                "endpoint": endpoint,
                                "requiresBackendAuth": False,
                                "requiresCapabilityToken": True,
                                "modelKeysRequired": False,
                            },
                        },
                    },
                )
                return
            if self.path == "/api/auth/session":
                self._send_json(
                    200, {"authenticated": False, "engineControlAllowed": False}
                )
                return
            if self.path == "/api/playground-nepsis":
                self._send_json(
                    200, {"modelRoutesEnabled": False, "hasServerKey": False}
                )
                return
            if self.path == "/api/engine/health":
                self._send_json(200, {"ok": True})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            body = json.loads(raw) if raw else {}
            requests.append(
                {
                    "method": "POST",
                    "path": self.path,
                    "body": body,
                    "authorization": self.headers.get("Authorization"),
                    "capability": self.headers.get("X-Nepsis-Capability-Token"),
                }
            )
            if self.path == "/api/engine/mvp":
                self._send_json(200, {"schema_id": "nepsis.mvp_packet"})
                return
            if self.path in {
                "/api/playground-nepsis",
                "/api/run-with-nepsis",
                "/api/operator/model",
            }:
                self._send_json(403, {"error": "forbidden"})
                return
            if self.path == "/mcp":
                method = body.get("method")
                if method == "initialize":
                    self._send_json(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "id": body.get("id"),
                            "result": {
                                "serverInfo": {"name": "nepsis-cgn"},
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
                                    {"name": "get_routes"},
                                    {"name": "start_operator_packet"},
                                ]
                            },
                        },
                    )
                    return
                if method == "tools/call":
                    if self.headers.get("Authorization") == "Bearer site-smoke-token":
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
                                                    "phase": "frame_draft",
                                                }
                                            ),
                                        }
                                    ],
                                    "isError": False,
                                },
                            },
                        )
                        return
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
            self._send_json(404, {"error": "not found"})

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            self._send(status, json.dumps(payload), content_type="application/json")

        def _send(self, status: int, payload: str, *, content_type: str) -> None:
            encoded = payload.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), SmokeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            **os.environ,
            "NEPSIS_SITE_BASE_URL": f"http://127.0.0.1:{server.server_port}",
            "NEPSIS_MCP_CAPABILITY_TOKEN": "site-smoke-token",
            "PYTHON_BIN": sys.executable,
        }
        result = subprocess.run(
            ["bash", str(ROOT / "scripts" / "site-smoke.sh")],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert result.returncode == 0, result.stdout + result.stderr
    mcp_methods = [
        request["body"].get("method")
        for request in requests
        if request["method"] == "POST" and request["path"] == "/mcp"
    ]
    assert mcp_methods == ["initialize", "tools/list", "tools/call", "tools/call"]
    tool_calls = [
        request
        for request in requests
        if request["method"] == "POST"
        and request["path"] == "/mcp"
        and request["body"].get("method") == "tools/call"
    ]
    assert tool_calls[0]["authorization"] is None
    assert tool_calls[0]["capability"] is None
    assert tool_calls[1]["authorization"] == "Bearer site-smoke-token"
    assert tool_calls[1]["body"]["params"]["name"] == "start_operator_packet"
