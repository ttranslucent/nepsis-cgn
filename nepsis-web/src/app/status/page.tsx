"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";

type StatusPayload = {
  backend: {
    configured: boolean;
    reachable: boolean;
    status: number | null;
    detail?: string;
  };
  mvp: {
    available: boolean;
    status: number | null;
    schemaId: string | null;
    noLoginRequired: boolean;
    detail?: string;
  };
  auth: {
    loginConfigured: boolean;
    authSecretConfigured?: boolean;
    authSecretMode?: "configured" | "development-fallback" | "missing";
    emailConfigured?: boolean;
    previewCodesEnabled: boolean;
    operatorLoginReady?: boolean;
  };
  models: {
    enabled: boolean;
    hasServerOpenAiKey: boolean;
  };
  mcp: {
    available: boolean;
    endpoint?: string | null;
    publicTools: string[];
    protectedTools?: string[];
    operatorTools?: string[];
    local?: {
      available: boolean;
      command: string;
      transport: string;
      modelKeysRequired: boolean;
      lifecycle?: string;
    };
    hosted?: {
      available: boolean;
      endpoint?: string | null;
      deferred: boolean;
      requiresBackendAuth?: boolean;
    };
  };
};

function Badge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
        ok
          ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-200"
          : "border-amber-500/50 bg-amber-500/10 text-amber-100"
      }`}
    >
      {label}
    </span>
  );
}

function StatusCard({
  title,
  ok,
  children,
}: {
  title: string;
  ok: boolean;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-5">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-lg font-semibold">{title}</h2>
        <Badge ok={ok} label={ok ? "ready" : "needs setup"} />
      </div>
      <div className="mt-4 space-y-2 text-sm text-nepsis-muted">{children}</div>
    </section>
  );
}

function authSecretLabel(auth: StatusPayload["auth"]): string {
  if (auth.authSecretMode === "development-fallback") {
    return "Dev auth secret active.";
  }
  if (auth.authSecretConfigured ?? auth.loginConfigured) {
    return "Auth secret configured.";
  }
  return "Auth secret missing.";
}

export default function StatusPage() {
  const [status, setStatus] = useState<StatusPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadStatus() {
      try {
        const response = await fetch("/api/status", { cache: "no-store" });
        const payload = (await response.json()) as StatusPayload;
        if (!cancelled) {
          setStatus(payload);
        }
      } catch (err) {
        if (!cancelled) {
          setError((err as Error)?.message ?? "Status check failed.");
        }
      }
    }
    void loadStatus();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 md:px-6 md:py-12">
      <div className="mb-6">
        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-nepsis-muted">Public readiness</div>
        <h1 className="mt-2 text-3xl font-semibold">System Status</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-nepsis-muted">
          Public users should be able to run the deterministic MVP without login or model keys. Operator tools stay
          gated on the hosted site, while local MCP runs through stdio with the model client the user chooses.
        </p>
      </div>

      {error && <div className="rounded-2xl border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-100">{error}</div>}
      {!status && !error && (
        <div className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-5 text-sm text-nepsis-muted">
          Checking deployment status...
        </div>
      )}

      {status && (
        <div className="grid gap-4 md:grid-cols-2">
          <StatusCard title="Public MVP" ok={status.mvp.available}>
            <p>{status.mvp.available ? "Frozen /mvp packet is reachable." : "Frozen /mvp packet is not reachable."}</p>
            <p>Schema: {status.mvp.schemaId ?? "unavailable"}</p>
            <p>{status.mvp.noLoginRequired ? "No login required" : "Login required"}</p>
            <p>Provider model keys not required.</p>
            {status.mvp.status && <p>HTTP status: {status.mvp.status}</p>}
          </StatusCard>

          <StatusCard title="Backend API" ok={status.backend.configured && status.backend.reachable}>
            <p>
              {status.backend.configured ? "NEPSIS_API_BASE_URL is set." : "NEPSIS_API_BASE_URL is not configured."}
            </p>
            <p>
              {status.backend.reachable
                ? "Backend health check is reachable."
                : "Backend health check is not reachable."}
            </p>
            {status.backend.status && <p>HTTP status: {status.backend.status}</p>}
          </StatusCard>

          <StatusCard
            title="Operator Login"
            ok={
              status.auth.operatorLoginReady ??
              (status.auth.loginConfigured && (status.auth.emailConfigured || status.auth.previewCodesEnabled))
            }
          >
            <p>Public MVP access does not require login.</p>
            <p>{authSecretLabel(status.auth)}</p>
            <p>{status.auth.emailConfigured ? "Email login configured." : "Email login not configured."}</p>
            <p>{status.auth.previewCodesEnabled ? "Preview codes enabled." : "Preview codes disabled."}</p>
          </StatusCard>

          <StatusCard title="Model Routes" ok={!status.models.enabled || status.models.hasServerOpenAiKey}>
            <p>{status.models.enabled ? "Model routes are enabled." : "Model routes are disabled for the public site."}</p>
            <p>
              {status.models.hasServerOpenAiKey
                ? "Server OpenAI key configured."
                : "No server OpenAI key configured."}
            </p>
          </StatusCard>

          <StatusCard title="Local MCP Bridge" ok={status.mcp.local?.available ?? false}>
            <p>Command: {status.mcp.local?.command ?? "nepsiscgn-mcp"}</p>
            <p>Transport: {status.mcp.local?.transport ?? "stdio"}</p>
            <p>
              {status.mcp.local?.modelKeysRequired === false
                ? "No model provider API key collected by NepsisCGN."
                : "Model key requirement unknown."}
            </p>
            <p>{status.mcp.local?.lifecycle ?? "One local process owns one implicit ambient session."}</p>
            <p>Public tools: {status.mcp.publicTools.join(", ")}</p>
            <p>Operator phase tools: {(status.mcp.operatorTools ?? []).join(", ") || "none"}</p>
          </StatusCard>

          <StatusCard title="Hosted MCP Endpoint" ok={status.mcp.hosted?.available ?? status.mcp.available}>
            <p>MCP endpoint: {status.mcp.hosted?.endpoint ?? status.mcp.endpoint ?? "/mcp"}</p>
            <p>
              {status.mcp.hosted?.deferred
                ? "Deferred until backend auth and deployment are configured."
                : "Hosted MCP endpoint is reachable."}
            </p>
            <p>
              {status.mcp.hosted?.requiresBackendAuth === false
                ? "Backend auth not required."
                : "Requires backend auth, TLS, ownership, and security review."}
            </p>
            <p>Hosted protected tools: {(status.mcp.protectedTools ?? []).join(", ") || "none"}</p>
          </StatusCard>
        </div>
      )}
    </div>
  );
}
