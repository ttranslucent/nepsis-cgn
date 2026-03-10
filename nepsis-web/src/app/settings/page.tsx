"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { LLM_CONNECTED_NOTICE_KEY, OPENAI_KEY_STORAGE_KEY } from "@/lib/clientStorage";

export default function SettingsPage() {
  const router = useRouter();
  const [apiKey, setApiKey] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const stored = window.localStorage.getItem(OPENAI_KEY_STORAGE_KEY);
      if (stored) {
        setApiKey(stored);
        setHasKey(true);
      }
    } catch {
      setHasKey(false);
    }
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

  return (
    <div className="mx-auto max-w-xl px-4 py-10">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Connect Your LLM</h1>
        <span
          className={`rounded-full px-3 py-1 text-xs ${
            hasKey
              ? "border border-green-500/50 text-green-400"
              : "border border-nepsis-border text-nepsis-muted"
          }`}
        >
          {hasKey ? "Connected ✓" : "Not connected"}
        </span>
      </div>

      <p className="mb-2 text-sm text-nepsis-muted">
        Paste an OpenAI API key to enable live model calls in Playground and Engine.
      </p>
      <p className="mb-6 text-xs text-nepsis-muted">
        This key is stored only in your browser for this MVP.
      </p>

      <label className="mb-1 block text-xs">OpenAI API Key</label>
      <input
        className="mb-3 w-full rounded-lg border border-nepsis-border bg-black/30 px-3 py-2 font-mono text-sm focus:border-nepsis-accent focus:outline-none"
        type="password"
        placeholder="sk-..."
        autoComplete="new-password"
        value={apiKey}
        onChange={(e) => {
          setApiKey(e.target.value);
          setMessage(null);
        }}
      />

      <button
        onClick={connectLlm}
        disabled={!apiKey.trim()}
        className="rounded-full bg-nepsis-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-60"
      >
        Connect LLM
      </button>
      {hasKey && (
        <button
          onClick={() => router.push("/engine")}
          className="ml-2 rounded-full border border-nepsis-border px-4 py-2 text-sm hover:border-nepsis-accent"
        >
          Open Engine
        </button>
      )}

      {message && <p className="mt-3 text-xs text-nepsis-muted">{message}</p>}
    </div>
  );
}
