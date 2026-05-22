import type { NepsisMvpPacket } from "@/lib/engineClient";

import { buildMvpTopology, type MvpTopologyNode, type MvpTopologyStatus } from "./topology";

const STATUS_CLASS: Record<MvpTopologyStatus, string> = {
  clear: "border-emerald-300/45 bg-emerald-400/10 text-emerald-100",
  active: "border-red-300/55 bg-red-500/10 text-red-100",
  bounded: "border-sky-300/55 bg-sky-500/10 text-sky-100",
  hold: "border-nepsis-accent/70 bg-nepsis-accent/10 text-nepsis-accentSoft",
  ready: "border-emerald-300/55 bg-emerald-400/10 text-emerald-100",
  blocked: "border-red-300/60 bg-red-500/15 text-red-100",
};

export function VisualTopologyMode({ packet }: { packet: NepsisMvpPacket }) {
  const topology = buildMvpTopology(packet);

  return (
    <section
      aria-label="Visual topology"
      className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-5 md:p-6"
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)] lg:items-start">
        <div>
          <div className="text-xs uppercase tracking-[0.14em] text-nepsis-muted">Visual Topology</div>
          <h2 className="mt-2 text-xl font-semibold">{topology.headline}</h2>
          <p className="mt-2 text-sm text-nepsis-muted">{topology.subhead}</p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
          {topology.activeFacts.map((fact) => (
            <div
              key={fact}
              className="rounded-2xl border border-nepsis-border bg-black/20 px-3 py-2 text-xs text-nepsis-text"
            >
              {fact}
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-3 xl:grid-cols-[1fr_1fr_1fr_1fr_1fr_1fr_1fr]">
        {topology.nodes.map((node, index) => (
          <TopologyNodeCard
            key={node.id}
            node={node}
            edgeLabel={topology.edges[index]?.label}
            edgeEmphasized={topology.edges[index]?.emphasized ?? false}
            isLast={index === topology.nodes.length - 1}
          />
        ))}
      </div>
    </section>
  );
}

function TopologyNodeCard({
  node,
  edgeLabel,
  edgeEmphasized,
  isLast,
}: {
  node: MvpTopologyNode;
  edgeLabel?: string;
  edgeEmphasized: boolean;
  isLast: boolean;
}) {
  return (
    <div className="relative min-w-0">
      <div className={`min-h-64 rounded-2xl border p-4 ${STATUS_CLASS[node.status]}`}>
        <div className="text-[11px] uppercase tracking-[0.12em] opacity-80">{node.eyebrow}</div>
        <h3 className="mt-2 text-base font-semibold">{node.label}</h3>
        <div className="mt-3 inline-flex rounded-full border border-current/35 px-2 py-1 font-mono text-[11px]">
          {node.statusLabel}
        </div>
        <p className="mt-3 text-sm leading-relaxed text-nepsis-text">{node.summary}</p>
        <div className="mt-4 space-y-2">
          {node.metrics.map((metric) => (
            <div key={`${node.id}-${metric.label}`} className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.12em] text-nepsis-muted">{metric.label}</div>
              <div className="mt-1 break-words text-xs text-nepsis-text">{metric.value}</div>
            </div>
          ))}
        </div>
      </div>
      {!isLast && edgeLabel && (
        <div className="mt-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-nepsis-muted xl:absolute xl:left-[calc(100%+0.2rem)] xl:top-1/2 xl:z-10 xl:mt-0 xl:w-24 xl:-translate-y-1/2">
          <span className={`h-px flex-1 ${edgeEmphasized ? "bg-nepsis-accent" : "bg-nepsis-border"}`} />
          <span className="max-w-20 text-center">{edgeLabel}</span>
        </div>
      )}
    </div>
  );
}
