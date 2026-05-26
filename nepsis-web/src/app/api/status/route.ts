import { NextResponse } from "next/server";

import {
  envFlag,
  liveOperatorEnabled,
  modelRoutesEnabled,
  operatorSiteMode,
  publicSiteMode,
} from "@/lib/publicMode";
import { hasConfiguredOpenAiKey } from "@/lib/openaiClient";
import { buildBundledMvpFallbackResponse } from "@/lib/mvpFallback";
import {
  authSecretStatus,
  loginEmailConfigured,
  operatorLoginReady,
  previewCodesAllowed,
} from "@/lib/nepsisAuth";

export const runtime = "nodejs";

async function backendHealth(baseUrl: string | undefined, token: string | undefined) {
  const trimmedBase = baseUrl?.trim().replace(/\/+$/, "");
  if (!trimmedBase) {
    return {
      configured: false,
      reachable: false,
      status: null,
      detail: "NEPSIS_API_BASE_URL is not configured.",
    };
  }

  try {
    const headers = new Headers();
    if (token?.trim()) {
      headers.set("Authorization", `Bearer ${token.trim()}`);
    }
    const response = await fetch(`${trimmedBase}/v1/health`, {
      method: "GET",
      headers,
      cache: "no-store",
    });
    return {
      configured: true,
      reachable: response.ok,
      status: response.status,
      detail: response.ok ? "Backend health check passed." : await response.text(),
    };
  } catch (error) {
    return {
      configured: true,
      reachable: false,
      status: null,
      detail: (error as Error)?.message ?? "Backend health check failed.",
    };
  }
}

async function mvpHealth(baseUrl: string | undefined, token: string | undefined) {
  const trimmedBase = baseUrl?.trim().replace(/\/+$/, "");
  if (!trimmedBase) {
    const response = buildBundledMvpFallbackResponse(JSON.stringify({ case_id: "jailing" }));
    const payload = await response.json();
    const schemaId =
      typeof payload === "object" && payload !== null && "schema_id" in payload
        ? String((payload as { schema_id: unknown }).schema_id)
        : null;
    const available = response.ok && schemaId === "nepsis.mvp_packet";
    return {
      available,
      status: response.status,
      schemaId,
      noLoginRequired: true,
      detail: available
        ? "Bundled frozen MVP packet check passed without backend configuration."
        : "Bundled MVP packet response did not match the expected schema.",
    };
  }

  try {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (token?.trim()) {
      headers.set("Authorization", `Bearer ${token.trim()}`);
    }
    const response = await fetch(`${trimmedBase}/v1/mvp`, {
      method: "POST",
      headers,
      body: JSON.stringify({ case_id: "jailing" }),
      cache: "no-store",
    });
    const contentType = response.headers.get("content-type") ?? "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : await response.text();
    const schemaId =
      typeof payload === "object" && payload !== null && "schema_id" in payload
        ? String((payload as { schema_id: unknown }).schema_id)
        : null;
    const available = response.ok && schemaId === "nepsis.mvp_packet";
    return {
      available,
      status: response.status,
      schemaId,
      noLoginRequired: true,
      detail: available
        ? "Frozen MVP packet check passed."
        : typeof payload === "string"
          ? payload
          : "MVP packet response did not match the expected schema.",
    };
  } catch (error) {
    return {
      available: false,
      status: null,
      schemaId: null,
      noLoginRequired: true,
      detail: (error as Error)?.message ?? "MVP packet check failed.",
    };
  }
}

