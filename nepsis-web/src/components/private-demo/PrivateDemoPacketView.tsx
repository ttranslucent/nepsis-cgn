"use client";

import { useMemo, useState, type ReactNode } from "react";
import type { NepsisPrivateDemoRuntimePacket } from "@/lib/engineClient";

type ViewMode = "topology" | "audit" | "lineage" | "compiler" | "raw";

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function readBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function thresholdPacket(packet: NepsisPrivateDemoRuntimePacket): Record<string, unknown> {
  const latestAudit = asRecord(packet.latest_audit);
  return asRecord(asRecord(latestAudit.threshold).packet);
}

function eventNames(packet: NepsisPrivateDemoRuntimePacket): string[] {
  return packet.audit_trace
    .map((event) => readString(event.event))
    .filter((event): event is string => Boolean(event));
}

function KeyValue({ label, value }: { label: string; value: string | number | boolean | null | undefined }) {
  return (
    <div className="min-w-0 rounded-lg border border-nepsis-border bg-nepsis-bg/70 p-3">
      <div className="text-xs uppercase text-nepsis-muted">{label}</div>
      <div className="mt-1 break-words font-mono text-sm text-nepsis-text">{String(value ?? "n/a")}</div>
    </div>
  );
}

function ModeButton({
  mode,
  active,
  onClick,
  children,
}: {
  mode: ViewMode;
  active: boolean;
  onClick: (mode: ViewMode) => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={() => onClick(mode)}
      className={`rounded-md border px-3 py-2 text-sm font-medium transition ${
        active
          ? "border-nepsis-accent bg-nepsis-accent text-black"
          : "border-nepsis-border bg-nepsis-panel text-nepsis-text hover:border-nepsis-accent"
      }`}
    >
      {children}
    </button>
  );
}

function TopologyView({ packet }: { packet: NepsisPrivateDemoRuntimePacket }) {
  const compiler = packet.case_reasoning_compiler;
  const threshold = thresholdPacket(packet);
  const operatorPacket = packet.operator_packet;
  const events = eventNames(packet);
  const compilerValid = readBoolean(compiler.compiler_valid);
  const recommendedAction = readString(compiler.recommended_threshold_action);
  const lastEventArguments = asRecord(asRecord(packet.audit_trace.at(-1)).arguments);
  const thresholdDecision = readString(lastEventArguments.decision);

  return (
    <section aria-label="Private demo topology" className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <KeyValue label="Schema" value={packet.schema_id} />
        <KeyValue label="Mode" value={packet.mode} />
        <KeyValue label="Compiler valid" value={compilerValid} />
        <KeyValue label="Threshold action" value={recommendedAction} />
        <KeyValue label="Threshold decision" value={thresholdDecision} />
        <KeyValue label="Operator phase" value={operatorPacket.phase} />
      </div>

      <div className="grid gap-3 md:grid-cols-4">
        {["LOCK_FRAME", "RUN_REPORT", "LOCK_REPORT", "SET_THRESHOLD_DECISION"].map((event) => (
          <div
            key={event}
            className={`rounded-lg border p-4 ${
              events.includes(event)
                ? "border-nepsis-accent bg-nepsis-accent/10"
                : "border-nepsis-border bg-nepsis-panel"
            }`}
          >
            <div className="text-xs uppercase text-nepsis-muted">Audit gate</div>
            <div className="mt-2 font-mono text-sm">{event}</div>
            <div className="mt-1 text-xs text-nepsis-muted">{events.includes(event) ? "present" : "missing"}</div>
          </div>
        ))}
      </div>

      <div className="rounded-lg border border-nepsis-border bg-nepsis-panel p-4">
        <h2 className="text-base font-semibold">Threshold packet</h2>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <KeyValue label="Gate crossed" value={readBoolean(threshold.gate_crossed)} />
          <KeyValue label="Warning level" value={readString(threshold.warning_level)} />
          <KeyValue label="Recommendation" value={readString(threshold.recommendation)} />
        </div>
      </div>
    </section>
  );
}

