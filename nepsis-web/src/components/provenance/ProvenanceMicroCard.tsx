"use client";

import { motion, useReducedMotion } from "motion/react";

import { formatTelemetryDensity } from "@/components/provenance/format";
import type { ProvenanceNode } from "@/lib/provenance/types";

function textList(value: unknown): string {
  if (!Array.isArray(value) || value.length === 0) {
    return "None";
  }
  return value.map((item) => String(item)).join("; ");
}

function metadataText(node: ProvenanceNode, key: string): string {
  const value = node.metadata?.[key];
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return value === undefined || value === null ? "n/a" : JSON.stringify(value);
}

export function ProvenanceMicroCard({
  node,
  onOpenAudit,
  onReplay,
}: {
  node: ProvenanceNode;
  onOpenAudit: () => void;
  onReplay: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const deterministicCallId = metadataText(node, "deterministicCallId");

  return (
    <motion.div
      initial={reduceMotion ? false : { opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      exit={reduceMotion ? { opacity: 0 } : { opacity: 0, y: 4 }}
      transition={{ duration: 0.16 }}
      className="absolute left-0 top-[calc(100%+0.5rem)] z-30 w-[20rem] rounded-lg border border-slate-500/40 bg-zinc-950 p-3 text-left shadow-2xl shadow-black/40"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-400">{node.stage}</div>
          <div className="mt-1 text-sm font-semibold text-slate-50">{node.label}</div>
        </div>
        <div className="text-right font-mono text-[10px] text-slate-400">
          <div>{node.version ?? "unversioned"}</div>
          <div>{Math.round((node.confidence ?? 0) * 100)}% confidence</div>
        </div>
      </div>

      <div className="mt-2 rounded border border-slate-700/70 bg-black/25 px-2 py-1.5 font-mono text-[11px] text-sky-100">
        {deterministicCallId}
      </div>

      <dl className="mt-3 grid gap-2 text-xs">
        <div>
          <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">Inputs used</dt>
          <dd className="mt-0.5 line-clamp-2 text-slate-200">{textList(node.metadata?.inputsUsed)}</dd>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">Constraints</dt>
            <dd className="mt-0.5 text-slate-200">{metadataText(node, "constraintStatus")}</dd>
          </div>
          <div>
            <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">Density</dt>
            <dd className="mt-0.5 text-slate-200">{formatTelemetryDensity(node.contradictionDensity)}</dd>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">STILL</dt>
            <dd className="mt-0.5 text-slate-200">{metadataText(node, "stillStatus")}</dd>
          </div>
          <div>
            <dt className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">Timestamp</dt>
            <dd className="mt-0.5 truncate text-slate-200">{metadataText(node, "timestamp")}</dd>
          </div>
        </div>
      </dl>

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          onClick={onOpenAudit}
          className="rounded-md border border-sky-300/40 px-2 py-1 text-xs font-semibold text-sky-100 transition hover:border-sky-200 focus:outline-none focus:ring-2 focus:ring-sky-300/50"
        >
          Open audit trail
        </button>
        <button
          type="button"
          onClick={onReplay}
          className="rounded-md border border-slate-600 px-2 py-1 text-xs font-semibold text-slate-200 transition hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-slate-300/40"
        >
          Replay lineage
        </button>
      </div>
    </motion.div>
  );
}