async function mcpHealth(baseUrl: string | undefined) {
  const trimmedBase = baseUrl?.trim().replace(/\/+$/, "");
  if (!trimmedBase) {
    return { available: false, endpoint: null };
  }

  try {
    const response = await fetch(`${trimmedBase}/mcp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }),
      cache: "no-store",
    });
    return {
      available: response.ok,
      endpoint: `${trimmedBase}/mcp`,
    };
  } catch {
    return {
      available: false,
      endpoint: `${trimmedBase}/mcp`,
    };
  }
}

type ReadinessAssertion = {
  id: string;
  ok: boolean;
  label: string;
  detail: string;
  env: string[];
};

function readiness(assertions: ReadinessAssertion[]) {
  return {
    ready: assertions.every((assertion) => assertion.ok),
    assertions,
  };
}

export async function GET() {
  const [backend, mvp, mcp] = await Promise.all([
    backendHealth(process.env.NEPSIS_API_BASE_URL, process.env.NEPSIS_API_TOKEN),
    mvpHealth(process.env.NEPSIS_API_BASE_URL, process.env.NEPSIS_API_TOKEN),
    mcpHealth(process.env.NEPSIS_API_BASE_URL),
  ]);
  const authSecret = authSecretStatus();
  const emailConfigured = loginEmailConfigured();
  const previewCodesEnabled = previewCodesAllowed();
  const modelsEnabled = modelRoutesEnabled();
  const operatorMode = operatorSiteMode();
  const operatorEnabled = liveOperatorEnabled();
  const serverModelKeyConfigured = hasConfiguredOpenAiKey();
  const apiTokenConfigured = Boolean(process.env.NEPSIS_API_TOKEN?.trim());
  const mcpToolNames = [
    "run_mvp",
    "get_mvp_schema",
    "health",
    "get_routes",
    "start_operator_packet",
    "get_session_state",
    "lock_frame",
    "run_report",
    "lock_report",
    "set_threshold_decision",
    "commit_iteration",
    "abandon_packet",
  ];
  const operatorPacketTools = [
    "start_operator_packet",
    "get_session_state",
    "lock_frame",
    "run_report",
    "lock_report",
    "set_threshold_decision",
    "commit_iteration",
    "abandon_packet",
  ];
  const capabilityTokenConfigured = Boolean(process.env.NEPSIS_MCP_CAPABILITY_TOKEN_HASHES?.trim());

  return NextResponse.json({
    backend,
    mvp,
    operator: {
      enabled: operatorEnabled,
      operatorSiteMode: operatorMode,
      path: "/operator",
      backendReady: backend.configured && backend.reachable,
      authReady: operatorLoginReady(),
      modelReady: modelsEnabled && serverModelKeyConfigured,
    },
    auth: {
      loginConfigured: authSecret.ready,
      authSecretConfigured: authSecret.configured,
      authSecretMode: authSecret.mode,
      emailConfigured,
      previewCodesEnabled,
      operatorLoginReady: operatorLoginReady(),
    },
    models: {
      enabled: modelsEnabled,
      hasServerOpenAiKey: modelsEnabled && serverModelKeyConfigured,
    },
    setup: {
      publicSite: {
        envExample: "nepsis-web/.env.public.example",
        docs: [{ label: "Public site setup", href: "docs/public-api.md#public-site-setup" }],
        ...readiness([
          {
            id: "public-site-mode",
            ok: publicSiteMode(),
            label: "Public site mode active",
            detail: "The web deployment is rendering the frozen public /mvp posture.",
            env: ["NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true"],
          },
          {
            id: "mvp-no-login",
            ok: mvp.available && mvp.noLoginRequired,
            label: "Frozen /mvp packet available without login",
            detail: "The public path returns nepsis.mvp_packet and does not require an operator session.",
            env: ["NEPSIS_API_BASE_URL optional", "NEPSIS_API_TOKEN optional when backend is configured"],
          },
          {
            id: "operator-disabled",
            ok: !operatorMode && !operatorEnabled,
            label: "Live operator mode disabled",
            detail: "The public site keeps /operator gated and does not expose live operator affordances.",
            env: ["NEPSIS_DEPLOYMENT_MODE unset", "NEXT_PUBLIC_NEPSIS_OPERATOR_SITE=false", "NEPSIS_LIVE_OPERATOR_ENABLED=false"],
          },
          {
            id: "model-routes-disabled",
            ok: !modelsEnabled && !serverModelKeyConfigured,
            label: "Model routes and server provider keys absent",
            detail: "The public /mvp deployment stays deterministic and does not need model-provider credentials.",
            env: ["NEPSIS_MODEL_ROUTES_ENABLED=false", "OPENAI_API_KEY unset", "NEPSIS_OPENAI_API_KEY unset"],
          },
          {
            id: "local-escapes-disabled",
            ok: !envFlag("NEPSIS_ENGINE_ALLOW_ANON") && !previewCodesEnabled,
            label: "Local-only auth escapes disabled",
            detail: "Anonymous engine controls and preview login codes are local-only and should not be active here.",
            env: ["NEPSIS_ENGINE_ALLOW_ANON=false", "NEPSIS_AUTH_ALLOW_CODE_PREVIEW=false"],
          },
        ]),
      },
      operatorMode: {
        envExample: "nepsis-web/.env.operator.example",
        docs: [{ label: "Private operator deployment", href: "docs/operator-runbook.md#private-operator-deployment" }],
        ...readiness([
          {
            id: "operator-mode",
            ok: operatorMode && operatorEnabled,
            label: "Private operator mode active",
            detail: "The deployment is explicitly configured as a live operator surface.",
            env: ["NEPSIS_DEPLOYMENT_MODE=operator", "NEXT_PUBLIC_NEPSIS_OPERATOR_SITE=true", "NEPSIS_LIVE_OPERATOR_ENABLED=true"],
          },
          {
            id: "backend-auth",
            ok: backend.configured && backend.reachable && apiTokenConfigured,
            label: "Backend API reachable with proxy token configured",
            detail: "Private operator mode needs a reachable FastAPI backend and a shared web-proxy token.",
            env: ["NEPSIS_API_BASE_URL", "NEPSIS_API_TOKEN"],
          },
          {
            id: "real-login",
            ok: authSecret.ready && emailConfigured && !previewCodesEnabled,
            label: "Real passwordless login ready",
            detail: "Operator login should use signed cookies and email delivery, not preview codes.",
            env: ["NEPSIS_AUTH_SECRET", "RESEND_API_KEY", "NEPSIS_AUTH_FROM_EMAIL", "NEPSIS_AUTH_ALLOW_CODE_PREVIEW=false"],
          },
          {
            id: "live-model-routes",
            ok: modelsEnabled && serverModelKeyConfigured,
            label: "Live model routes enabled with server-side key",
            detail: "Operator model assistance is available only behind auth with a server-side provider key.",
            env: ["NEPSIS_MODEL_ROUTES_ENABLED=true", "OPENAI_API_KEY or NEPSIS_OPENAI_API_KEY"],
          },
          {
            id: "anonymous-controls-disabled",
            ok: !envFlag("NEPSIS_ENGINE_ALLOW_ANON"),
            label: "Anonymous engine controls disabled",
            detail: "Private operator deployments require signed browser identity for engine controls.",
            env: ["NEPSIS_ENGINE_ALLOW_ANON=false"],
          },
        ]),
      },
    },
    mcp: {
      available: mcp.available,
      endpoint: mcp.endpoint,
      discoverableMethods: ["initialize", "tools/list"],
      publicTools: [],
      protectedTools: mcpToolNames,
      operatorTools: operatorPacketTools,
      local: {
        available: true,
        command: "nepsiscgn-mcp",
        transport: "stdio",
        modelKeysRequired: false,
        lifecycle: "stateless packet-in/packet-out; the model host stores the packet",
      },
      hosted: {
        available: mcp.available,
        endpoint: mcp.endpoint,
        deferred: !mcp.available,
        requiresBackendAuth: false,
        requiresCapabilityToken: true,
        capabilityTokenConfigured,
        modelKeysRequired: false,
      },
    },
  });
}
