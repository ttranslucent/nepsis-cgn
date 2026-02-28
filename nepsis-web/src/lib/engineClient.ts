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

export type EngineSessionSummary = {
  session_id: string;
  family: EngineFamily;
  created_at: string;
  stage: string;
  steps: number;
  packet_count: number;
  frame: EngineFrame | null;
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
  governance?: Record<string, unknown>;
  iteration_packet?: Record<string, unknown>;
  session: EngineSessionSummary;
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
  ): Promise<{ session_id: string; frame: EngineFrame; stage: string }> {
    return requestEngine<{ session_id: string; frame: EngineFrame; stage: string }>(
      `/sessions/${encodeURIComponent(sessionId)}/reframe`,
      jsonRequest("POST", payload),
    );
  },

  getSessionPackets(sessionId: string): Promise<EnginePacketResponse> {
    return requestEngine<EnginePacketResponse>(`/sessions/${encodeURIComponent(sessionId)}/packets`, {
      method: "GET",
    });
  },
};
