import type { ProvenancePacket } from "@/lib/provenance/types";

export function ReplayControls({ packet }: { packet: ProvenancePacket }) {
  const replayAttached = Boolean(packet.replay_token);

  return (
    <div className="rounded-xl border border-slate-800 bg-black/25 p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">Replay</div>
          <h3 className="mt-1 text-base font-semibold text-slate-50">Lineage replay hooks</h3>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-400">
            Public MVP replay is deterministic UI state only. No model call or operator runtime call is made here.
          </p>
        </div>
        <button
          type="button"
          disabled
          className="rounded-md border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-500 disabled:cursor-not-allowed"
        >
          Replay lineage
        </button>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-[16rem_1fr]">
        <div className="rounded-lg border border-slate-800 bg-zinc-950/70 p-3">
          <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">Replay token</div>
          <div className="mt-1 break-words font-mono text-xs text-slate-100">
            {replayAttached ? packet.replay_token : "Replay hook not attached on public MVP."}
          </div>
        </div>
        <div className="rounded-lg border border-slate-800 bg-zinc-950/70 p-3">
          <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">Lineage chain</div>
          <ol className="mt-2 grid gap-1">
            {packet.lineage.map((item, index) => (
              <li key={`${item}-${index}`} className="flex items-center gap-2 font-mono text-xs text-slate-300">
                <span className="text-slate-600">#{index + 1}</span>
                <span className="break-all">{item}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </div>
  );
}
