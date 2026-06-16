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
  operator: {
    enabled: boolean;
    operatorSiteMode: boolean;
    path: string;
    backendReady: boolean;
    authReady: boolean;
    modelReady: boolean;
  };
  auth: {
    loginConfigured: boolean;
    authSecretConfigured?: boolean;
    authSecretMode?: "configured" | "development-fallback" | "missing";
    allowedEmailsConfigured?: boolean;
    emailConfigured?: boolean;
    previewCodesEnabled: boolean;
    persistentSessionDays?: number;
    sessionRevokeBeforeConfigured?: boolean;
    operatorLoginReady?: boolean;
  };
  models: {
    enabled: boolean;
    hasServerOpenAiKey: boolean;
  };
  providerAccess?: {
    userProviderKeysAccepted: boolean;
    modelAccessMode: string;
    approvalBackend: string;
    adminTestLogin: string;
    invitedUserFlow: string;
    userOwnedModelAccess: string;
  };
  setup?: {
    publicSite: SetupPath;
    operatorMode: SetupPath;
  };
  mcp: {
    available: boolean;
    endpoint?: string | null;
    discoverableMethods?: string[];
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
      requiresCapabilityToken?: boolean;
      capabilityTokenConfigured?: boolean;
      modelKeysRequired?: boolean;
    };
  };
};

type SetupAssertion = {
  id: string;
  ok: boolean;
  label: string;
  detail: string;
  env: string[];
};

type SetupPath = {
  ready: boolean;
  envExample: string;
  docs: { label: string; href: string }[];
  assertions: SetupAssertion[];
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

function SetupPathCard({ title, path }: { title: string; path: SetupPath }) {
  return (
    <StatusCard title={title} ok={path.ready}>
      <p>Env example: {path.envExample}</p>
      <p>Docs: {path.docs.map((doc) => `${doc.label} (${doc.href})`).join(", ")}</p>
      <ul className="space-y-2">
        {path.assertions.map((assertion) => (
          <li key={assertion.id}>
            <span className={assertion.ok ? "text-emerald-200" : "text-amber-100"}>
              {assertion.ok ? "Ready" : "Needs setup"}:
            </span>{" "}
            {assertion.label}. <span>{assertion.detail}</span>
            <span className="block text-xs">Env: {assertion.env.join(", ")}</span>
          </li>
        ))}
      </ul>
    </StatusCard>
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
          gated on the hosted site, while MCP tools run against the model client and account the user chooses.
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

          {status.setup?.publicSite && <SetupPathCard title="Public Site Setup" path={status.setup.publicSite} />}

          {status.setup?.operatorMode && (
            <SetupPathCard title="Private Operator Setup" path={status.setup.operatorMode} />
          )}

          <StatusCard title="Live Operator" ok={status.operator.enabled && status.operator.backendReady && status.operator.authReady}>
            <p>{status.operator.enabled ? "Live operator route is enabled." : "Live operator route is disabled."}</p>
            <p>Path: {status.operator.path}</p>
            <p>{status.operator.backendReady ? "Backend is reachable." : "Backend is not ready."}</p>
            <p>{status.operator.authReady ? "Operator auth is ready." : "Operator auth is not ready."}</p>
            <p>{status.operator.modelReady ? "Server model key is ready." : "Server model key is not ready."}</p>
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
            <p>
              {status.auth.allowedEmailsConfigured
                ? "Operator email allowlist configured."
                : "Operator email allowlist missing."}
            </p>
            <p>{status.auth.emailConfigured ? "Email login configured." : "Email login not configured."}</p>
            <p>{status.auth.previewCodesEnabled ? "Preview codes enabled." : "Preview codes disabled."}</p>
            <p>Persistent session window: {status.auth.persistentSessionDays ?? 30} days.</p>
            <p>
              {status.auth.sessionRevokeBeforeConfigured
                ? "Global session revocation configured."
                : "Global session revocation not configured."}
            </p>
          </StatusCard>

          <StatusCard title="Model Routes" ok={!status.models.enabled || status.models.hasServerOpenAiKey}>
            <p>{status.models.enabled ? "Model routes are enabled." : "Model routes are disabled for the public site."}</p>
            <p>
              {status.models.hasServerOpenAiKey
                ? "Server OpenAI key configured."
                : "No server OpenAI key configured."}
            </p>
          </StatusCard>

          {status.providerAccess && (
            <StatusCard title="Provider Access" ok={!status.providerAccess.userProviderKeysAccepted}>
              <p>
                {status.providerAccess.userProviderKeysAccepted
                  ? "User provider keys are accepted by this deployment."
                  : "User provider keys are not accepted by this deployment."}
              </p>
              <p>Mode: {status.providerAccess.modelAccessMode}</p>
              <p>Approval backend: {status.providerAccess.approvalBackend}</p>
              <p>{status.providerAccess.adminTestLogin}</p>
              <p>{status.providerAccess.invitedUserFlow}</p>
              <p>{status.providerAccess.userOwnedModelAccess}</p>
            </StatusCard>
          )}

          <StatusCard title="Local MCP Bridge" ok={status.mcp.local?.available ?? false}>
            <p>Command: {status.mcp.local?.command ?? "nepsiscgn-mcp"}</p>
            <p>Transport: {status.mcp.local?.transport ?? "stdio"}</p>
            <p>
              {status.mcp.local?.modelKeysRequired === false
                ? "No model provider API key collected by NepsisCGN."
                : "Model key requirement unknown."}
            </p>
            <p>{status.mcp.local?.lifecycle ?? "Stateless packet-in/packet-out."}</p>
            <p>Discovery: {(status.mcp.discoverableMethods ?? ["initialize", "tools/list"]).join(", ")}</p>
            <p>Operator packet tools: {(status.mcp.operatorTools ?? []).join(", ") || "none"}</p>
          </StatusCard>

          <StatusCard title="Hosted MCP Endpoint" ok={status.mcp.hosted?.available ?? status.mcp.available}>
            <p>MCP endpoint: {status.mcp.hosted?.endpoint ?? status.mcp.endpoint ?? "/mcp"}</p>
            <p>
              {status.mcp.hosted?.deferred
                ? "Deferred until the backend endpoint is configured."
                : "Hosted MCP endpoint is reachable."}
            </p>
            <p>
              {status.mcp.hosted?.requiresCapabilityToken === true
                ? "Tool calls require a Nepsis capability token."
                : "Tool-call auth requirement unknown."}
            </p>
            <p>
              {status.mcp.hosted?.capabilityTokenConfigured
                ? "Capability token hash configured."
                : "Capability token hash not configured."}
            </p>
            <p>
              {status.mcp.hosted?.modelKeysRequired === false
                ? "No model provider API key collected by NepsisCGN."
                : "Model key requirement unknown."}
            </p>
            <p>Protected tool calls: {(status.mcp.protectedTools ?? []).join(", ") || "none"}</p>
          </StatusCard>
        </div>
      )}
    </div>
  );
}
