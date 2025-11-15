"use client";

import { startTransition, useEffect, useState } from "react";

export default function SettingsPage() {
  const [apiKey, setApiKey] = useState("");

  useEffect(() => {
    const stored = window.localStorage.getItem("nepsis_openai_key");
    if (stored) {
      startTransition(() => setApiKey(stored));
    }
  }, []);

  function saveKey() {
    window.localStorage.setItem("nepsis_openai_key", apiKey);
    alert("API key saved locally in this browser.");
  }

  return (
    <div className="mx-auto max-w-xl px-4 py-12">
      <h1 className="mb-3 text-xl font-semibold">LLM Connection</h1>
      <p className="mb-6 text-sm text-nepsis-muted">
        For now, NepsisCGN uses your own OpenAI API key. It is stored locally in
        your browser for this MVP.
      </p>
      <label className="mb-1 block text-xs">OpenAI API Key</label>
      <input
        className="mb-3 w-full rounded-lg border border-nepsis-border bg-black/30 px-3 py-2 text-sm font-mono"
        type="password"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        placeholder="sk-..."
      />
      <button
        onClick={saveKey}
        className="rounded-full bg-nepsis-accent px-4 py-2 text-sm font-medium text-black"
      >
        Save key
      </button>
    </div>
  );
}
