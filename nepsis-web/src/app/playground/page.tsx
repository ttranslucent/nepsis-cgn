"use client";

import { useState } from "react";

type CgnResult = {
  valid: boolean;
  distance: number;
  violations: unknown[];
};

export default function PlaygroundPage() {
  const [prompt, setPrompt] = useState("");
  const [rawAnswer, setRawAnswer] = useState<string | null>(null);
  const [cgn, setCgn] = useState<CgnResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runNepsis() {
    setLoading(true);
    setError(null);
    setRawAnswer(null);
    setCgn(null);

    const apiKey = window.localStorage.getItem("nepsis_openai_key");
    if (!apiKey) {
      setLoading(false);
      setError("No OpenAI API key found. Add one in Settings.");
      return;
    }

    try {
      const res = await fetch("/api/run-with-nepsis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, apiKey }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || "Run failed.");
        return;
      }
      setRawAnswer(data.rawAnswer);
      setCgn(data.cgn);
    } catch (err) {
      console.error(err);
      setError("Network error – please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex h-full flex-col gap-4 px-4 py-6">
      <div className="mx-auto w-full max-w-4xl">
        <h1 className="mb-2 text-xl font-semibold">NepsisCGN Playground</h1>
        <p className="mb-4 text-sm text-nepsis-muted">
          Enter a prompt, run your LLM through NepsisCGN, and inspect the output and constraint
          evaluation side-by-side.
        </p>

        <textarea
          className="mb-3 min-h-[100px] w-full rounded-xl border border-nepsis-border bg-black/30 px-3 py-2 text-sm focus:border-nepsis-accent focus:outline-none"
          placeholder="Type a puzzle or command here..."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />

        <button
          onClick={runNepsis}
          disabled={loading || !prompt}
          className="rounded-full bg-nepsis-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-60"
        >
          {loading ? "Running..." : "Run with NepsisCGN"}
        </button>

        {error && <p className="mt-3 text-xs text-red-400">{error}</p>}
      </div>

      <div className="mx-auto mt-6 flex w-full max-w-6xl flex-col gap-4 md:flex-row">
        <div className="flex-1 rounded-xl border border-nepsis-border bg-nepsis-panel p-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">Raw LLM Output</h2>
          </div>
          <div className="whitespace-pre-wrap text-xs text-nepsis-muted">
            {rawAnswer ?? "No output yet."}
          </div>
        </div>
        <div className="flex-1 rounded-xl border border-nepsis-border bg-nepsis-panel p-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">NepsisCGN Evaluation</h2>
          </div>
          {cgn ? (
            <div className="space-y-2 text-xs text-nepsis-muted">
              <div>
                <span className="font-semibold">Valid:</span> {cgn.valid ? "Yes" : "No"}
              </div>
              <div>
                <span className="font-semibold">Distance:</span> {cgn.distance?.toFixed?.(3) ?? cgn.distance}
              </div>
              <div>
                <span className="font-semibold">Violations:</span>
                {cgn.violations && cgn.violations.length > 0 ? (
                  <ul className="ml-5 mt-1 list-disc">
                    {cgn.violations.map((v, index) => (
                      <li key={index}>{JSON.stringify(v)}</li>
                    ))}
                  </ul>
                ) : (
                  <span> none</span>
                )}
              </div>
            </div>
          ) : (
            <p className="text-xs text-nepsis-muted">No evaluation yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}
