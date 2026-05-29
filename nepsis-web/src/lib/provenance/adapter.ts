import type { NepsisMvpAuditEvent, NepsisMvpPacket } from "@/lib/engineClient";
import type {
  AuditEvent,
  ProvenanceDiff,
  ProvenanceDiffItem,
  ProvenanceEdge,
  ProvenanceNode,
  ProvenancePacket,
  ProvenanceStage,
} from "@/lib/provenance/types";

const BREADCRUMBS = ["Source", "RED", "STILL", "BLUE", "Collapse", "Validation", "Output"];

const CALL_IDS: Record<string, string> = {
  ingest: "det_call_source_000",
  red_channel: "det_call_red_001",
  still: "det_call_still_002",
  blue_channel: "det_call_blue_003",
  collapse: "det_call_collapse_004",
  validation: "det_call_validation_005",
  final: "det_call_final_006",
};

const EVENT_CALL_IDS: Record<string, string> = {
  signal_intake: CALL_IDS.ingest,
  red_channel: CALL_IDS.red_channel,
  still_checkpoint_1: CALL_IDS.still,
  blue_channel: CALL_IDS.blue_channel,
  contradiction_monitor: CALL_IDS.collapse,
  denominator_collapse: CALL_IDS.collapse,
  non_quiescence: CALL_IDS.validation,
  still_checkpoint_2: CALL_IDS.validation,
  retessellation: "det_call_repair_007",
  zeroback: "det_call_repair_008",
  voronoi_commitment: CALL_IDS.final,
  state_feedback: CALL_IDS.final,
};

