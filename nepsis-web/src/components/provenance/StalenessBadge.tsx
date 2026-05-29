import type { ProvenanceNode } from "@/lib/provenance/types";

export function StalenessBadge({ node }: { node: ProvenanceNode }) {
  const driftSignals = Array.isArray(node.metadata?.driftSignals) ? node.metadata?.driftSignals : [];
  const hasDrift = node.stale || driftSignals.length > 0;

  if (!hasDrift) {
    return null;
  }

  return (
    <span className="inline-flex items-center rounded border border-amber-300/35 bg-amber-400/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-[0.1em] text-amber-100">
      Drift
    </span>
  );
}
