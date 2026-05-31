import { withCsrfHeader } from "@/lib/csrfClient";

export type EngineFamily = "puzzle" | "clinical" | "safety";
export type NepsisMvpCaseId = "jailing" | "clinical";

export type EngineRoute = {
  method: string;
  path: string;
  description: string;
};

export type EngineFrame = {
  frame_id: string;
  frame_version: number;
  text: string;
  objective_type: string;
  domain: string | null;
  time_horizon: string | null;
  rationale_for_change: string | null;
  constraints_hard: string[];
  constraints_soft: string[];
  costs: {
    c_fp: number | null;
    c_fn: number | null;
    c_delay: number | null;
  };
};

export type EngineLineage = {
  branch_id: string | null;
  lineage_version: number | null;
  parent_frame_id: string | null;
  frame_ref?: string | null;
};

export type EngineSessionSummary = {
  session_id: string;
  family: EngineFamily;
  created_at: string;
  stage: string;
  steps: number;
  packet_count: number;
  frame: EngineFrame | null;
  branch_id: string | null;
  lineage_version: number | null;
  parent_frame_id: string | null;
  frame_ref?: string | null;
  workspace_state?: EngineWorkspaceState | null;
  operator_phase?: string;
  operator_ambient?: boolean;
};

export type EngineWorkspaceState = Record<string, unknown>;

export type EngineCreateSessionPayload = {
  family: EngineFamily;
  manifest_path?: string;
  governance?: {
    c_fp: number;
    c_fn: number;
  };
  emit_packet?: boolean;
  frame?: Partial<EngineFrame> & { text: string };
};

export type EngineStepPayload = {
  sign: Record<string, unknown>;
  commit?: boolean;
  user_decision?: "stop" | "continue_override";
  override_reason?: string;
  carry_forward?: Record<string, unknown>;
};

export type EngineReframePayload = {
  frame: {
    text?: string;
    objective_type?: string;
    domain?: string | null;
    time_horizon?: string | null;
    rationale_for_change?: string | null;
    constraints_hard?: string[];
    constraints_soft?: string[];
  };
  branch_id?: string;
  parent_frame_id?: string | null;
};

export type EngineConvergenceReason = {
  code: string;
  title: string;
  message: string;
  next_discriminator: string;
  severity: string;
};

export type EngineGovernance = {
  posture: string;
  warning_level: string;
  recommended_action: string;
  trigger_codes: string[];
  theta: number;
  loss_treat: number;
  loss_notreat: number;
  p_bad: number;
  ruin_mass: number;
  contradiction_density: number;
  posterior_entropy_norm: number;
  top_margin: number;
  top_p: number | null;
  user_decision: string | null;
  override_reason: string | null;
  why_not_converging?: EngineConvergenceReason[];
};

export type EngineStepResponse = {
  manifold: string;
  family: string;
  decision: string;
  cause: string | null;
  tension: number;
  velocity: number;
  accel: number;
  posterior: Record<string, number>;
  ruin_hits: string[];
  active_transforms: string[];
  is_ruin: boolean;
  violation_count: number;
  stage: string;
  stage_events: string[];
  frame_id: string | null;
  frame_version: number | null;
  governance?: EngineGovernance;
  iteration_packet?: Record<string, unknown>;
  session: EngineSessionSummary;
};

export type EngineStageAuditCheckStatus = "pass" | "warn" | "block";

export type EngineStageAuditCheck = {
  key: string;
  label: string;
  status: EngineStageAuditCheckStatus;
  detail: string;
};

export type EngineStageAuditCoach = {
  status: "PASS" | "WARN" | "BLOCK";
  summary: string;
  prompts: string[];
};

export type EngineStageAuditGate<TPacket = Record<string, unknown>> = {
  status: "PASS" | "WARN" | "BLOCK";
  checks: EngineStageAuditCheck[];
  missing: string[];
  warnings: string[];
  packet: TPacket;
  coach: EngineStageAuditCoach;
};

export type EngineStageAuditContext = {
  frame?: Record<string, unknown>;
  interpretation?: Record<string, unknown>;
  threshold?: Record<string, unknown>;
};

export type EngineStageAuditPayload = {
  context?: EngineStageAuditContext;
  persist_context?: boolean;
};

export type EngineWorkspacePayload = {
  workspace_state: EngineWorkspaceState;
};

export type EngineStageAuditPolicy = {
  name: string;
  version: string;
};

export type EngineStageAuditResponse = {
  session_id: string;
  stage: string;
  policy: EngineStageAuditPolicy;
  frame: EngineStageAuditGate;
  interpretation: EngineStageAuditGate;
  threshold: EngineStageAuditGate;
  source: {
    packet_count: number;
    latest_packet_id: string | null;
    latest_iteration: number | null;
    context_applied: boolean;
    context_source?: "request" | "session" | null;
  };
};

