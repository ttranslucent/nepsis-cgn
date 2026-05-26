import type { NepsisMvpPacket } from "@/lib/engineClient";

export type MvpTopologyNodeId =
  | "red"
  | "still_1"
  | "blue"
  | "still_2"
  | "commitment"
  | "feedback"
  | "audit";

export type MvpTopologyStatus = "clear" | "active" | "bounded" | "hold" | "ready" | "blocked";

export type MvpTopologyNode = {
  id: MvpTopologyNodeId;
  label: string;
  eyebrow: string;
  status: MvpTopologyStatus;
  statusLabel: string;
  summary: string;
  detail: {
    checked: string;
    found: string;
    changed: string;
  };
  metrics: Array<{ label: string; value: string }>;
};

export type MvpTopologyEdge = {
  from: MvpTopologyNodeId;
  to: MvpTopologyNodeId;
  label: string;
  emphasized: boolean;
};

export type MvpTopologyModel = {
  headline: string;
  subhead: string;
  nodes: MvpTopologyNode[];
  edges: MvpTopologyEdge[];
  activeFacts: string[];
};

export function buildMvpTopology(packet: NepsisMvpPacket): MvpTopologyModel {
  const redActive = packet.red_channel.escalation_required || packet.red_channel.active_hazards.length > 0;
  const contradictionActive = packet.contradiction_monitor.contradictions.length > 0;
  const retessellationRequired = packet.denominator_collapse.retessellation_required;
  const still1 = packet.still.checkpoints.find((checkpoint) => checkpoint.position === "after_red_before_blue");
  const still2 = packet.still.checkpoints.find((checkpoint) => checkpoint.position === "after_blue_before_commitment");
  const readiness = packet.still.commitment_readiness.status;
  const blueBounded = redActive && packet.blue_channel.hypotheses.length > 0;
  const feedbackStatus = packet.state_feedback.loop_decision.status;
  const firstHazard = packet.red_channel.active_hazards[0];
  const hazardText =
    firstHazard && typeof firstHazard.hazard === "string"
      ? firstHazard.hazard
      : firstHazard && typeof firstHazard.id === "string"
        ? firstHazard.id
        : "No hard-stop hazard was emitted.";
  const hypothesisLabels = packet.blue_channel.hypotheses.map((hypothesis) => hypothesis.label).join(" vs. ");
  const requiredBeforeBlue = still1?.required_before_commitment.join("; ") || "No additional check required.";
  const requiredBeforeCommitment = still2?.required_before_commitment.join("; ") || "No additional check required.";
  const firstFailureCondition =
    packet.state_feedback.predicted_next_state.failure_conditions[0] || "No failure condition was emitted.";

  const nodes: MvpTopologyNode[] = [
    {
      id: "audit",
      label: "Audit",
      eyebrow: "Packet lineage",
      status: "active",
      statusLabel: "RECORDED",
      summary: packet.final_output.concise_recommendation,
      detail: {
        checked: "Whether the packet kept a reviewable lineage from signal intake through final output.",
        found: `${packet.audit_trace.length} audit events recorded under schema ${packet.schema_version}.`,
        changed: packet.final_output.concise_recommendation,
      },
      metrics: [
        { label: "Events", value: String(packet.audit_trace.length) },
        { label: "Schema", value: packet.schema_version },
      ],
    },
    {
      id: "red",
      label: "RED Channel",
      eyebrow: "Constraint and hazard gate",
      status: redActive ? "active" : "clear",
      statusLabel: redActive ? "ACTIVE" : "CLEAR",
      summary: packet.red_channel.rationale,
      detail: {
        checked: "Hard constraints and must-not-miss hazards before any BLUE optimization.",
        found: redActive ? String(hazardText) : "No active RED hazard was found in this packet.",
        changed: redActive
          ? "The run must preserve the RED boundary before explanation, optimization, or commitment."
          : "The packet may enter BLUE without a RED hold.",
      },
      metrics: [
        { label: "Hazards", value: String(packet.red_channel.active_hazards.length) },
        { label: "Missing discriminators", value: String(packet.red_channel.missing_discriminators.length) },
      ],
    },
    {
      id: "still_1",
      label: "STILL 1",
      eyebrow: "Before BLUE",
      status: still1?.trigger_status === "hold" ? "hold" : "ready",
      statusLabel: still1?.trigger_status?.toUpperCase() ?? "READY",
      summary: still1?.reason ?? "No pre-BLUE checkpoint was emitted.",
      detail: {
        checked: "Whether BLUE is allowed to reason freely or only inside a bounded RED frame.",
        found: still1?.reason ?? "No pre-BLUE checkpoint was emitted.",
        changed: `Required before commitment: ${requiredBeforeBlue}`,
      },
      metrics: [{ label: "Required checks", value: String(still1?.required_before_commitment.length ?? 0) }],
    },
    {
      id: "blue",
      label: "BLUE Channel",
      eyebrow: "Bounded hypothesis work",
      status: blueBounded ? "bounded" : "active",
      statusLabel: blueBounded ? "BOUNDED" : "ACTIVE",
      summary: blueBounded
        ? "BLUE can explain candidate interpretations, but cannot clear an unresolved RED boundary."
        : "BLUE is available for hypothesis comparison.",
      detail: {
        checked: "Competing hypotheses, support, and action priority inside the active constraints.",
        found: hypothesisLabels || "No hypotheses were emitted.",
        changed: blueBounded
          ? "Plausibility can inform the audit, but cannot override the active RED boundary."
          : "Hypothesis work can proceed without a RED-bounded hold.",
      },
      metrics: [
        { label: "Hypotheses", value: String(packet.blue_channel.hypotheses.length) },
        { label: "Axes", value: String(Object.keys(packet.blue_channel.evaluation_axes).length) },
      ],
    },
    {
      id: "still_2",
      label: "STILL 2",
      eyebrow: "Before commitment",
      status: still2?.trigger_status === "hold" ? "hold" : readiness === "ready" ? "ready" : "blocked",
      statusLabel: still2?.trigger_status?.toUpperCase() ?? readiness.toUpperCase(),
      summary: still2?.reason ?? packet.still.commitment_readiness.rationale,
      detail: {
        checked: "Whether the packet can close, must hold, or must retessellate before commitment.",
        found: still2?.reason ?? packet.still.commitment_readiness.rationale,
        changed: `Commitment readiness is ${readiness}; required before closure: ${requiredBeforeCommitment}`,
      },
      metrics: [{ label: "Readiness", value: readiness }],
    },
    {
      id: "commitment",
      label: "Commitment",
      eyebrow: "Voronoi selection",
      status: retessellationRequired ? "blocked" : "ready",
      statusLabel: retessellationRequired ? "RETESSELLATE" : "READY",
      summary: packet.voronoi_commitment.recommended_action,
      detail: {
        checked: "Which action wins once constraints, plausibility, and consequence weighting are compared.",
        found: packet.voronoi_commitment.recommended_action,
        changed: packet.voronoi_commitment.threshold_basis,
      },
      metrics: [{ label: "Threshold", value: packet.voronoi_commitment.threshold_basis }],
    },
    {
      id: "feedback",
      label: "State feedback",
      eyebrow: "Predicted next state",
      status: feedbackStatus === "continue" ? "active" : "hold",
      statusLabel: feedbackStatus.toUpperCase(),
      summary: packet.state_feedback.loop_decision.next_observation_required,
      detail: {
        checked: "What the next valid state should preserve, prove, or reopen.",
        found: packet.state_feedback.loop_decision.next_observation_required,
        changed: `Failure condition to watch: ${firstFailureCondition}`,
      },
      metrics: [{ label: "Observed", value: packet.state_feedback.observed_next_state.status }],
    },
  ];

  return {
    headline: contradictionActive ? "Constraint conflict detected" : "No contradiction detected",
    subhead: retessellationRequired ? "Retessellation required" : "Current topology is commitment-ready",
    nodes,
    edges: [
      { from: "audit", to: "red", label: "opens trace", emphasized: true },
      { from: "red", to: "still_1", label: redActive ? "holds boundary" : "permits", emphasized: redActive },
      { from: "still_1", to: "blue", label: blueBounded ? "bounded entry" : "entry", emphasized: blueBounded },
      { from: "blue", to: "still_2", label: "returns to check", emphasized: true },
      {
        from: "still_2",
        to: "commitment",
        label: retessellationRequired ? "blocks closure" : "permits",
        emphasized: retessellationRequired,
      },
      { from: "commitment", to: "feedback", label: "predicts next state", emphasized: true },
    ],
    activeFacts: [
      `Contradiction density: ${packet.contradiction_monitor.contradiction_density}`,
      `Density basis: ${packet.contradiction_monitor.density_basis.model}`,
      `Denominator collapse: ${packet.denominator_collapse.detected ? "detected" : "clear"}`,
      `ZeroBack: ${packet.zeroback.triggered ? "triggered" : "clear"}`,
    ],
  };
}