function asString(value: unknown): string {
  if (value === undefined || value === null) {
    return "n/a";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function confidenceFromDensity(density: number): number {
  return Number(Math.max(0.2, Math.min(0.98, 0.92 - density * 0.42)).toFixed(2));
}

function coherenceFromPacket(packet: NepsisMvpPacket): number {
  const density = packet.contradiction_monitor.contradiction_density;
  const penalty = packet.denominator_collapse.detected ? 0.18 : 0;
  return Number(Math.max(0.1, 0.9 - density * 0.36 - penalty).toFixed(2));
}

function eventTimestamp(packet: NepsisMvpPacket, order: number): string {
  const base = Date.parse(packet.created_at);
  if (Number.isNaN(base)) {
    return packet.created_at;
  }
  return new Date(base + order * 1000).toISOString();
}

function stageFromAuditStage(stage: string): ProvenanceStage | string {
  if (stage === "signal_intake") {
    return "ingest";
  }
  if (stage === "retessellation" || stage === "denominator_collapse" || stage === "contradiction_monitor") {
    return "collapse";
  }
  if (stage === "still_checkpoint_1" || stage === "still_checkpoint_2") {
    return "still";
  }
  if (stage === "voronoi_commitment" || stage === "state_feedback") {
    return "final";
  }
  if (stage === "non_quiescence") {
    return "validation";
  }
  if (stage === "red_channel" || stage === "blue_channel" || stage === "zeroback") {
    return stage;
  }
  return stage;
}

function normalizeAuditEvent(packet: NepsisMvpPacket, event: NepsisMvpAuditEvent): AuditEvent {
  return {
    id: `${packet.packet_id}:${event.order}:${event.stage}`,
    order: event.order,
    stage: stageFromAuditStage(event.stage),
    summary: event.summary,
    timestamp: eventTimestamp(packet, event.order),
    deterministicCallId: EVENT_CALL_IDS[event.stage] ?? `det_call_audit_${String(event.order).padStart(3, "0")}`,
    raw: event as unknown as Record<string, unknown>,
  };
}

function changedItem(field: string, previous: unknown, current: unknown): ProvenanceDiffItem | null {
  const previousValue = asString(previous);
  const currentValue = asString(current);
  if (previousValue === currentValue) {
    return null;
  }
  return { field, previous: previousValue, current: currentValue };
}

function buildDiff(packet: NepsisMvpPacket, previousPacket?: NepsisMvpPacket): ProvenanceDiff {
  if (!previousPacket) {
    return {
      hasPriorPacket: false,
      changedFields: [],
      changedNodeIds: [],
      changedConstraintCount: false,
      changedOutput: false,
    };
  }

  const candidates = [
    changedItem("input_text", previousPacket.input_text, packet.input_text),
    changedItem(
      "contradiction_density",
      previousPacket.contradiction_monitor.contradiction_density,
      packet.contradiction_monitor.contradiction_density,
    ),
    changedItem("zeroback_triggered", previousPacket.zeroback.triggered, packet.zeroback.triggered),
    changedItem("final_output", previousPacket.final_output.concise_recommendation, packet.final_output.concise_recommendation),
    changedItem("packet_version", previousPacket.schema_version, packet.schema_version),
  ].filter((item): item is ProvenanceDiffItem => Boolean(item));

  const changedNodeIds = new Set<string>();
  for (const item of candidates) {
    if (item.field === "input_text") {
      changedNodeIds.add("source");
    }
    if (item.field === "contradiction_density") {
      changedNodeIds.add("collapse");
      changedNodeIds.add("validation");
    }
    if (item.field === "zeroback_triggered") {
      changedNodeIds.add("validation");
    }
    if (item.field === "final_output") {
      changedNodeIds.add("output");
    }
  }

  return {
    hasPriorPacket: true,
    changedFields: candidates,
    changedNodeIds: Array.from(changedNodeIds),
    changedConstraintCount: previousPacket.constraints.length !== packet.constraints.length,
    changedOutput: previousPacket.final_output.concise_recommendation !== packet.final_output.concise_recommendation,
  };
}

function nodeMetadata(values: Record<string, unknown>): Record<string, unknown> {
  return {
    inputsUsed: values.inputsUsed ?? [],
    constraintStatus: values.constraintStatus ?? "not evaluated",
    stillStatus: values.stillStatus ?? "n/a",
    deterministicCallId: values.deterministicCallId,
    timestamp: values.timestamp,
    driftSignals: values.driftSignals ?? [],
    summary: values.summary,
  };
}

export function adaptMvpPacketToProvenance(
  packet: NepsisMvpPacket,
  previousPacket?: NepsisMvpPacket | null,
): ProvenancePacket {
  const contradictionDensity = packet.contradiction_monitor.contradiction_density;
  const confidence = confidenceFromDensity(contradictionDensity);
  const interpretantCoherence = coherenceFromPacket(packet);
  const redActive = packet.red_channel.escalation_required || packet.red_channel.active_hazards.length > 0;
  const collapseActive = packet.denominator_collapse.detected || packet.denominator_collapse.retessellation_required;
  const zeroBackActive = packet.zeroback.triggered;
  const stillStatus = packet.still.commitment_readiness.status;
  const prior = previousPacket ?? undefined;
  const versionMismatch = Boolean(prior && prior.schema_version !== packet.schema_version);
  const densityChanged = Boolean(
    prior && prior.contradiction_monitor.contradiction_density !== packet.contradiction_monitor.contradiction_density,
  );

  const baseNode = {
    version: packet.schema_version,
    timestamp: packet.created_at,
    contradictionDensity,
    interpretantCoherence,
  };

  const nodes: ProvenanceNode[] = [
    {
      ...baseNode,
      id: "source",
      parentIds: [],
      stage: "ingest",
      label: "Source",
      confidence: 0.96,
      state: "active",
      metadata: nodeMetadata({
        inputsUsed: [packet.input_text],
        constraintStatus: `${packet.constraints.length} constraints loaded`,
        stillStatus,
        deterministicCallId: CALL_IDS.ingest,
        timestamp: packet.created_at,
        summary: "Packet source text and case scaffold entered deterministic MVP rendering.",
      }),
    },
    {
      ...baseNode,
      id: "red",
      parentIds: ["source"],
      stage: "red_channel",
      label: "RED Channel",
      confidence,
      state: redActive ? "contradiction" : "active",
      metadata: nodeMetadata({
        inputsUsed: packet.red_channel.active_hazards.map((hazard) => asString(hazard.id ?? hazard.hazard)),
        constraintStatus: redActive ? "RED boundary active" : "RED boundary clear",
        stillStatus,
        deterministicCallId: CALL_IDS.red_channel,
        timestamp: eventTimestamp(packet, 2),
        summary: packet.red_channel.rationale,
      }),
    },
    {
      ...baseNode,
      id: "still",
      parentIds: ["red"],
      stage: "still",
      label: "STILL Checkpoint",
      confidence: Number((confidence - 0.04).toFixed(2)),
      state: stillStatus === "ready" ? "active" : "contradiction",
      metadata: nodeMetadata({
        inputsUsed: packet.still.checkpoints.map((checkpoint) => checkpoint.name),
        constraintStatus: packet.still.commitment_readiness.rationale,
        stillStatus,
        deterministicCallId: CALL_IDS.still,
        timestamp: eventTimestamp(packet, 3),
        summary: packet.still.definition,
      }),
    },
    {
      ...baseNode,
      id: "blue",
      parentIds: ["still"],
      stage: "blue_channel",
      label: "BLUE Channel",
      confidence: Number((confidence - 0.08).toFixed(2)),
      stale: redActive,
      state: redActive ? "stale" : "active",
      metadata: nodeMetadata({
        inputsUsed: packet.blue_channel.hypotheses.map((hypothesis) => hypothesis.id),
        constraintStatus: redActive ? "bounded by RED" : "optimization permitted",
        stillStatus,
        deterministicCallId: CALL_IDS.blue_channel,
        timestamp: eventTimestamp(packet, 4),
        driftSignals: redActive ? ["BLUE cannot clear unresolved RED boundary"] : [],
        summary: "Hypothesis comparison runs only inside the RED-permitted frame.",
      }),
    },
    {
      ...baseNode,
      id: "collapse",
      parentIds: ["blue"],
      stage: "collapse",
      label: "Collapse",
      confidence: Number((confidence - 0.14).toFixed(2)),
      state: collapseActive ? "collapsed" : "active",
      metadata: nodeMetadata({
        inputsUsed: packet.denominator_collapse.missing_hypothesis_classes,
        constraintStatus: collapseActive ? "retessellation required" : "no denominator collapse",
        stillStatus,
        deterministicCallId: CALL_IDS.collapse,
        timestamp: eventTimestamp(packet, 6),
        driftSignals: densityChanged ? ["contradiction density changed from prior packet"] : [],
        summary: collapseActive
          ? "The hypothesis denominator omitted required classes and must be retessellated."
          : "No denominator collapse was detected in this deterministic packet.",
      }),
    },
    {
      ...baseNode,
      id: "validation",
      parentIds: ["collapse"],
      stage: zeroBackActive ? "zeroback" : "validation",
      label: "Validation",
      confidence: Number((confidence - 0.1).toFixed(2)),
      state: zeroBackActive ? "repair" : "active",
      metadata: nodeMetadata({
        inputsUsed: [packet.zeroback.reason, packet.non_quiescence.reason],
        constraintStatus: zeroBackActive ? "ZeroBack repair path active" : "validation path clear",
        stillStatus,
        deterministicCallId: CALL_IDS.validation,
        timestamp: eventTimestamp(packet, 10),
        driftSignals: versionMismatch ? ["packet version mismatch"] : [],
        summary: zeroBackActive ? packet.zeroback.reset_scope : packet.non_quiescence.next_required_move,
      }),
    },
    {
      ...baseNode,
      id: "output",
      parentIds: ["validation"],
      stage: "final",
      label: "Output",
      confidence: Number((confidence - 0.06).toFixed(2)),
      state: "final",
      metadata: nodeMetadata({
        inputsUsed: packet.final_output.required_next_discriminators,
        constraintStatus: packet.final_output.caveats.join(" "),
        stillStatus,
        deterministicCallId: CALL_IDS.final,
        timestamp: eventTimestamp(packet, 12),
        summary: packet.final_output.concise_recommendation,
      }),
    },
  ];

  const edges: ProvenanceEdge[] = [
    { from: "source", to: "red", type: "causal", label: "ingest" },
    { from: "red", to: "still", type: redActive ? "override" : "causal", label: redActive ? "hard gate" : "permit" },
    { from: "still", to: "blue", type: "derived", stale: redActive, label: "bounded" },
    { from: "blue", to: "collapse", type: collapseActive ? "override" : "derived", stale: redActive, label: "monitor" },
    { from: "collapse", to: "validation", type: zeroBackActive ? "repair" : "causal", label: zeroBackActive ? "ZeroBack" : "validate" },
    { from: "validation", to: "output", type: "causal", label: "commit" },
  ];

  return {
    run_id: packet.packet_id,
    packet_version: packet.schema_version,
    nodes,
    edges,
    breadcrumbs: BREADCRUMBS,
    audit_events: packet.audit_trace.map((event) => normalizeAuditEvent(packet, event)),
    source_packet: packet,
    previous_packet: prior,
    diff: buildDiff(packet, prior),
    lineage: nodes.map((node) => asString(node.metadata?.deterministicCallId)),
    hidden_step_count: Math.max(0, packet.audit_trace.length - nodes.length - 2),
  };
}
