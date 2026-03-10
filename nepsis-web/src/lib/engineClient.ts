export type EngineFamily = "puzzle" | "clinical" | "safety";

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
};

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
  };
};

export type EnginePacketResponse = {
  session_id: string;
  count: number;
  packets: Record<string, unknown>[];
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
  const res = await fetch(`${ENGINE_PROXY_BASE}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      ...(init?.headers ?? {}),
    },
  });
  return parseResponse<T>(res);
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
};
