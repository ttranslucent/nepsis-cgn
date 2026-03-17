"use client";

import { startTransition, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { LLM_CONNECTED_NOTICE_KEY, OPENAI_KEY_STORAGE_KEY } from "@/lib/clientStorage";

function maskKey(value: string): string {
  if (!value || value.length < 12) {
    return "stored";
  }
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

export default function SettingsPage() {
  const router = useRouter();
  const [apiKey, setApiKey] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      const stored = window.localStorage.getItem(OPENAI_KEY_STORAGE_KEY);
      if (stored) {
        startTransition(() => {
          setApiKey(stored);
          setHasKey(true);
        });
      }
    } catch {}
  }, []);

  function connectLlm() {
    if (typeof window === "undefined") return;
    const trimmed = apiKey.trim();
    if (!trimmed) return;
    try {
      window.localStorage.setItem(OPENAI_KEY_STORAGE_KEY, trimmed);
      window.localStorage.setItem(LLM_CONNECTED_NOTICE_KEY, "1");
    } catch {
      setMessage("Could not store key in this browser context.");
      return;
    }
    setApiKey(trimmed);
    setHasKey(true);
    setMessage("Connected. Redirecting to Engine workspace...");
    router.push("/engine?connected=1");
  }

  function disconnectLlm() {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.removeItem(OPENAI_KEY_STORAGE_KEY);
      window.localStorage.removeItem(LLM_CONNECTED_NOTICE_KEY);
    } catch {
      setMessage("Could not clear key in this browser context.");
      return;
    }
    setApiKey("");
    setHasKey(false);
    setMessage("LLM key removed from this browser.");
  }

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 md:px-6 md:py-12">
      <section className="grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
        <article className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-6 md:p-7">
          <div className="mb-3 flex items-center justify-between gap-3">
            <h1 className="text-2xl font-semibold">Connect Your Model Key</h1>
            <span
              className={`rounded-full px-3 py-1 text-xs font-semibold ${
                hasKey
                  ? "border border-emerald-500/50 bg-emerald-500/10 text-emerald-300"
                  : "border border-nepsis-border bg-black/20 text-nepsis-muted"
              }`}
            >
              {hasKey ? "Connected" : "Not connected"}
            </span>
          </div>

          <p className="text-sm text-nepsis-muted">
            Add an OpenAI API key to enable live calls in Playground and Engine. For MVP this key is stored locally in
            your browser.
          </p>

          <label className="mt-5 block text-xs uppercase tracking-[0.14em] text-nepsis-muted">OpenAI API Key</label>
          <input
            className="mt-2 w-full rounded-xl border border-nepsis-border bg-black/30 px-3 py-2.5 font-mono text-sm focus:border-nepsis-accent focus:outline-none"
            type="password"
            placeholder="sk-..."
            autoComplete="new-password"
            value={apiKey}
            onChange={(e) => {
              setApiKey(e.target.value);
              setMessage(null);
            }}
          />

          <div className="mt-4 flex flex-wrap gap-2">
            <button
              onClick={connectLlm}
              disabled={!apiKey.trim()}
              className="rounded-full bg-nepsis-accent px-4 py-2 text-sm font-semibold text-black transition hover:bg-nepsis-accentSoft disabled:opacity-60"
            >
              Connect LLM
            </button>
            {hasKey && (
              <>
                <button
                  onClick={() => router.push("/engine")}
                  className="rounded-full border border-nepsis-border px-4 py-2 text-sm transition hover:border-nepsis-accent"
                >
                  Open Engine
                </button>
                <button
                  onClick={disconnectLlm}
                  className="rounded-full border border-red-500/40 px-4 py-2 text-sm text-red-300 transition hover:border-red-400"
                >
                  Disconnect Key
                </button>
              </>
            )}
          </div>

          {message && <p className="mt-3 text-xs text-nepsis-muted">{message}</p>}
        </article>

        <aside className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-6 md:p-7">
          <h2 className="text-lg font-semibold">Current Browser State</h2>
          <div className="mt-4 space-y-3">
            <div className="rounded-xl border border-nepsis-border bg-black/20 p-3">
              <div className="text-xs text-nepsis-muted">Connection</div>
              <div className="mt-1 font-mono text-sm text-nepsis-text">{hasKey ? "active" : "inactive"}</div>
            </div>
            <div className="rounded-xl border border-nepsis-border bg-black/20 p-3">
              <div className="text-xs text-nepsis-muted">Stored key</div>
              <div className="mt-1 font-mono text-sm text-nepsis-accent">{hasKey ? maskKey(apiKey) : "none"}</div>
            </div>
            <div className="rounded-xl border border-nepsis-border bg-black/20 p-3 text-xs text-nepsis-muted">
              Use a non-production key for demos. Rotate it after public testing.
            </div>
          </div>
        </aside>
      </section>
    </div>
  );
}
