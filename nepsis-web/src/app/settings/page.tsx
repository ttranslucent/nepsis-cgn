"use client";

import { startTransition, useEffect, useState } from "react";

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem("nepsis_openai_key");
    if (stored) {
      startTransition(() => {
        setApiKey(stored);
        setHasKey(true);
      });
    }
  }, []);

  function saveKey() {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("nepsis_openai_key", apiKey);
    setHasKey(true);
    setMessage("API key saved locally in this browser.");
  }

  return (
    <div className="mx-auto max-w-xl px-4 py-12">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="text-xl font-semibold">LLM Connection</h1>
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

      <p className="mb-6 text-sm text-nepsis-muted">
        For now, NepsisCGN uses your own OpenAI API key. It is stored locally in your browser for
        this MVP.
      </p>

      <label className="mb-1 block text-xs">OpenAI API Key</label>
      <input
        className="mb-3 w-full rounded-lg border border-nepsis-border bg-black/30 px-3 py-2 font-mono text-sm focus:border-nepsis-accent focus:outline-none"
        type="password"
        placeholder="sk-..."
        autoComplete="new-password"
        value={apiKey}
        onChange={(e) => {
          setApiKey(e.target.value.trim());
          setMessage(null);
        }}
      />

      <button
        onClick={saveKey}
        disabled={!apiKey}
        className="rounded-full bg-nepsis-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-60"
      >
        Save key
      </button>

      {message && <p className="mt-3 text-xs text-nepsis-muted">{message}</p>}
    </div>
  );
}
