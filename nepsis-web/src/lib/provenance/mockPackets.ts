import type {
  AuditEvent,
  ProvenanceMockCase,
  ProvenanceNode,
  ProvenancePacket,
  ProvenanceStage,
} from "@/lib/provenance/types";

const CASE_LABELS: Record<ProvenanceMockCase, string> = {
  jailing: "Jailing/JINGALL constraint preservation",
  posterior_stroke: "Posterior stroke must-not-miss screen",
  sepsis: "Sepsis escalation under uncertainty",
  constraint_violation: "Constraint violation repair",
  zeroback_recovery: "ZeroBack recovery",
};

const CASE_DENSITY: Record<ProvenanceMockCase, number> = {
  jailing: 0.67,
  posterior_stroke: 0.5,
  sepsis: 0.5,
  constraint_violation: 0.75,
  zeroback_recovery: 0.25,
};

function callId(seedCase: ProvenanceMockCase, suffix: string): string {
  return `det_mock_${seedCase}_${suffix}`;
}

function node(seedCase: ProvenanceMockCase, id: string, label: string, parentIds: string[]): ProvenanceNode {
  const density = CASE_DENSITY[seedCase];
  const stageById: Record<string, ProvenanceStage> = {
    source: "ingest",
    red: "red_channel",
    still: "still",
    blue: "blue_channel",
    collapse: "collapse",
    validation: seedCase === "zeroback_recovery" ? "zeroback" : "validation",
    output: "final",
  };
  return {
    id,
    parentIds,
    stage: stageById[id] ?? "validation",
    label,
    version: "mock.provenance.v1",
    confidence: Number((0.92 - density * 0.3).toFixed(2)),
    timestamp: "2026-05-29T12:00:00.000Z",
    contradictionDensity: density,
    interpretantCoherence: Number((0.9 - density * 0.25).toFixed(2)),
    state:
      id === "red"
        ? "contradiction"
        : id === "validation" && seedCase === "zeroback_recovery"
          ? "repair"
          : id === "output"
            ? "final"
            : "active",
    metadata: {
      inputsUsed: [CASE_LABELS[seedCase]],
      constraintStatus: density > 0.6 ? "constraint pressure high" : "constraint pressure bounded",
      stillStatus: seedCase === "zeroback_recovery" ? "zeroback" : "retessellate",
      deterministicCallId: callId(seedCase, id),
      timestamp: "2026-05-29T12:00:00.000Z",
      summary: `${CASE_LABELS[seedCase]} fixture for provenance component examples.`,
    },
  };
}

function event(seedCase: ProvenanceMockCase, order: number, stage: string, summary: string): AuditEvent {
  return {
    id: `${seedCase}:${order}:${stage}`,
    order,
    stage,
    summary,
    timestamp: new Date(Date.parse("2026-05-29T12:00:00.000Z") + order * 1000).toISOString(),
    deterministicCallId: callId(seedCase, stage),
    raw: { order, stage, summary, seed_case: seedCase },
  };
}

export function createMockProvenancePacket(seedCase: ProvenanceMockCase = "jailing"): ProvenancePacket {
  const nodes = [
    node(seedCase, "source", "Source", []),
    node(seedCase, "red", "RED Channel", ["source"]),
    node(seedCase, "still", "STILL Checkpoint", ["red"]),
    node(seedCase, "blue", "BLUE Channel", ["still"]),
    node(seedCase, "collapse", "Collapse", ["blue"]),
    node(seedCase, "validation", "Validation", ["collapse"]),
    node(seedCase, "output", "Output", ["validation"]),
  ];

  return {
    run_id: `mock_${seedCase}_run`,
    replay_token: `replay_mock_${seedCase}`,
    packet_version: "mock.provenance.v1",
    nodes,
    edges: [
      { from: "source", to: "red", type: "causal", label: "ingest" },
      { from: "red", to: "still", type: "override", label: "hard gate" },
      { from: "still", to: "blue", type: "derived", label: "bounded" },
      { from: "blue", to: "collapse", type: "override", stale: seedCase === "constraint_violation", label: "monitor" },
      { from: "collapse", to: "validation", type: "repair", label: "repair" },
      { from: "validation", to: "output", type: "causal", label: "commit" },
    ],
    breadcrumbs: ["Source", "RED", "STILL", "BLUE", "Collapse", "Validation", "Output"],
    audit_events: [
      event(seedCase, 1, "ingest", "Seeded source inputs loaded."),
      event(seedCase, 2, "red_channel", "RED constraints evaluated before optimization."),
      event(seedCase, 3, "still", "STILL checkpoint preserved commitment gate."),
      event(seedCase, 4, "blue_channel", "BLUE hypotheses compared inside RED boundary."),
      event(seedCase, 5, "collapse", "Denominator collapse and contradictions assessed."),
      event(seedCase, 6, "zeroback", "Repair path prepared for replayable lineage."),
      event(seedCase, 7, "final", "Final deterministic fixture output recorded."),
    ],
    diff: {
      hasPriorPacket: false,
      changedFields: [],
      changedNodeIds: [],
      changedConstraintCount: false,
      changedOutput: false,
    },
    lineage: nodes.map((item) => String(item.metadata?.deterministicCallId)),
    hidden_step_count: 3,
  };
}

export const provenanceMockCases: ProvenanceMockCase[] = [
  "jailing",
  "posterior_stroke",
  "sepsis",
  "constraint_violation",
  "zeroback_recovery",
];
