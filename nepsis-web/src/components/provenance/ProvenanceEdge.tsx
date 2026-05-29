import type { ProvenanceEdge as ProvenanceEdgeModel } from "@/lib/provenance/types";

const EDGE_STYLE: Record<ProvenanceEdgeModel["type"], { path: string; text: string; dash?: string }> = {
  causal: { path: "stroke-slate-300/70", text: "text-slate-300" },
  derived: { path: "stroke-slate-400/45", text: "text-slate-400", dash: "5 5" },
  override: { path: "stroke-amber-300/80", text: "text-amber-100" },
  repair: { path: "stroke-sky-300/85", text: "text-sky-100" },
};

export function ProvenanceEdge({ edge }: { edge: ProvenanceEdgeModel }) {
  const style = EDGE_STYLE[edge.type];
  const strokeClass = edge.stale ? "stroke-slate-600/60" : style.path;
  const textClass = edge.stale ? "text-slate-500" : style.text;

  return (
    <div className="flex min-w-20 shrink-0 flex-col items-center justify-center px-1" aria-hidden="true">
      <svg className="h-8 w-20 overflow-visible" viewBox="0 0 80 32" fill="none">
        <path
          d="M2 16H72"
          className={strokeClass}
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeDasharray={edge.stale ? "3 6" : style.dash}
        />
        <path d="M70 11L77 16L70 21" className={strokeClass} strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      {edge.label ? (
        <span className={`max-w-20 truncate font-mono text-[10px] uppercase tracking-[0.1em] ${textClass}`}>
          {edge.label}
        </span>
      ) : null}
    </div>
  );
}
