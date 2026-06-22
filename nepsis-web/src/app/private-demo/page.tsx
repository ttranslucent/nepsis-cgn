"use client";

import { FormEvent, useEffect, useState } from "react";
import { OperatorAccessNotice } from "@/app/components/OperatorAccessNotice";
import { PrivateDemoPacketView } from "@/components/private-demo/PrivateDemoPacketView";
import {
  EngineClientError,
  engineClient,
  type NepsisPrivateDemoRuntimePacket,
} from "@/lib/engineClient";

type AuthState = {
  authenticated: boolean;
  engineControlAllowed: boolean;
  user: string | null;
};

const DEFAULT_PROMPT =
  "No PHI. Source token is JINGALL and the candidate answer collapses to JAILING; preserve the mismatch and show the packet audit.";

async function readAuthState(): Promise<AuthState> {
  const response = await fetch("/api/auth/session", { cache: "no-store" });
  if (!response.ok) {
    return { authenticated: false, engineControlAllowed: false, user: null };
  }
  return response.json();
}

export default function PrivateDemoPage() {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [caseId, setCaseId] = useState("jailing");
  const [prompt, setPrompt] = useState(DEFAULT_PROMPT);
  const [noPhiAcknowledged, setNoPhiAcknowledged] = useState(false);
  const [packet, setPacket] = useState<NepsisPrivateDemoRuntimePacket | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let mounted = true;
    readAuthState()
      .then((nextAuth) => {
        if (mounted) setAuth(nextAuth);
      })
      .catch(() => {
        if (mounted) setAuth({ authenticated: false, engineControlAllowed: false, user: null });
      });
    return () => {
      mounted = false;
    };
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setPacket(null);

    if (!noPhiAcknowledged) {
      setError("Confirm the prompt contains no PHI or PII before running the private demo.");
      return;
    }

    const trimmedPrompt = prompt.trim();
    if (trimmedPrompt.length < 3) {
      setError("Enter a no-PHI prompt of at least 3 characters.");
      return;
    }

    setRunning(true);
    try {
      const result = await engineClient.runPrivateDemo({
        case_id: caseId.trim() || "custom",
        prompt: trimmedPrompt,
        no_phi_acknowledged: true,
        thread_id: `private-demo-${Date.now()}`,
        user_id: auth?.user ?? undefined,
      });
      setPacket(result);
    } catch (caught) {
      if (caught instanceof EngineClientError) {
        setError(caught.detail ? `${caught.message}: ${String(caught.detail)}` : caught.message);
      } else {
        setError((caught as Error)?.message ?? "Private demo request failed.");
      }
    } finally {
      setRunning(false);
    }
  }

  if (!auth) {
    return <OperatorAccessNotice checking />;
  }

  if (!auth.engineControlAllowed) {
    return (
      <OperatorAccessNotice
        title="Private demo access required"
        message="The private demo runs authenticated no-PHI prompts through the operator-packet backend. Sign in with an approved operator email to use this path."
      />
    );
  }

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-8 md:px-6 md:py-10">
      <section className="space-y-4">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-nepsis-muted">
            Authenticated private demo
          </div>
          <h1 className="mt-2 text-2xl font-semibold md:text-3xl">Private Demo Runtime</h1>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-nepsis-muted">
            Submit no-PHI prompts to the private operator-packet runtime and inspect the packet artifact. Public MVP behavior remains separate and deterministic.
          </p>
        </div>

        <form onSubmit={onSubmit} className="rounded-lg border border-nepsis-border bg-nepsis-panel p-4 md:p-5">
          <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_12rem]">
            <label className="block">
              <span className="text-sm font-medium">No-PHI prompt</span>
              <textarea
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
                rows={8}
                className="mt-2 w-full rounded-md border border-nepsis-border bg-nepsis-bg p-3 text-sm text-nepsis-text outline-none focus:border-nepsis-accent"
              />
            </label>

            <label className="block">
              <span className="text-sm font-medium">Case ID</span>
              <input
                value={caseId}
                onChange={(event) => setCaseId(event.target.value)}
                className="mt-2 w-full rounded-md border border-nepsis-border bg-nepsis-bg p-3 text-sm text-nepsis-text outline-none focus:border-nepsis-accent"
              />
            </label>
          </div>

          <label className="mt-4 flex gap-3 rounded-md border border-nepsis-border bg-nepsis-bg/70 p-3 text-sm">
            <input
              type="checkbox"
              checked={noPhiAcknowledged}
              onChange={(event) => setNoPhiAcknowledged(event.target.checked)}
              className="mt-1 h-4 w-4"
            />
            <span>I confirm this prompt contains no PHI, no PII, and no real patient-identifying details.</span>
          </label>

          {error && (
            <div role="alert" className="mt-4 rounded-md border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-100">
              {error}
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="submit"
              disabled={running}
              className="rounded-md bg-nepsis-accent px-4 py-2 text-sm font-semibold text-black transition hover:bg-nepsis-accentSoft disabled:cursor-not-allowed disabled:opacity-60"
            >
              {running ? "Running..." : "Run Private Demo"}
            </button>
            <span className="text-xs text-nepsis-muted">Signed in as {auth.user ?? "operator"}</span>
          </div>
        </form>
      </section>

      {packet && (
        <div className="mt-6">
          <PrivateDemoPacketView packet={packet} />
        </div>
      )}
    </main>
  );
}
