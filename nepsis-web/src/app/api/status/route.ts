import { NextResponse } from "next/server";

import { modelRoutesEnabled } from "@/lib/publicMode";
import { hasConfiguredOpenAiKey } from "@/lib/openaiClient";
import { buildBundledMvpFallbackResponse } from "@/lib/mvpFallback";
import { previewCodesAllowed } from "@/lib/nepsisAuth";

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

export async function GET() {
  const [backend, mvp, mcp] = await Promise.all([
    backendHealth(process.env.NEPSIS_API_BASE_URL, process.env.NEPSIS_API_TOKEN),
    mvpHealth(process.env.NEPSIS_API_BASE_URL, process.env.NEPSIS_API_TOKEN),
    mcpHealth(process.env.NEPSIS_API_BASE_URL),
  ]);
  const loginConfigured = configured(process.env.NEPSIS_AUTH_SECRET);
  const emailConfigured = configured(process.env.RESEND_API_KEY) && configured(process.env.NEPSIS_AUTH_FROM_EMAIL);
  const previewCodesEnabled = previewCodesAllowed();
  const modelsEnabled = modelRoutesEnabled();

  return NextResponse.json({
    backend,
    mvp,
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
