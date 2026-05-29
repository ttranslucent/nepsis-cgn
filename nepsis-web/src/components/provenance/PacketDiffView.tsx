import type { ProvenancePacket } from "@/lib/provenance/types";

export function PacketDiffView({ packet }: { packet: ProvenancePacket }) {
  const diff = packet.diff;

  if (!diff?.hasPriorPacket) {
    return (
      <div className="rounded-lg border border-slate-800 bg-black/25 p-4 text-sm text-slate-300">
        No prior packet available for deterministic diff.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-800 bg-black/25 p-4">
        <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">Changed fields</div>
        {diff.changedFields.length > 0 ? (
          <div className="mt-3 space-y-2">
            {diff.changedFields.map((item) => (
              <div key={item.field} className="rounded-md border border-slate-800 bg-zinc-950/70 p-3">
                <div className="font-mono text-xs text-sky-100">{item.field}</div>
                <div className="mt-2 grid gap-2 text-xs md:grid-cols-2">
                  <div>
                    <div className="font-mono uppercase tracking-[0.12em] text-slate-500">Previous</div>
                    <div className="mt-1 break-words text-slate-400">{item.previous}</div>
                  </div>
                  <div>
                    <div className="font-mono uppercase tracking-[0.12em] text-slate-500">Current</div>
                    <div className="mt-1 break-words text-slate-100">{item.current}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-2 text-sm text-slate-400">No tracked fields changed.</div>
        )}
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <SummaryMetric label="Changed nodes" value={diff.changedNodeIds.join(", ") || "none"} />
        <SummaryMetric label="Changed constraints" value={diff.changedConstraintCount ? "yes" : "no"} />
        <SummaryMetric label="Changed outputs" value={diff.changedOutput ? "yes" : "no"} />
      </div>
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-black/25 p-3">
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm text-slate-100">{value}</div>
    </div>
  );
}
