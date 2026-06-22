"use client";

import { useMemo, useState, type ReactNode } from "react";
import type { NepsisPrivateDemoRuntimePacket } from "@/lib/engineClient";

type ViewMode = "topology" | "audit" | "lineage" | "compiler" | "raw";

type NormalizedPacket = {
  packet: Record<string, unknown>;
  raw: NepsisPrivateDemoRuntimePacket;
  auditTrace: Record<string, unknown>[];
  operatorPacket: Record<string, unknown>;
  compiler: Record<string, unknown>;
  latestAudit: Record<string, unknown>;
  threshold: Record<string, unknown>;
  thresholdEventArguments: Record<string, unknown>;
};

function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};
}

function readString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function readBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function lastEventArguments(auditTrace: Record<string, unknown>[], eventName: string): Record<string, unknown> {
  for (let index = auditTrace.length - 1; index >= 0; index -= 1) {
    const event = auditTrace[index];
    if (readString(event.event) === eventName) {
      return asRecord(event.arguments);
    }
  }
  return {};
}

function normalizePacket(packet: NepsisPrivateDemoRuntimePacket): NormalizedPacket {
  const packetRecord = asRecord(packet);
  const latestAudit = asRecord(packetRecord.latest_audit);
  const thresholdGate = asRecord(latestAudit.threshold);
  const auditTrace = Array.isArray(packetRecord.audit_trace) ? packetRecord.audit_trace.map(asRecord) : [];

  return {
    packet: packetRecord,
    raw: packet,
    auditTrace,
    operatorPacket: asRecord(packetRecord.operator_packet),
    compiler: asRecord(packetRecord.case_reasoning_compiler),
    latestAudit,
    threshold: asRecord(thresholdGate.packet),
    thresholdEventArguments: lastEventArguments(auditTrace, "SET_THRESHOLD_DECISION"),
  };
}

function eventNames(auditTrace: Record<string, unknown>[]): string[] {
  return auditTrace
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

function TopologyView({ normalized }: { normalized: NormalizedPacket }) {
  const { packet, compiler, threshold, operatorPacket, thresholdEventArguments } = normalized;
  const events = eventNames(normalized.auditTrace);
  const compilerValid = readBoolean(compiler.compiler_valid);
  const recommendedAction =
    readString(threshold.recommended_threshold_action) ?? readString(compiler.recommended_threshold_action);
  const thresholdDecision = readString(threshold.decision) ?? readString(thresholdEventArguments.decision);
  const thresholdHoldReason = readString(threshold.hold_reason) ?? readString(thresholdEventArguments.hold_reason);
  const closureBasis = readString(threshold.closure_basis) ?? readString(compiler.closure_basis);
  const hypothesisCount = readNumber(threshold.hypothesis_count) ?? readNumber(compiler.hypothesis_count);
  const inputFrame = readString(threshold.input_frame_id) ?? readString(compiler.input_frame_id);
  const inputPromptHash = readString(threshold.input_prompt_hash) ?? readString(compiler.input_prompt_hash);

  return (
    <section aria-label="Private demo topology" className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <KeyValue label="Schema" value={readString(packet.schema_id)} />
        <KeyValue label="Mode" value={readString(packet.mode)} />
        <KeyValue label="Compiler valid" value={compilerValid} />
        <KeyValue label="Threshold action" value={recommendedAction} />
        <KeyValue label="Threshold decision" value={thresholdDecision} />
        <KeyValue label="Operator phase" value={readString(operatorPacket.phase)} />
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
          <KeyValue label="Recommended threshold action" value={recommendedAction} />
          <KeyValue label="Decision" value={thresholdDecision} />
          <KeyValue label="Hold reason" value={thresholdHoldReason} />
          <KeyValue label="Closure basis" value={closureBasis} />
          <KeyValue label="Hypothesis count" value={hypothesisCount} />
          <KeyValue label="Input frame" value={inputFrame} />
          <KeyValue label="Input prompt hash" value={inputPromptHash} />
        </div>
        <pre className="mt-3 max-h-72 overflow-auto rounded-md bg-black/30 p-3 text-xs text-nepsis-text">
          {JSON.stringify(threshold, null, 2)}
        </pre>
      </div>
    </section>
  );
}

function AuditView({ normalized }: { normalized: NormalizedPacket }) {
  if (normalized.auditTrace.length === 0) {
    return (
      <section aria-label="Private demo audit" className="rounded-lg border border-nepsis-border bg-nepsis-panel p-4">
        <div className="text-sm text-nepsis-muted">No audit events recorded in this packet.</div>
      </section>
    );
  }

  return (
    <section aria-label="Private demo audit" className="space-y-3">
      {normalized.auditTrace.map((event, index) => (
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

function LineageView({ normalized }: { normalized: NormalizedPacket }) {
  const { packet, operatorPacket } = normalized;
  return (
    <section aria-label="Private demo lineage" className="grid gap-3 md:grid-cols-2">
      <KeyValue label="Prompt hash" value={readString(packet.prompt_hash)} />
      <KeyValue label="Operator packet" value={readString(operatorPacket.packet_id)} />
      <KeyValue label="Loop" value={readString(operatorPacket.loop_id)} />
      <KeyValue label="Generated" value={readString(packet.generated_at)} />
      <KeyValue label="Thread" value={readString(packet.thread_id)} />
      <KeyValue label="User" value={readString(packet.user_id)} />
    </section>
  );
}

function CompilerView({ normalized }: { normalized: NormalizedPacket }) {
  const compiler = normalized.compiler;
  return (
    <section aria-label="Case reasoning compiler" className="space-y-3">
      <div className="grid gap-3 md:grid-cols-3">
        <KeyValue label="Schema" value={readString(compiler.schema_id)} />
        <KeyValue label="Valid" value={readBoolean(compiler.compiler_valid)} />
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
  const normalized = useMemo(() => normalizePacket(packet), [packet]);
  const summary = useMemo(
    () => ({
      events: eventNames(normalized.auditTrace).length,
      operatorPhase: readString(normalized.operatorPacket.phase),
      thresholdAction:
        readString(normalized.threshold.recommended_threshold_action) ??
        readString(normalized.compiler.recommended_threshold_action),
    }),
    [normalized],
  );

  return (
    <section className="space-y-5">
      <div className="rounded-lg border border-nepsis-border bg-nepsis-panel p-4">
        <div className="text-xs uppercase text-nepsis-muted">Private runtime packet</div>
        <h1 className="mt-2 text-xl font-semibold">{readString(normalized.packet.case_id) ?? "Unknown case"}</h1>
        <p className="mt-2 text-sm leading-6 text-nepsis-muted">{readString(normalized.packet.summary) ?? "n/a"}</p>
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

      {mode === "topology" && <TopologyView normalized={normalized} />}
      {mode === "audit" && <AuditView normalized={normalized} />}
      {mode === "lineage" && <LineageView normalized={normalized} />}
      {mode === "compiler" && <CompilerView normalized={normalized} />}
      {mode === "raw" && (
        <pre className="max-h-[42rem] overflow-auto rounded-lg border border-nepsis-border bg-black/30 p-4 text-xs text-nepsis-text">
          {JSON.stringify(normalized.raw, null, 2)}
        </pre>
      )}
    </section>
  );
}
