"use client";

import { useEffect, useState } from "react";

import { clearLegacyOpenAiKey } from "@/lib/clientStorage";
import { publicSiteMode } from "@/lib/publicMode";

export default function SettingsPage() {
  const [message, setMessage] = useState<string | null>(null);
  const publicMode = publicSiteMode();

  useEffect(() => {
    queueMicrotask(() => {
      if (clearLegacyOpenAiKey()) {
        setMessage("Removed a legacy browser-stored OpenAI key from this browser.");
      }
    });
  }, []);

  function clearLegacyKey() {
    const removed = clearLegacyOpenAiKey();
    setMessage(
      removed
        ? "Removed a legacy browser-stored OpenAI key from this browser."
        : "No legacy browser-stored OpenAI key was present.",
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 md:px-6 md:py-12">
      <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-6 md:p-7">
        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-nepsis-muted">
          {publicMode ? "Public site mode" : "Provider access"}
        </div>
        <h1 className="mt-3 text-2xl font-semibold">Model Access</h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-nepsis-muted">
          NepsisCGN does not collect or store user provider API keys in the browser. Public MVP runs are deterministic
          and model-free. Private operator model assistance uses reviewed server-side credentials. User-owned model
          accounts should connect through MCP-capable hosts such as ChatGPT, Codex, Claude, or Gemini.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <a
            href="/mvp"
            className="rounded-full bg-nepsis-accent px-4 py-2 text-sm font-semibold text-black transition hover:bg-nepsis-accentSoft"
          >
            Run MVP Demo
          </a>
          <a
            href="/status"
            className="rounded-full border border-nepsis-border px-4 py-2 text-sm transition hover:border-nepsis-accent"
          >
            System Status
          </a>
          <a
            href="/login"
            className="rounded-full border border-nepsis-border px-4 py-2 text-sm transition hover:border-nepsis-accent"
          >
            Operator Login
          </a>
          <button
            type="button"
            onClick={clearLegacyKey}
            className="rounded-full border border-red-500/40 px-4 py-2 text-sm text-red-300 transition hover:border-red-400"
          >
            Clear Legacy Browser Key
          </button>
        </div>
        {message && <p className="mt-3 text-xs text-nepsis-muted">{message}</p>}
      </section>
    </div>
  );
}
