import type { NepsisMvpPacket } from "@/lib/engineClient";

export type ProvenanceStage =
  | "ingest"
  | "red_channel"
  | "blue_channel"
  | "still"
  | "collapse"
  | "zeroback"
  | "validation"
  | "final";

export type ProvenanceNodeState = "active" | "stale" | "contradiction" | "collapsed" | "repair" | "final";

export interface ProvenanceNode {
  id: string;
  parentIds: string[];
  stage: ProvenanceStage;
  label: string;
  version?: string;
  confidence?: number;
  timestamp?: string;
  stale?: boolean;
  contradictionDensity?: number;
  interpretantCoherence?: number;
  metadata?: Record<string, unknown>;
  state?: ProvenanceNodeState;
}

export interface ProvenanceEdge {
  from: string;
  to: string;
  type: "causal" | "derived" | "override" | "repair";
  stale?: boolean;
  label?: string;
}

export interface AuditEvent {
  id: string;
  order: number;
  stage: ProvenanceStage | string;
  summary: string;
  timestamp: string;
  deterministicCallId: string;
  raw: Record<string, unknown>;
}

export interface ProvenanceDiffItem {
  field: string;
  previous: string;
  current: string;
}

export interface ProvenanceDiff {
  hasPriorPacket: boolean;
  changedFields: ProvenanceDiffItem[];
  changedNodeIds: string[];
  changedConstraintCount: boolean;
  changedOutput: boolean;
}

export interface ProvenancePacket {
  run_id: string;
  replay_token?: string;
  packet_version: string;
  nodes: ProvenanceNode[];
  edges: ProvenanceEdge[];
  breadcrumbs: string[];
  audit_events: AuditEvent[];
  source_packet?: NepsisMvpPacket;
  previous_packet?: NepsisMvpPacket;
  diff?: ProvenanceDiff;
  lineage: string[];
  hidden_step_count: number;
}

export type ProvenanceMockCase =
  | "jailing"
  | "posterior_stroke"
  | "sepsis"
  | "constraint_violation"
  | "zeroback_recovery";
