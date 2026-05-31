"use client";

import { useEffect, useState } from "react";

import { getStoredOpenAiKey, hasStoredOpenAiKey } from "@/lib/clientStorage";
import { withCsrfHeader } from "@/lib/csrfClient";
import { publicSiteMode } from "@/lib/publicMode";

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
  const [hasBrowserKey, setHasBrowserKey] = useState<boolean | null>(null);
  const [hasServerKey, setHasServerKey] = useState<boolean | null>(null);
  const publicMode = publicSiteMode();
  const keyReady = hasBrowserKey === true || hasServerKey === true;

  useEffect(() => {
    setHasBrowserKey(hasStoredOpenAiKey());
    let cancelled = false;
    async function loadKeyState() {
      try {
        const res = await fetch("/api/playground-nepsis", { method: "GET" });
        const data = await res.json();
        if (!cancelled) {
          setHasServerKey(Boolean(data.hasServerKey));
        }
      } catch {
        if (!cancelled) {
          setHasServerKey(false);
        }
      }
    }
    void loadKeyState();
    return () => {
      cancelled = true;
    };
  }, []);

  async function runNepsis() {
    setLoading(true);
    setError(null);
    setRawOutput(null);
    setEvaluation(null);

    if (publicMode) {
      setLoading(false);
      setError("Model playground calls are disabled on the public site.");
      return;
    }

    if (!prompt.trim()) {
      setLoading(false);
      setError("Please enter a prompt before running NepsisCGN.");
      return;
    }

    if (!keyReady) {
      setLoading(false);
      setError("OpenAI key required. Add a browser-local key in Settings or configure a server-side key.");
      return;
    }

    try {
      const apiKey = getStoredOpenAiKey();
      const res = await fetch("/api/playground-nepsis", {
        method: "POST",
        headers: withCsrfHeader({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          prompt,
          packId,
          apiKey: apiKey ?? undefined,
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || data.error || "Run failed.");
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

  if (publicMode) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-8 md:px-6 md:py-12">
        <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-6 md:p-7">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-nepsis-muted">Operator tool</div>
          <h1 className="mt-3 text-2xl font-semibold">Playground locked</h1>
          <p className="mt-3 text-sm leading-6 text-nepsis-muted">
            Model playground calls are disabled on the public site, so visitors cannot use an operator key or paste
            their own key into a shared deployment.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <a
              href="/mvp"
              className="rounded-full bg-nepsis-accent px-4 py-2 text-sm font-semibold text-black transition hover:bg-nepsis-accentSoft"
            >
              Run MVP Demo
            </a>
            <a
              href="/login"
              className="rounded-full border border-nepsis-border px-4 py-2 text-sm transition hover:border-nepsis-accent"
            >
              Operator Login
            </a>
            <a
              href="/status"
              className="rounded-full border border-nepsis-border px-4 py-2 text-sm transition hover:border-nepsis-accent"
            >
              System Status
            </a>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 px-4 py-6">
      <div className="mx-auto w-full max-w-4xl">
        <h1 className="mb-2 text-xl font-semibold">NepsisCGN Playground</h1>
        <div className="mb-2 text-xs text-nepsis-muted">
          Status: Ready – NepsisCGN will evaluate the selected constraint pack against every run.
        </div>
        <div className="mb-2 text-xs text-nepsis-muted">
          OpenAI key:{" "}
          {hasBrowserKey === null || hasServerKey === null
            ? "checking..."
            : keyReady
              ? hasBrowserKey
                ? "browser local key available"
                : "server key configured"
              : "missing"}
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
          disabled={loading || !keyReady}
          className="mt-2 rounded-full bg-nepsis-accent px-4 py-2 text-sm font-medium text-black hover:bg-nepsis-accentSoft focus:outline-none focus:ring-2 focus:ring-nepsis-accent disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? "Running..." : "Run with NepsisCGN"}
        </button>
        {!keyReady && hasBrowserKey !== null && hasServerKey !== null && (
          <a href="/settings" className="ml-3 text-xs font-semibold text-nepsis-accent hover:underline">
            Open Settings
          </a>
        )}

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
