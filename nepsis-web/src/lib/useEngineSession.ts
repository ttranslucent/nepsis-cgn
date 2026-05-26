"use client";

import { useCallback, useRef, useState } from "react";

import {
  EngineClientError,
  type EngineCreateSessionPayload,
  type EngineDeleteSessionResponse,
  type EngineFrame,
  type EngineOperatorPacket,
  type EngineOperatorPacketResult,
  type EngineOperatorFramePayload,
  type EngineOperatorReportPayload,
  type EngineOperatorResponse,
  type EngineOperatorResult,
  type EnginePacketResponse,
  type EngineReframePayload,
  type EngineRoute,
  type EngineStageAuditPayload,
  type EngineStageAuditResponse,
  type EngineSessionSummary,
  type EngineStepPayload,
  type EngineStepResponse,
  type EngineWorkspacePayload,
  engineClient,
  isPhaseRejection,
} from "@/lib/engineClient";

type EngineState = {
  loading: boolean;
  error: string | null;
  routes: EngineRoute[];
  healthy: boolean | null;
  sessions: EngineSessionSummary[];
  activeSession: EngineSessionSummary | null;
  packets: Record<string, unknown>[];
  lastStep: EngineStepResponse | null;
  lastAudit: EngineStageAuditResponse | null;
  operatorPacket: EngineOperatorPacket | null;
};

function upsertSession(
  sessions: EngineSessionSummary[],
  incoming: EngineSessionSummary,
): EngineSessionSummary[] {
  const idx = sessions.findIndex((session) => session.session_id === incoming.session_id);
  if (idx === -1) {
    return [incoming, ...sessions];
  }
  const next = [...sessions];
  next[idx] = incoming;
  return next;
}

