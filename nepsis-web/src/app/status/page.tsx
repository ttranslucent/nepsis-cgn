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
  auth: {
    loginConfigured: boolean;
    emailConfigured?: boolean;
    previewCodesEnabled: boolean;
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
          gated until deployment auth and backend access are configured.
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
          <StatusCard title="Backend API" ok={status.backend.configured && status.backend.reachable}>
            <p>{status.backend.configured ? "NEPSIS_API_BASE_URL is set." : "NEPSIS_API_BASE_URL is not configured."}</p>
            <p>{status.backend.reachable ? "Backend health check is reachable." : "Backend health check is not reachable."}</p>
            {status.backend.status && <p>HTTP status: {status.backend.status}</p>}
          </StatusCard>

          <StatusCard title="Login" ok={status.auth.loginConfigured && (status.auth.emailConfigured || status.auth.previewCodesEnabled)}>
            <p>{status.auth.loginConfigured ? "Auth secret configured." : "Auth secret missing."}</p>
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

          <StatusCard title="MCP Tools" ok={status.mcp.available}>
            <p>MCP endpoint: {status.mcp.endpoint ?? "/mcp"}</p>
            <p>Public tools: {status.mcp.publicTools.join(", ")}</p>
            <p>Protected tools: {(status.mcp.protectedTools ?? []).join(", ") || "none"}</p>
          </StatusCard>
        </div>
      )}
    </div>
  );
}
