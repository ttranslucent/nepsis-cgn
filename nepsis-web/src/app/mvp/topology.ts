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

  const nodes: MvpTopologyNode[] = [
    {
      id: "red",
      label: "RED Channel",
      eyebrow: "Constraint and hazard gate",
      status: redActive ? "active" : "clear",
      statusLabel: redActive ? "ACTIVE" : "CLEAR",
      summary: packet.red_channel.rationale,
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
      metrics: [{ label: "Readiness", value: readiness }],
    },
    {
      id: "commitment",
      label: "Commitment",
      eyebrow: "Voronoi selection",
      status: retessellationRequired ? "blocked" : "ready",
      statusLabel: retessellationRequired ? "RETESSELLATE" : "READY",
      summary: packet.voronoi_commitment.recommended_action,
      metrics: [{ label: "Threshold", value: packet.voronoi_commitment.threshold_basis }],
    },
    {
      id: "feedback",
      label: "State feedback",
      eyebrow: "Predicted next state",
      status: feedbackStatus === "continue" ? "active" : "hold",
      statusLabel: feedbackStatus.toUpperCase(),
      summary: packet.state_feedback.loop_decision.next_observation_required,
      metrics: [{ label: "Observed", value: packet.state_feedback.observed_next_state.status }],
    },
    {
      id: "audit",
      label: "Audit",
      eyebrow: "Packet lineage",
      status: "active",
      statusLabel: "RECORDED",
      summary: packet.final_output.concise_recommendation,
      metrics: [
        { label: "Events", value: String(packet.audit_trace.length) },
        { label: "Schema", value: packet.schema_version },
      ],
    },
  ];

  return {
    headline: contradictionActive ? "Constraint conflict detected" : "No contradiction detected",
    subhead: retessellationRequired ? "Retessellation required" : "Current topology is commitment-ready",
    nodes,
    edges: [
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
      { from: "feedback", to: "audit", label: "records lineage", emphasized: true },
    ],
    activeFacts: [
      `Contradiction density: ${packet.contradiction_monitor.contradiction_density}`,
      `Density basis: ${packet.contradiction_monitor.density_basis.model}`,
      `Denominator collapse: ${packet.denominator_collapse.detected ? "detected" : "clear"}`,
      `ZeroBack: ${packet.zeroback.triggered ? "triggered" : "clear"}`,
    ],
  };
}
