"use client";

import { useState } from "react";

type Evaluation = {
  packId: string;
  packName: string;
  distance: number;
  isValid: boolean;
  violations: { id: string; severity: string; description: string }[];
};

const PACK_OPTIONS = [
  {
    id: "jailing_jingall",
    label: "Jailing ↔ Jingall",
    example: {
      name_correct: true,
      story_consistent: false,
      explanation_quality: 0.4,
    },
  },
  {
    id: "utf8_clean",
    label: "UTF-8 Clean",
    example: {
      valid_utf8: true,
      has_invisible_chars: false,
      format_ok: true,
    },
  },
  {
    id: "terminal_bench",
    label: "Terminal Bench",
    example: {
      tests_passed: 0.75,
      banned_commands_used: false,
      steps_taken: 37,
      timeout_or_crash: false,
      file_corruption: false,
      idempotent: false,
      final_output_utf8_valid: true,
      final_output_has_invisibles: true,
    },
  },
];

const pretty = (value: unknown) => JSON.stringify(value, null, 2);

export default function ProtoPuzzlePage() {
  const [packId, setPackId] = useState(PACK_OPTIONS[0].id);
  const [stateJson, setStateJson] = useState(pretty(PACK_OPTIONS[0].example));
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  function handlePackChange(value: string) {
    setPackId(value);
    const preset = PACK_OPTIONS.find((option) => option.id === value);
    if (preset) {
      setStateJson(pretty(preset.example));
    }
    setEvaluation(null);
    setError(null);
  }

  async function runEvaluation() {
    setLoading(true);
    setError(null);
    try {
      const parsed = JSON.parse(stateJson);
      const res = await fetch("/api/proto-puzzle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ packId, state: parsed }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Evaluation failed");
      }
      setEvaluation(data);
    } catch (err) {
      console.error(err);
      setEvaluation(null);
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-8">
      <div>
        <h1 className="mb-1 text-2xl font-semibold">Proto Puzzle Manifold</h1>
        <p className="text-sm text-nepsis-muted">
          Pick a constraint pack, provide state JSON, and run it through the proto manifold.
        </p>
      </div>

      <div className="rounded-xl border border-nepsis-border bg-nepsis-panel p-4">
        <label className="mb-2 block text-xs uppercase tracking-wide text-nepsis-muted">Constraint pack</label>
        <select
          className="w-full rounded-lg border border-nepsis-border bg-black/30 px-3 py-2 text-sm focus:border-nepsis-accent focus:outline-none"
          value={packId}
          onChange={(event) => handlePackChange(event.target.value)}
        >
          {PACK_OPTIONS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <div className="rounded-xl border border-nepsis-border bg-nepsis-panel p-4">
        <label className="mb-2 block text-xs uppercase tracking-wide text-nepsis-muted">State JSON</label>
        <textarea
          className="h-48 w-full rounded-lg border border-nepsis-border bg-black/30 px-3 py-2 text-sm font-mono focus:border-nepsis-accent focus:outline-none"
          value={stateJson}
          onChange={(event) => setStateJson(event.target.value)}
        />
        <button
          onClick={runEvaluation}
          disabled={loading}
          className="mt-3 rounded-full bg-nepsis-accent px-4 py-2 text-sm font-medium text-black disabled:opacity-60"
        >
          {loading ? "Evaluating..." : "Evaluate"}
        </button>
        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
      </div>

      {evaluation && (
        <div className="rounded-xl border border-nepsis-border bg-nepsis-panel p-4">
          <div className="mb-2 flex items-center justify-between text-sm">
            <span className="font-semibold">Result</span>
            <span className={evaluation.isValid ? "text-green-400" : "text-red-400"}>
              {evaluation.isValid ? "Valid" : "Invalid"}
            </span>
          </div>
          <p className="text-sm text-nepsis-muted">Distance: {evaluation.distance}</p>
          <div className="mt-3">
            <p className="text-xs font-semibold uppercase tracking-wide text-nepsis-muted">
              Violations ({evaluation.violations.length})
            </p>
            {evaluation.violations.length === 0 ? (
              <p className="text-sm text-nepsis-muted">None</p>
            ) : (
              <ul className="mt-2 space-y-2 text-sm text-nepsis-muted">
                {evaluation.violations.map((violation) => (
                  <li key={violation.id} className="rounded border border-nepsis-border px-3 py-2">
                    <span className="font-semibold">[{violation.severity.toUpperCase()}]</span> {violation.description}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
