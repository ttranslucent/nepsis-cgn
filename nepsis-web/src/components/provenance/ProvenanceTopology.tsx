"use client";

import { useMemo, useRef, useState } from "react";

import { ProvenanceBreadcrumbs } from "@/components/provenance/ProvenanceBreadcrumbs";
import { ProvenanceEdge } from "@/components/provenance/ProvenanceEdge";
import { ProvenanceNode } from "@/components/provenance/ProvenanceNode";
import type { ProvenancePacket } from "@/lib/provenance/types";

function relatedNodeIds(packet: ProvenancePacket, nodeId: string | null): Set<string> {
  if (!nodeId) {
    return new Set();
  }
  const related = new Set<string>([nodeId]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const edge of packet.edges) {
      if (related.has(edge.from) && !related.has(edge.to)) {
        related.add(edge.to);
        changed = true;
      }
      if (related.has(edge.to) && !related.has(edge.from)) {
        related.add(edge.from);
        changed = true;
      }
    }
  }
  return related;
}

export function ProvenanceTopology({
  packet,
  selectedNodeId,
  onSelectedNodeIdChange,
  onOpenAudit,
  onReplay,
}: {
  packet: ProvenancePacket;
  selectedNodeId: string | null;
  onSelectedNodeIdChange: (nodeId: string) => void;
  onOpenAudit: () => void;
  onReplay: () => void;
}) {
  const [activeMicroCardId, setActiveMicroCardId] = useState<string | null>(null);
  const nodeRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const edgeByFrom = useMemo(() => new Map(packet.edges.map((edge) => [edge.from, edge])), [packet.edges]);
  const related = useMemo(
    () => relatedNodeIds(packet, activeMicroCardId ?? selectedNodeId),
    [activeMicroCardId, packet, selectedNodeId],
  );

  function focusNode(nodeId: string) {
    onSelectedNodeIdChange(nodeId);
    setActiveMicroCardId(nodeId);
    const element = nodeRefs.current[nodeId];
    element?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
    element?.focus();
  }

  return (
    <section
      aria-label="Provenance topology"
      className="rounded-xl border border-slate-700/80 bg-zinc-950/80 p-4 md:p-5"
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
        <div>
          <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-slate-500">Semantic telemetry</div>
          <h2 className="mt-2 text-xl font-semibold text-slate-50">Reasoning topology</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
            Deterministic packet lineage rendered as a fixed left-to-right governance graph.
          </p>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-lg border border-slate-800 bg-black/25 p-2">
            <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">Run</div>
            <div className="mt-1 truncate font-mono text-slate-200">{packet.run_id}</div>
          </div>
          <div className="rounded-lg border border-slate-800 bg-black/25 p-2">
            <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">Version</div>
            <div className="mt-1 font-mono text-slate-200">{packet.packet_version}</div>
          </div>
        </div>
      </div>

      <div className="mt-4">
        <ProvenanceBreadcrumbs
          breadcrumbs={packet.breadcrumbs}
          activeNodeId={selectedNodeId}
          onFocusNode={focusNode}
        />
      </div>

      <div className="mt-5 overflow-x-auto pb-32">
        <div className="flex min-w-max items-start">
          {packet.nodes.map((node, index) => {
            const edge = edgeByFrom.get(node.id);
            const dimmed = related.size > 0 && !related.has(node.id);
            return (
              <div key={node.id} className="flex items-start">
                <ProvenanceNode
                  ref={(element) => {
                    nodeRefs.current[node.id] = element;
                  }}
                  node={node}
                  selected={selectedNodeId === node.id}
                  active={activeMicroCardId === node.id}
                  dimmed={dimmed}
                  onSelect={() => {
                    onSelectedNodeIdChange(node.id);
                    setActiveMicroCardId(node.id);
                    onOpenAudit();
                  }}
                  onActivateCard={() => setActiveMicroCardId(node.id)}
                  onDeactivateCard={() => undefined}
                  onOpenAudit={onOpenAudit}
                  onReplay={onReplay}
                />
                {edge ? <ProvenanceEdge edge={edge} /> : null}
                {index === 4 && packet.hidden_step_count > 0 ? (
                  <div className="mx-2 mt-24 shrink-0 rounded-md border border-slate-700 bg-black/30 px-3 py-2 font-mono text-[11px] uppercase tracking-[0.12em] text-slate-400">
                    + {packet.hidden_step_count} hidden steps
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