function AuditView({ packet }: { packet: NepsisPrivateDemoRuntimePacket }) {
  return (
    <section aria-label="Private demo audit" className="space-y-3">
      {packet.audit_trace.map((event, index) => (
        <article key={`${readString(event.event) ?? "event"}-${index}`} className="rounded-lg border border-nepsis-border bg-nepsis-panel p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-mono text-sm font-semibold">{readString(event.event) ?? `event-${index}`}</h2>
            <span className="text-xs text-nepsis-muted">#{index + 1}</span>
          </div>
          <pre className="mt-3 max-h-72 overflow-auto rounded-md bg-black/30 p-3 text-xs text-nepsis-text">
            {JSON.stringify(event, null, 2)}
          </pre>
        </article>
      ))}
    </section>
  );
}

function LineageView({ packet }: { packet: NepsisPrivateDemoRuntimePacket }) {
  const operator = packet.operator_packet;
  return (
    <section aria-label="Private demo lineage" className="grid gap-3 md:grid-cols-2">
      <KeyValue label="Runtime packet hash" value={packet.prompt_hash} />
      <KeyValue label="Operator packet" value={operator.packet_id} />
      <KeyValue label="Loop" value={operator.loop_id} />
      <KeyValue label="Generated" value={packet.generated_at} />
      <KeyValue label="Thread" value={packet.thread_id} />
      <KeyValue label="User" value={packet.user_id} />
    </section>
  );
}

function CompilerView({ packet }: { packet: NepsisPrivateDemoRuntimePacket }) {
  const compiler = packet.case_reasoning_compiler;
  return (
    <section aria-label="Case reasoning compiler" className="space-y-3">
      <div className="grid gap-3 md:grid-cols-3">
        <KeyValue label="Schema" value={compiler.schema_id} />
        <KeyValue label="Valid" value={compiler.compiler_valid} />
        <KeyValue label="Source" value={readString(compiler.compiler_source)} />
        <KeyValue label="Input frame" value={readString(compiler.input_frame_id)} />
        <KeyValue label="Input prompt hash" value={readString(compiler.input_prompt_hash)} />
        <KeyValue label="Threshold action" value={readString(compiler.recommended_threshold_action)} />
      </div>
      <pre className="max-h-[32rem] overflow-auto rounded-lg border border-nepsis-border bg-black/30 p-4 text-xs text-nepsis-text">
        {JSON.stringify(compiler, null, 2)}
      </pre>
    </section>
  );
}

export function PrivateDemoPacketView({ packet }: { packet: NepsisPrivateDemoRuntimePacket }) {
  const [mode, setMode] = useState<ViewMode>("topology");
  const summary = useMemo(
    () => ({
      events: eventNames(packet).length,
      operatorPhase: packet.operator_packet.phase,
      thresholdAction: readString(packet.case_reasoning_compiler.recommended_threshold_action),
    }),
    [packet],
  );

  return (
    <section className="space-y-5">
      <div className="rounded-lg border border-nepsis-border bg-nepsis-panel p-4">
        <div className="text-xs uppercase text-nepsis-muted">Private runtime packet</div>
        <h1 className="mt-2 text-xl font-semibold">{packet.case_id}</h1>
        <p className="mt-2 text-sm leading-6 text-nepsis-muted">{packet.summary}</p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <KeyValue label="Events" value={summary.events} />
          <KeyValue label="Operator phase" value={summary.operatorPhase} />
          <KeyValue label="Threshold action" value={summary.thresholdAction} />
        </div>
      </div>

      <div className="flex flex-wrap gap-2" aria-label="Private demo packet views">
        <ModeButton mode="topology" active={mode === "topology"} onClick={setMode}>Topology</ModeButton>
        <ModeButton mode="audit" active={mode === "audit"} onClick={setMode}>Audit</ModeButton>
        <ModeButton mode="lineage" active={mode === "lineage"} onClick={setMode}>Lineage</ModeButton>
        <ModeButton mode="compiler" active={mode === "compiler"} onClick={setMode}>Compiler</ModeButton>
        <ModeButton mode="raw" active={mode === "raw"} onClick={setMode}>Raw</ModeButton>
      </div>

      {mode === "topology" && <TopologyView packet={packet} />}
      {mode === "audit" && <AuditView packet={packet} />}
      {mode === "lineage" && <LineageView packet={packet} />}
      {mode === "compiler" && <CompilerView packet={packet} />}
      {mode === "raw" && (
        <pre className="max-h-[42rem] overflow-auto rounded-lg border border-nepsis-border bg-black/30 p-4 text-xs text-nepsis-text">
          {JSON.stringify(packet, null, 2)}
        </pre>
      )}
    </section>
  );
}