function phaseRejectionMessage(result: EngineOperatorResult): string {
  if (!isPhaseRejection(result)) {
    return "";
  }
  const missing = result.missing.length > 0 ? ` Missing: ${result.missing.join(", ")}.` : "";
  const next = result.legal_next_tools.length > 0 ? ` Next: ${result.legal_next_tools.join(", ")}.` : "";
  return `${result.attempted_tool} refused at ${result.current_phase}.${missing}${next}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function isStageAuditResponse(value: unknown): value is EngineStageAuditResponse {
  return (
    isRecord(value) &&
    isRecord(value.policy) &&
    isRecord(value.frame) &&
    isRecord(value.interpretation) &&
    isRecord(value.threshold)
  );
}

function isStepResponse(value: unknown): value is EngineStepResponse {
  return isRecord(value) && typeof value.decision === "string" && isRecord(value.posterior);
}

function packetFrameToEngineFrame(packet: EngineOperatorPacket): EngineFrame | null {
  const frame = packet.frame;
  if (!isRecord(frame)) {
    return null;
  }
  const costs = isRecord(packet.governance_costs) ? packet.governance_costs : {};
  return {
    frame_id: `${packet.loop_id}:${packet.packet_id}`,
    frame_version: Math.max(1, packet.audit_trace.length + 1),
    text: stringValue(frame.text),
    objective_type: stringValue(frame.objective_type, "sensemake"),
    domain: typeof frame.domain === "string" ? frame.domain : null,
    time_horizon: typeof frame.time_horizon === "string" ? frame.time_horizon : null,
    rationale_for_change:
      typeof frame.rationale_for_change === "string" ? frame.rationale_for_change : null,
    constraints_hard: stringList(frame.constraints_hard),
    constraints_soft: stringList(frame.constraints_soft),
    costs: {
      c_fp: numberValue(costs.c_fp),
      c_fn: numberValue(costs.c_fn),
      c_delay: numberValue(costs.c_delay),
    },
  };
}

function operatorPacketSession(packet: EngineOperatorPacket): EngineSessionSummary {
  return {
    session_id: packet.loop_id,
    family: packet.family,
    created_at: packet.created_at,
    stage: packet.phase,
    steps: packet.audit_trace.length,
    packet_count: packet.audit_trace.length,
    frame: packetFrameToEngineFrame(packet),
    branch_id: `packet-${packet.loop_id.slice(0, 8)}`,
    lineage_version: Math.max(1, (packet.previous_trace?.length ?? 0) + 1),
    parent_frame_id: null,
    frame_ref: packet.packet_id,
    workspace_state: null,
    operator_phase: packet.phase,
  };
}

function operatorPacketResponse(packet: EngineOperatorPacket): EngineOperatorResponse {
  const audit = isStageAuditResponse(packet.latest_audit) ? packet.latest_audit : undefined;
  const step = isStepResponse(packet.latest_step) ? packet.latest_step : undefined;
  return {
    session_id: packet.loop_id,
    phase: packet.phase,
    legal_next_tools: packet.legal_next_tools,
    session: operatorPacketSession(packet),
    audit,
    step,
    packet: packet as unknown as Record<string, unknown>,
  };
}

export function useEngineSession() {
  const operatorPacketRef = useRef<EngineOperatorPacket | null>(null);
  const [state, setState] = useState<EngineState>({
    loading: false,
    error: null,
    routes: [],
    healthy: null,
    sessions: [],
    activeSession: null,
    packets: [],
    lastStep: null,
    lastAudit: null,
    operatorPacket: null,
  });

  const run = useCallback(async <T,>(op: () => Promise<T>): Promise<T | undefined> => {
    setState((prev) => ({ ...prev, loading: true, error: null }));
    try {
      return await op();
    } catch (error) {
      const message =
        error instanceof EngineClientError && error.status === 401
          ? "Sign in to access engine session controls."
          : error instanceof Error
            ? error.message
            : "Engine request failed";
      setState((prev) => ({ ...prev, error: message }));
      return undefined;
    } finally {
      setState((prev) => ({ ...prev, loading: false }));
    }
  }, []);

  const clearError = useCallback(() => {
    setState((prev) => ({ ...prev, error: null }));
  }, []);

  const applyOperatorPacketResponse = useCallback((packet: EngineOperatorPacket) => {
    operatorPacketRef.current = packet;
    const response = operatorPacketResponse(packet);
    setState((prev) => ({
      ...prev,
      operatorPacket: packet,
      activeSession: response.session,
      sessions: upsertSession(prev.sessions, response.session),
      lastStep: response.step ?? prev.lastStep,
      lastAudit: response.audit ?? prev.lastAudit,
      packets: [...prev.packets, packet as unknown as Record<string, unknown>],
    }));
    return response;
  }, []);

  const applyOperatorPacketResult = useCallback(
    (result: EngineOperatorPacketResult | undefined): EngineOperatorResult | undefined => {
      if (!result) {
        return undefined;
      }
      if (isPhaseRejection(result)) {
        setState((prev) => ({ ...prev, error: phaseRejectionMessage(result) }));
        return result;
      }
      return applyOperatorPacketResponse(result);
    },
    [applyOperatorPacketResponse],
  );

  const refreshHealth = useCallback(async () => {
    const data = await run(() => engineClient.getHealth());
    if (!data) {
      setState((prev) => ({ ...prev, healthy: false }));
      return undefined;
    }
    setState((prev) => ({ ...prev, healthy: !!data.ok }));
    return data;
  }, [run]);

  const refreshRoutes = useCallback(async () => {
    const data = await run(() => engineClient.getRoutes());
    if (!data) {
      return undefined;
    }
    setState((prev) => ({ ...prev, routes: data.routes }));
    return data.routes;
  }, [run]);

  const refreshSessions = useCallback(async () => {
    return state.sessions;
  }, [state.sessions]);

  const createSession = useCallback(
    async (payload: EngineCreateSessionPayload) => {
      const session = await run(() => engineClient.createSession(payload));
      if (!session) {
        return undefined;
      }
      setState((prev) => ({
        ...prev,
        activeSession: session,
        sessions: upsertSession(prev.sessions, session),
        packets: [],
        lastStep: null,
        lastAudit: null,
      }));
      return session;
    },
    [run],
  );

  const loadSession = useCallback(
    async (sessionId: string) => {
      const loaded = await run(async () => {
        const [session, packetResponse] = await Promise.all([
          engineClient.getSession(sessionId),
          engineClient.getSessionPackets(sessionId),
        ]);
        return { session, packetResponse };
      });
      if (!loaded) {
        return undefined;
      }
      setState((prev) => ({
        ...prev,
        activeSession: loaded.session,
        sessions: upsertSession(prev.sessions, loaded.session),
        packets: loaded.packetResponse.packets,
        lastAudit: null,
      }));
      return loaded.session;
    },
    [run],
  );

  const step = useCallback(
    async (payload: EngineStepPayload) => {
      const active = state.activeSession;
      if (!active) {
        setState((prev) => ({ ...prev, error: "No active engine session selected." }));
        return undefined;
      }
      const stepResult = await run(() => engineClient.stepSession(active.session_id, payload));
      if (!stepResult) {
        return undefined;
      }
      setState((prev) => ({
        ...prev,
        activeSession: stepResult.session,
        sessions: upsertSession(prev.sessions, stepResult.session),
        lastStep: stepResult,
        packets:
          stepResult.iteration_packet != null
            ? [...prev.packets, stepResult.iteration_packet]
            : prev.packets,
        lastAudit: prev.lastAudit,
      }));
      return stepResult;
    },
    [run, state.activeSession],
  );

  const reframe = useCallback(
    async (payload: EngineReframePayload) => {
      const active = state.activeSession;
      if (!active) {
        setState((prev) => ({ ...prev, error: "No active engine session selected." }));
        return undefined;
      }
      const result = await run(() => engineClient.reframeSession(active.session_id, payload));
      if (!result) {
        return undefined;
      }
      const updated: EngineSessionSummary = {
        ...active,
        frame: result.frame,
        stage: result.stage,
        branch_id: result.branch_id ?? active.branch_id,
        lineage_version: result.lineage_version ?? active.lineage_version,
        parent_frame_id: result.parent_frame_id ?? null,
        frame_ref: result.frame_ref ?? active.frame_ref,
      };
      setState((prev) => ({
        ...prev,
        activeSession: updated,
        sessions: upsertSession(prev.sessions, updated),
      }));
      return result;
    },
    [run, state.activeSession],
  );

  const refreshPackets = useCallback(
    async (sessionId?: string): Promise<EnginePacketResponse | undefined> => {
      return {
        session_id: sessionId ?? state.operatorPacket?.loop_id ?? "operator-packet",
        count: state.packets.length,
        packets: state.packets,
      };
    },
    [state.operatorPacket, state.packets],
  );

  const updateWorkspaceState = useCallback(
    async (sessionId: string, payload: EngineWorkspacePayload): Promise<EngineSessionSummary | undefined> => {
      void sessionId;
      void payload;
      return state.activeSession ?? undefined;
    },
    [state.activeSession],
  );

  const deleteSession = useCallback(
    async (sessionId?: string): Promise<EngineDeleteSessionResponse | undefined> => {
      const targetId = sessionId ?? state.activeSession?.session_id;
      if (!targetId) {
        setState((prev) => ({ ...prev, error: "No session selected for delete." }));
        return undefined;
      }
      const family =
        state.sessions.find((session) => session.session_id === targetId)?.family ??
        state.activeSession?.family ??
        "safety";
      const remainingSessions = state.sessions.filter((session) => session.session_id !== targetId).length;
      setState((prev) => {
        const nextSessions = prev.sessions.filter((session) => session.session_id !== targetId);
        const activeSession =
          prev.activeSession?.session_id === targetId ? null : prev.activeSession;
        return {
          ...prev,
          sessions: nextSessions,
          activeSession,
          packets: activeSession ? prev.packets : [],
          lastStep: activeSession ? prev.lastStep : null,
          lastAudit: activeSession ? prev.lastAudit : null,
        };
      });
      return {
        deleted: true,
        session_id: targetId,
        family,
        remaining_sessions: remainingSessions,
      };
    },
    [state.activeSession, state.sessions],
  );

  const stageAudit = useCallback(
    async (
      payload?: EngineStageAuditPayload,
      sessionId?: string,
    ): Promise<EngineStageAuditResponse | undefined> => {
      void payload;
      void sessionId;
      const audit = isStageAuditResponse(state.operatorPacket?.latest_audit)
        ? state.operatorPacket.latest_audit
        : undefined;
      if (!audit) {
        return undefined;
      }
      setState((prev) => ({ ...prev, lastAudit: audit }));
      return audit;
    },
    [state.operatorPacket],
  );

  const lockOperatorFrame = useCallback(
    async (payload: EngineOperatorFramePayload): Promise<EngineOperatorResult | undefined> => {
      const result = await run(async () => {
        const packet =
          operatorPacketRef.current ??
          (await engineClient.startOperatorPacket({
            family: payload.family,
            governance: payload.governance,
            governance_costs: payload.governance_costs,
          }));
        operatorPacketRef.current = packet;
        return engineClient.lockOperatorPacketFrame({ ...payload, packet });
      });
      return applyOperatorPacketResult(result);
    },
    [applyOperatorPacketResult, run],
  );

  const runOperatorReport = useCallback(
    async (payload: EngineOperatorReportPayload): Promise<EngineOperatorResult | undefined> => {
      const packet = operatorPacketRef.current;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No active operator packet. Lock Frame first." }));
        return undefined;
      }
      const result = await run(() => engineClient.runOperatorPacketReport({ ...payload, packet }));
      return applyOperatorPacketResult(result);
    },
    [applyOperatorPacketResult, run],
  );

  const lockOperatorReport = useCallback(async (): Promise<EngineOperatorResult | undefined> => {
    const packet = operatorPacketRef.current;
    if (!packet) {
      setState((prev) => ({ ...prev, error: "No active operator packet. Run report first." }));
      return undefined;
    }
    const result = await run(() => engineClient.lockOperatorPacketReport({ packet }));
    return applyOperatorPacketResult(result);
  }, [applyOperatorPacketResult, run]);

  const setOperatorThresholdDecision = useCallback(
    async (payload: { decision: "recommend" | "hold"; hold_reason?: string }): Promise<EngineOperatorResult | undefined> => {
      const packet = operatorPacketRef.current;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No active operator packet. Lock report first." }));
        return undefined;
      }
      const result = await run(() =>
        engineClient.setOperatorPacketThresholdDecision({ ...payload, packet }),
      );
      return applyOperatorPacketResult(result);
    },
    [applyOperatorPacketResult, run],
  );

  const commitOperatorIteration = useCallback(
    async (payload: { carry_forward_frame?: Record<string, unknown> }): Promise<EngineOperatorResult | undefined> => {
      const packet = operatorPacketRef.current;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No active operator packet. Set threshold first." }));
        return undefined;
      }
      const result = await run(() => engineClient.commitOperatorPacketIteration({ ...payload, packet }));
      return applyOperatorPacketResult(result);
    },
    [applyOperatorPacketResult, run],
  );

  const abandonOperatorSession = useCallback(
    async (payload: { reason?: string } = {}): Promise<EngineOperatorResponse | undefined> => {
      const packet = operatorPacketRef.current;
      if (!packet) {
        return undefined;
      }
      const result = await run(() => engineClient.abandonOperatorPacket({ ...payload, packet }));
      const applied = applyOperatorPacketResult(result);
      return applied && !isPhaseRejection(applied) ? applied : undefined;
    },
    [applyOperatorPacketResult, run],
  );

  return {
    ...state,
    clearError,
    refreshHealth,
    refreshRoutes,
    refreshSessions,
    createSession,
    loadSession,
    step,
    reframe,
    refreshPackets,
    deleteSession,
    stageAudit,
    updateWorkspaceState,
    lockOperatorFrame,
    runOperatorReport,
    lockOperatorReport,
    setOperatorThresholdDecision,
    commitOperatorIteration,
    abandonOperatorSession,
  };
}

export type { EngineFrame };
