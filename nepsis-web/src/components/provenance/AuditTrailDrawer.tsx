"use client";

import { motion, useReducedMotion } from "motion/react";

import { PacketDiffView } from "@/components/provenance/PacketDiffView";
import { ReplayControls } from "@/components/provenance/ReplayControls";
import type { ProvenanceNode, ProvenancePacket } from "@/lib/provenance/types";

export type AuditDrawerTab = "summary" | "why" | "raw" | "diff" | "replay";

const TABS: Array<{ id: AuditDrawerTab; label: string }> = [
  { id: "summary", label: "Summary" },
  { id: "why", label: "Why" },
  { id: "raw", label: "Raw Trace" },
  { id: "diff", label: "Diff" },
  { id: "replay", label: "Replay" },
];

function metadataText(node: ProvenanceNode | null, key: string): string {
  const value = node?.metadata?.[key];
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.length ? value.map((item) => String(item)).join("; ") : "None";
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return value === undefined || value === null ? "n/a" : JSON.stringify(value);
}

export function AuditTrailDrawer({
  packet,
  selectedNode,
  activeTab,
  onActiveTabChange,
}: {
  packet: ProvenancePacket;
  selectedNode: ProvenanceNode | null;
  activeTab: AuditDrawerTab;
  onActiveTabChange: (tab: AuditDrawerTab) => void;
}) {
  const reduceMotion = useReducedMotion();
  const rawPacket = packet.source_packet ?? packet;
  const schemaId =
    packet.source_packet && "schema_id" in packet.source_packet ? packet.source_packet.schema_id : packet.packet_version;

  return (
    <motion.aside
      role="complementary"
      aria-label="Audit trail drawer"
      initial={reduceMotion ? false : { opacity: 0, x: 18 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.18 }}
      className="rounded-xl border border-slate-700/80 bg-zinc-950/90 p-4 shadow-2xl shadow-black/30"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.14em] text-slate-500">Audit drawer</div>
          <h2 className="mt-1 text-lg font-semibold text-slate-50">{selectedNode?.label ?? "Packet audit trail"}</h2>
        </div>
        <div className="rounded border border-slate-700 px-2 py-1 font-mono text-[10px] text-slate-300">
          {schemaId}
        </div>
      </div>

      <div role="tablist" aria-label="Audit trail sections" className="mt-4 flex overflow-x-auto rounded-lg border border-slate-800 bg-black/20 p-1">
        {TABS.map((tab) => {
          const selected = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={() => onActiveTabChange(tab.id)}
              className={`shrink-0 rounded-md px-3 py-1.5 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-sky-300/50 ${
                selected ? "bg-slate-200 text-black" : "text-slate-400 hover:text-slate-100"
              }`}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      <div className="mt-4">
        {activeTab === "summary" ? <SummaryTab packet={packet} selectedNode={selectedNode} /> : null}
        {activeTab === "why" ? <WhyTab packet={packet} selectedNode={selectedNode} /> : null}
        {activeTab === "raw" ? <RawTraceTab packet={packet} rawPacket={rawPacket} schemaId={schemaId} /> : null}
        {activeTab === "diff" ? <PacketDiffView packet={packet} /> : null}
        {activeTab === "replay" ? <ReplayControls packet={packet} /> : null}
      </div>
    </motion.aside>
  );
}

function SummaryTab({ packet, selectedNode }: { packet: ProvenancePacket; selectedNode: ProvenanceNode | null }) {
  return (
    <div className="space-y-3 text-sm">
      <p className="leading-6 text-slate-300">
        {metadataText(selectedNode, "summary")}
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <Metric label="Run ID" value={packet.run_id} />
        <Metric label="Deterministic ID" value={metadataText(selectedNode, "deterministicCallId")} />
        <Metric label="Confidence" value={`${Math.round((selectedNode?.confidence ?? 0) * 100)}%`} />
        <Metric label="Contradiction density" value={String(selectedNode?.contradictionDensity ?? 0)} />
      </div>
    </div>
  );
}

function WhyTab({ packet, selectedNode }: { packet: ProvenancePacket; selectedNode: ProvenanceNode | null }) {
  const source = packet.source_packet;
  const constraints = source?.constraints ?? [metadataText(selectedNode, "constraintStatus")];
  const contradictions = source?.contradiction_monitor.contradictions ?? [];
  const zeroBack = source?.zeroback;

  return (
    <div className="space-y-4 text-sm text-slate-300">
      <SectionList title="Constraints triggered" items={constraints} />
      <SectionList
        title="Contradictions detected"
        items={contradictions.map((item) => JSON.stringify(item))}
      />
      <SectionList
        title="Thresholds crossed"
        items={[
          `STILL: ${metadataText(selectedNode, "stillStatus")}`,
          `Node state: ${selectedNode?.state ?? "active"}`,
          `Density: ${selectedNode?.contradictionDensity ?? 0}`,
        ]}
      />
      <SectionList
        title="Manifold shifts and ZeroBack rationale"
        items={[
          source?.non_quiescence.reason ?? "No non-quiescence rationale in fixture.",
          zeroBack?.triggered ? zeroBack.reason : "ZeroBack clear in this packet.",
        ]}
      />
    </div>
  );
}

function RawTraceTab({
  packet,
  rawPacket,
  schemaId,
}: {
  packet: ProvenancePacket;
  rawPacket: unknown;
  schemaId: string;
}) {
  return (
    <div className="space-y-4">
      <div className="grid gap-2 sm:grid-cols-3">
        <Metric label="Schema" value={schemaId} />
        <Metric label="Events" value={String(packet.audit_events.length)} />
        <Metric label="Packet version" value={packet.packet_version} />
      </div>
      <ol className="space-y-2">
        {packet.audit_events.map((event) => (
          <li key={event.id} className="rounded-lg border border-slate-800 bg-black/25 p-3">
            <div className="flex flex-wrap items-center gap-2 font-mono text-[11px] text-slate-500">
              <span>#{event.order}</span>
              <span>{event.stage}</span>
              <span>{event.deterministicCallId}</span>
              <span>{event.timestamp}</span>
            </div>
            <div className="mt-1 text-sm text-slate-200">{event.summary}</div>
          </li>
        ))}
      </ol>
      <pre className="max-h-[26rem] overflow-auto rounded-lg border border-slate-800 bg-black/35 p-3 text-xs leading-relaxed text-slate-300">
        {JSON.stringify(rawPacket, null, 2)}
      </pre>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-black/25 p-3">
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">{label}</div>
      <div className="mt-1 break-words text-sm text-slate-100">{value}</div>
    </div>
  );
}

function SectionList({ title, items }: { title: string; items: string[] }) {
  return (
    <section>
      <div className="font-mono text-[10px] uppercase tracking-[0.12em] text-slate-500">{title}</div>
      {items.length > 0 ? (
        <ul className="mt-2 space-y-1.5">
          {items.map((item, index) => (
            <li key={`${title}-${index}`} className="rounded border border-slate-800 bg-black/20 px-2 py-1.5">
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-2 rounded border border-slate-800 bg-black/20 px-2 py-1.5 text-slate-500">None</div>
      )}
    </section>
  );
}