export type EnginePhaseRejection = {
  schema_id: "nepsis.phase_rejection";
  schema_version: string;
  attempted_tool: string;
  failed_precondition: string;
  current_phase: string;
  legal_next_tools: string[];
  session_id: string;
  gate_status: "PASS" | "WARN" | "BLOCK";
  missing: string[];
  coach_prompts: string[];
};

export type EngineOperatorResponse = {
  session_id: string;
  previous_session_id?: string;
  phase: string;
  legal_next_tools: string[];
  session: EngineSessionSummary;
  audit?: EngineStageAuditResponse;
  step?: EngineStepResponse;
  packet?: Record<string, unknown>;
};

export type EngineOperatorResult = EngineOperatorResponse | EnginePhaseRejection;

export type EngineOperatorFramePayload = {
  family?: EngineFamily;
  frame: EngineCreateSessionPayload["frame"];
  governance?: {
    c_fp: number;
    c_fn: number;
  };
  governance_costs?: {
    c_fp: number;
    c_fn: number;
  };
};

export type EngineOperatorReportPayload = {
  report_text: string;
  sign: Record<string, unknown>;
  interpretation?: Record<string, unknown>;
};

export type EnginePacketResponse = {
  session_id: string;
  count: number;
  packets: Record<string, unknown>[];
};

export type PacketProvenanceRecord = {
  schema_id: "nepsis.packet_provenance_record";
  schema_version: string;
  record_id: string;
  created_at: string;
  source: string;
  direction: string;
  packet_id: string;
  packet_schema_id: string | null;
  packet_schema_version: string | null;
  session_id: string | null;
  parent_packet_id: string | null;
  payload_hash: string;
  request: {
    request_id: string | null;
    method: string | null;
    path: string | null;
    sequence: number | null;
    owner_hash?: string;
  };
  retention: {
    mode: "retained" | "hash_only";
    payload_retained: boolean;
  };
  integrity: {
    payload_hash_verified: boolean | null;
    signature_verified: boolean | null;
  };
  signature: {
    algorithm: "unsigned" | "hmac-sha256" | string;
    key_id: string | null;
    signature: string | null;
    signed_at: string | null;
  };
  payload?: Record<string, unknown>;
};

export type PacketProvenanceGraph = {
  nodes: Array<{
    packet_id: string;
    packet_schema_id: string | null;
    session_id: string | null;
    source: string | null;
    payload_hash: string | null;
    signature: PacketProvenanceRecord["signature"] | null;
    retention: PacketProvenanceRecord["retention"] | null;
    created_at: string | null;
    request_id: string | null;
  }>;
  edges: Array<{
    parent_packet_id: string;
    child_packet_id: string;
  }>;
};

export type PacketProvenanceResponse = {
  session_id: string;
  count: number;
  records: PacketProvenanceRecord[];
  graph: PacketProvenanceGraph;
};

export type SessionAuditExport = {
  schema_id: "nepsis.audit_export";
  schema_version: string;
  created_at: string;
  session: EngineSessionSummary;
  packets: Record<string, unknown>[];
  provenance: {
    records: PacketProvenanceRecord[];
    graph: PacketProvenanceGraph;
  };
  verification: {
    record_count: number;
    hash_failures: string[];
    signature_failures: string[];
    hash_only_omissions: string[];
  };
};

export type NepsisMvpAuditEvent = {
  order: number;
  stage: string;
  summary: string;
};

export type NepsisMvpStillCheckpoint = {
  name: string;
  position: string;
  trigger_status: string;
  reason: string;
  required_before_commitment: string[];
};

export type NepsisMvpStill = {
  name: string;
  definition: string;
  checkpoints: NepsisMvpStillCheckpoint[];
  commitment_readiness: {
    status: "ready" | "hold" | "retessellate" | "zeroback";
    rationale: string;
  };
  learning_notes: string[];
  audit_events: NepsisMvpAuditEvent[];
};

export type NepsisMvpStateFeedback = {
  current_state: {
    timestamp_or_phase: string;
    active_frame: string;
    active_constraints: string[];
    active_hazards: string[];
    current_commitment: string;
    uncertainty_level: string;
  };
  predicted_next_state: {
    expected_time_window: string;
    expected_changes: string[];
    expected_discriminators: string[];
    expected_resolution_signs: string[];
    failure_conditions: string[];
  };
  observed_next_state: {
    status: "not_observed_in_mvp";
    placeholder_reason: string;
  };
  delta_analysis: {
    matches_prediction: "pending";
    contradiction_delta: "pending";
    confidence_delta: "pending";
    reason: string;
  };
  loop_decision: {
    status: "continue" | "hold" | "retessellate" | "zeroback" | "pending_observation";
    rationale: string;
    next_observation_required: string;
  };
  audit_events: string[];
};

