"use client";

import { useState } from "react";

type PackOption = {
  id: "jailing_jingall" | "utf8_clean";
  label: string;
};

const PACK_OPTIONS: PackOption[] = [
  { id: "jailing_jingall", label: "Jailing/Jingall" },
  { id: "utf8_clean", label: "UTF-8 Clean" },
];

type ProtoEvaluation = {
  packId: string;
  packName: string;
  distance: number;
  isValid: boolean;
  violations: { code: string; severity: string; message: string; metadata?: Record<string, unknown> | null }[];
};

export default function PlaygroundPage() {
  const [prompt, setPrompt] = useState("");
  const [packId, setPackId] = useState<PackOption["id"]>("jailing_jingall");
  const [rawOutput, setRawOutput] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<ProtoEvaluation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runNepsis() {
    setLoading(true);
    setError(null);
    setRawOutput(null);
    setEvaluation(null);

    if (!prompt.trim()) {
      setLoading(false);
      setError("Please enter a prompt before running NepsisCGN.");
      return;
    }

    try {
      const res = await fetch("/api/playground-nepsis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, packId }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.error || "Run failed.");
        return;
      }
      setRawOutput(data.rawOutput ?? "");
      setEvaluation(data.evaluation ?? null);
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
        <div className="mb-2 text-xs text-nepsis-muted">
          Status: Ready – NepsisCGN will evaluate the selected constraint pack against every run.
        </div>
        <p className="mb-4 text-sm text-nepsis-muted">
          Enter a prompt, run your LLM through NepsisCGN, and inspect the output and constraint
          evaluation side-by-side.
        </p>

        <label className="mb-3 block text-xs font-medium text-nepsis-muted">
          Constraint pack
          <select
            className="mt-1 w-full rounded-xl border border-nepsis-border bg-black/30 px-3 py-2 text-sm focus:border-nepsis-accent focus:outline-none"
            value={packId}
            onChange={(event) => setPackId(event.target.value as PackOption["id"])}
          >
            {PACK_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <textarea
          className="mb-3 min-h-[100px] w-full rounded-xl border border-nepsis-border bg-black/30 px-3 py-2 text-sm focus:border-nepsis-accent focus:outline-none"
          placeholder="Type a puzzle or command here..."
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
        />

        <button
          onClick={runNepsis}
          className="mt-2 rounded-full bg-nepsis-accent px-4 py-2 text-sm font-medium text-black hover:bg-nepsis-accentSoft focus:outline-none focus:ring-2 focus:ring-nepsis-accent"
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
            {rawOutput ?? "No output yet."}
          </div>
        </div>
        <div className="flex-1 rounded-xl border border-nepsis-border bg-nepsis-panel p-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-sm font-semibold">NepsisCGN Evaluation</h2>
          </div>
          {evaluation ? (
            <div className="space-y-2 text-xs text-nepsis-muted">
              <div>
                <span className="font-semibold">Pack:</span> {evaluation.packName}
              </div>
              <div>
                <span className="font-semibold">Valid:</span> {evaluation.isValid ? "Yes" : "No"}
              </div>
              <div>
                <span className="font-semibold">Distance:</span>{" "}
                {evaluation.distance?.toFixed?.(3) ?? evaluation.distance}
              </div>
              <div>
                <span className="font-semibold">Violations:</span>
                {evaluation.violations && evaluation.violations.length > 0 ? (
                  <ul className="ml-5 mt-1 list-disc">
                    {evaluation.violations.map((v, index) => (
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
