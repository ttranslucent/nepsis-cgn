"use client";

import { AnimatePresence } from "motion/react";
import { forwardRef } from "react";

import { formatTelemetryDensity } from "@/components/provenance/format";
import { ProvenanceMicroCard } from "@/components/provenance/ProvenanceMicroCard";
import { StalenessBadge } from "@/components/provenance/StalenessBadge";
import type { ProvenanceNode as ProvenanceNodeModel } from "@/lib/provenance/types";

const STATE_CLASS: Record<NonNullable<ProvenanceNodeModel["state"]>, string> = {
  active: "border-slate-500/55 bg-slate-900/80 text-slate-100",
  stale: "border-slate-700/60 bg-slate-950/70 text-slate-400 opacity-75",
  contradiction: "border-red-300/65 bg-red-950/30 text-red-50",
  collapsed: "border-amber-300/65 bg-amber-950/25 text-amber-50",
  repair: "border-sky-300/65 bg-sky-950/30 text-sky-50",
  final: "border-zinc-300/55 bg-zinc-900/85 text-zinc-50",
};

function metadataText(node: ProvenanceNodeModel, key: string): string {
  const value = node.metadata?.[key];
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => String(item)).join("; ") : "None";
  }
  return value === undefined || value === null ? "n/a" : JSON.stringify(value);
}

export const ProvenanceNode = forwardRef<
  HTMLButtonElement,
  {
    node: ProvenanceNodeModel;
    selected: boolean;
    active: boolean;
    dimmed: boolean;
    onSelect: () => void;
    onActivateCard: () => void;
    onDeactivateCard: () => void;
    onOpenAudit: () => void;
    onReplay: () => void;
  }
>(function ProvenanceNode(
  { node, selected, active, dimmed, onSelect, onActivateCard, onDeactivateCard, onOpenAudit, onReplay },
  ref,
) {
  const state = node.state ?? "active";
  const deterministicCallId = metadataText(node, "deterministicCallId");
  const summary = metadataText(node, "summary");

  return (
    <div className={`relative shrink-0 transition-opacity ${dimmed ? "opacity-35" : "opacity-100"}`}>
      <button
        ref={ref}
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        onFocus={onActivateCard}
        onBlur={onDeactivateCard}
        onMouseEnter={onActivateCard}
        onMouseLeave={onDeactivateCard}
        className={`h-56 w-48 rounded-lg border p-3 text-left shadow-sm transition focus:outline-none focus:ring-2 focus:ring-sky-300/60 ${STATE_CLASS[state]} ${
          selected ? "ring-2 ring-sky-300/70" : ""
        }`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-current/70">{node.stage}</div>
          <StalenessBadge node={node} />
        </div>
        <h3 className="mt-2 text-base font-semibold leading-tight">{node.label}</h3>
        <div className="mt-2 inline-flex rounded border border-current/25 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em]">
          {state}
        </div>
        <p className="mt-3 line-clamp-4 text-xs leading-relaxed text-slate-200/90">{summary}</p>
        <div className="mt-3 grid grid-cols-2 gap-2 font-mono text-[10px] text-slate-300">
          <div>
            <div className="uppercase tracking-[0.1em] text-slate-500">Density</div>
            <div className="mt-1">{formatTelemetryDensity(node.contradictionDensity)}</div>
          </div>
          <div>
            <div className="uppercase tracking-[0.1em] text-slate-500">Conf</div>
            <div className="mt-1">{Math.round((node.confidence ?? 0) * 100)}%</div>
          </div>
        </div>
        <div className="mt-3 truncate rounded border border-black/30 bg-black/25 px-2 py-1 font-mono text-[10px] text-sky-100">
          {deterministicCallId}
        </div>
      </button>

      <AnimatePresence>
        {active ? (
          <ProvenanceMicroCard node={node} onOpenAudit={onOpenAudit} onReplay={onReplay} />
        ) : null}
      </AnimatePresence>
    </div>
  );
});