export type NepsisMvpPacket = {
  schema_id: string;
  schema_version: string;
  packet_id: string;
  created_at: string;
  case_id: NepsisMvpCaseId;
  input_text: string;
  observations: string[];
  constraints: string[];
  red_channel: {
    active_hazards: Record<string, unknown>[];
    ruled_out_hazards: Record<string, unknown>[];
    missing_discriminators: string[];
    escalation_required: boolean;
    rationale: string;
  };
  blue_channel: {
    hypotheses: Array<{
      id: string;
      label: string;
      likelihood: string;
      supporting_features: string[];
      contradicting_features: string[];
      needed_discriminators: string[];
      action_threshold: string;
    }>;
    evaluation_axes: Record<
      string,
      {
        description: string;
        by_hypothesis: Record<string, string>;
      }
    >;
    supporting_features: string[];
    contradicting_features: string[];
    needed_discriminators: string[];
  };
  contradiction_monitor: {
    contradictions: Record<string, unknown>[];
    contradiction_density: number;
    density_basis: {
      model: string;
      formula: string;
      contradiction_count: number;
      runtime_gate_input: boolean;
      runtime_gate_note?: string;
    };
    stability_status: string;
  };
  denominator_collapse: {
    detected: boolean;
    missing_hypothesis_classes: string[];
    retessellation_required: boolean;
  };
  voronoi_commitment: {
    recommended_action: string;
    threshold_basis: string;
    consequence_weighting: string;
  };
  non_quiescence: {
    wrong_manifold_possible: boolean;
    reason: string;
    next_required_move: string;
  };
  still: NepsisMvpStill;
  zeroback: {
    triggered: boolean;
    reason: string;
    reset_scope: string;
  };
  state_feedback: NepsisMvpStateFeedback;
  audit_trace: NepsisMvpAuditEvent[];
  final_output: {
    concise_recommendation: string;
    caveats: string[];
    required_next_discriminators: string[];
  };
};

export type NepsisMvpPayload = {
  case_id: NepsisMvpCaseId;
  input_text?: string;
};

export type EngineDeleteSessionResponse = {
  deleted: true;
  session_id: string;
  family: EngineFamily;
  remaining_sessions: number;
};

const ENGINE_PROXY_BASE = "/api/engine";

export class EngineClientError extends Error {
  status: number;
  detail?: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "EngineClientError";
    this.status = status;
    this.detail = detail;
  }
}

async function parseResponse<T>(res: Response): Promise<T> {
  const contentType = res.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await res.json() : await res.text();

  if (!res.ok) {
    const message =
      typeof payload === "object" && payload !== null && "error" in payload
        ? String((payload as { error: unknown }).error)
        : `Engine request failed with status ${res.status}`;
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : undefined;
    throw new EngineClientError(message, res.status, detail);
  }

  return payload as T;
}

async function requestEngine<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method?.toUpperCase() ?? "GET";
  const headers =
    method === "GET" || method === "HEAD" ? new Headers(init?.headers) : withCsrfHeader(init?.headers);
  const res = await fetch(`${ENGINE_PROXY_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers,
  });
  return parseResponse<T>(res);
}

async function requestEngineAllowingPhaseRejection<T>(
  path: string,
  init?: RequestInit,
): Promise<T | EnginePhaseRejection> {
  const method = init?.method?.toUpperCase() ?? "GET";
  const headers =
    method === "GET" || method === "HEAD" ? new Headers(init?.headers) : withCsrfHeader(init?.headers);
  const res = await fetch(`${ENGINE_PROXY_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers,
  });
  const contentType = res.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await res.json() : await res.text();
  if (res.status === 409 && isPhaseRejection(payload)) {
    return payload;
  }
  if (!res.ok) {
    const message =
      typeof payload === "object" && payload !== null && "error" in payload
        ? String((payload as { error: unknown }).error)
        : `Engine request failed with status ${res.status}`;
    const detail =
      typeof payload === "object" && payload !== null && "detail" in payload
        ? (payload as { detail: unknown }).detail
        : undefined;
    throw new EngineClientError(message, res.status, detail);
  }
  return payload as T;
}

export function isPhaseRejection(value: unknown): value is EnginePhaseRejection {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { schema_id?: unknown }).schema_id === "nepsis.phase_rejection"
  );
}

