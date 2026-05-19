import { NextResponse } from "next/server";

import { modelRoutesEnabled } from "@/lib/publicMode";
import { hasConfiguredOpenAiKey } from "@/lib/openaiClient";

export const runtime = "nodejs";

function configured(value: string | undefined): boolean {
  return Boolean(value?.trim());
}

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

export async function GET() {
  const backend = await backendHealth(process.env.NEPSIS_API_BASE_URL, process.env.NEPSIS_API_TOKEN);
  const mcp = await mcpHealth(process.env.NEPSIS_API_BASE_URL);
  const loginConfigured = configured(process.env.NEPSIS_AUTH_SECRET);
  const emailConfigured = configured(process.env.RESEND_API_KEY) && configured(process.env.NEPSIS_AUTH_FROM_EMAIL);
  const previewCodesEnabled = process.env.NEPSIS_AUTH_ALLOW_CODE_PREVIEW?.trim().toLowerCase() === "true";
  const modelsEnabled = modelRoutesEnabled();

  return NextResponse.json({
    backend,
    auth: {
      loginConfigured,
      emailConfigured,
      previewCodesEnabled,
    },
    models: {
      enabled: modelsEnabled,
      hasServerOpenAiKey: modelsEnabled && hasConfiguredOpenAiKey(),
    },
    mcp: {
      available: mcp.available,
      endpoint: mcp.endpoint,
      publicTools: ["run_mvp", "get_mvp_schema", "health"],
      protectedTools: ["get_routes"],
    },
  });
}