function jsonRequest(method: "POST" | "PUT" | "PATCH", body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export const engineClient = {
  getHealth(): Promise<{ ok: boolean }> {
    return requestEngine<{ ok: boolean }>("/health", { method: "GET" });
  },

  getRoutes(): Promise<{ routes: EngineRoute[] }> {
    return requestEngine<{ routes: EngineRoute[] }>("/routes", { method: "GET" });
  },

  createSession(payload: EngineCreateSessionPayload): Promise<EngineSessionSummary> {
    return requestEngine<EngineSessionSummary>("/sessions", jsonRequest("POST", payload));
  },

  listSessions(): Promise<{ sessions: EngineSessionSummary[] }> {
    return requestEngine<{ sessions: EngineSessionSummary[] }>("/sessions", { method: "GET" });
  },

  getSession(sessionId: string): Promise<EngineSessionSummary> {
    return requestEngine<EngineSessionSummary>(`/sessions/${encodeURIComponent(sessionId)}`, { method: "GET" });
  },

  deleteSession(sessionId: string): Promise<EngineDeleteSessionResponse> {
    return requestEngine<EngineDeleteSessionResponse>(`/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
    });
  },

  stepSession(sessionId: string, payload: EngineStepPayload): Promise<EngineStepResponse> {
    return requestEngine<EngineStepResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/step`,
      jsonRequest("POST", payload),
    );
  },

  reframeSession(
    sessionId: string,
    payload: EngineReframePayload,
  ): Promise<{ session_id: string; frame: EngineFrame; stage: string } & EngineLineage> {
    return requestEngine<{ session_id: string; frame: EngineFrame; stage: string } & EngineLineage>(
      `/sessions/${encodeURIComponent(sessionId)}/reframe`,
      jsonRequest("POST", payload),
    );
  },

  getSessionPackets(sessionId: string): Promise<EnginePacketResponse> {
    return requestEngine<EnginePacketResponse>(`/sessions/${encodeURIComponent(sessionId)}/packets`, {
      method: "GET",
    });
  },

  getSessionProvenance(sessionId: string): Promise<PacketProvenanceResponse> {
    return requestEngine<PacketProvenanceResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/provenance`,
      { method: "GET" },
    );
  },

  getSessionAuditExport(sessionId: string): Promise<SessionAuditExport> {
    return requestEngine<SessionAuditExport>(
      `/sessions/${encodeURIComponent(sessionId)}/audit-export`,
      { method: "GET" },
    );
  },

  updateWorkspaceState(
    sessionId: string,
    payload: EngineWorkspacePayload,
  ): Promise<EngineSessionSummary> {
    return requestEngine<EngineSessionSummary>(
      `/sessions/${encodeURIComponent(sessionId)}/workspace`,
      jsonRequest("POST", payload),
    );
  },

  stageAuditSession(
    sessionId: string,
    payload?: EngineStageAuditPayload,
  ): Promise<EngineStageAuditResponse> {
    if (payload && payload.context) {
      return requestEngine<EngineStageAuditResponse>(
        `/sessions/${encodeURIComponent(sessionId)}/stage-audit`,
        jsonRequest("POST", payload),
      );
    }
    return requestEngine<EngineStageAuditResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/stage-audit`,
      { method: "GET" },
    );
  },

  runMvp(payload: NepsisMvpPayload): Promise<NepsisMvpPacket> {
    return requestEngine<NepsisMvpPacket>("/mvp", jsonRequest("POST", payload));
  },

  getOperatorSessionState(): Promise<EngineOperatorResponse> {
    return requestEngine<EngineOperatorResponse>("/operator/session", { method: "GET" });
  },

  lockOperatorFrame(payload: EngineOperatorFramePayload): Promise<EngineOperatorResult> {
    return requestEngineAllowingPhaseRejection<EngineOperatorResponse>(
      "/operator/frame",
      jsonRequest("POST", payload),
    );
  },

  runOperatorReport(payload: EngineOperatorReportPayload): Promise<EngineOperatorResult> {
    return requestEngineAllowingPhaseRejection<EngineOperatorResponse>(
      "/operator/report",
      jsonRequest("POST", payload),
    );
  },

  lockOperatorReport(): Promise<EngineOperatorResult> {
    return requestEngineAllowingPhaseRejection<EngineOperatorResponse>(
      "/operator/report/lock",
      jsonRequest("POST", {}),
    );
  },

  setOperatorThresholdDecision(payload: {
    decision: "recommend" | "hold";
    hold_reason?: string;
  }): Promise<EngineOperatorResult> {
    return requestEngineAllowingPhaseRejection<EngineOperatorResponse>(
      "/operator/threshold",
      jsonRequest("POST", payload),
    );
  },

  commitOperatorIteration(payload: {
    carry_forward_frame?: Record<string, unknown>;
  }): Promise<EngineOperatorResult> {
    return requestEngineAllowingPhaseRejection<EngineOperatorResponse>(
      "/operator/commit",
      jsonRequest("POST", payload),
    );
  },

  abandonOperatorSession(payload: { reason?: string } = {}): Promise<EngineOperatorResponse> {
    return requestEngine<EngineOperatorResponse>("/operator/abandon", jsonRequest("POST", payload));
  },
};
