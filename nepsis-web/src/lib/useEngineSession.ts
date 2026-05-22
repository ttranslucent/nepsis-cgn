"use client";

import { useCallback, useState } from "react";

import {
  EngineClientError,
  type EngineCreateSessionPayload,
  type EngineDeleteSessionResponse,
  type EngineFrame,
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

export function useEngineSession() {
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

  const applyOperatorResponse = useCallback((result: EngineOperatorResponse) => {
    setState((prev) => ({
      ...prev,
      activeSession: result.session,
      sessions: upsertSession(prev.sessions, result.session),
      lastStep: result.step ?? prev.lastStep,
      lastAudit: result.audit ?? prev.lastAudit,
      packets:
        result.packet != null
          ? [...prev.packets, result.packet]
          : result.step?.iteration_packet != null
            ? [...prev.packets, result.step.iteration_packet]
            : prev.packets,
    }));
  }, []);

  const applyOperatorResult = useCallback(
    (result: EngineOperatorResult | undefined): EngineOperatorResult | undefined => {
      if (!result) {
        return undefined;
      }
      if (isPhaseRejection(result)) {
        setState((prev) => ({ ...prev, error: phaseRejectionMessage(result) }));
        return result;
      }
      applyOperatorResponse(result);
      return result;
    },
    [applyOperatorResponse],
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
    const data = await run(() => engineClient.listSessions());
    if (!data) {
      return undefined;
    }
    setState((prev) => {
      const active =
        prev.activeSession == null
          ? null
          : data.sessions.find((session) => session.session_id === prev.activeSession?.session_id) ?? null;
      return {
        ...prev,
        sessions: data.sessions,
        activeSession: active,
      };
    });
    return data.sessions;
  }, [run]);

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
      const targetId = sessionId ?? state.activeSession?.session_id;
      if (!targetId) {
        setState((prev) => ({ ...prev, error: "No session selected for packet refresh." }));
        return undefined;
      }
      const packetResponse = await run(() => engineClient.getSessionPackets(targetId));
      if (!packetResponse) {
        return undefined;
      }
      setState((prev) => ({
        ...prev,
        packets: packetResponse.packets,
      }));
      return packetResponse;
    },
    [run, state.activeSession],
  );

  const updateWorkspaceState = useCallback(
    async (sessionId: string, payload: EngineWorkspacePayload): Promise<EngineSessionSummary | undefined> => {
      try {
        const session = await engineClient.updateWorkspaceState(sessionId, payload);
        setState((prev) => ({
          ...prev,
          activeSession:
            prev.activeSession?.session_id === session.session_id ? session : prev.activeSession,
          sessions: upsertSession(prev.sessions, session),
        }));
        return session;
      } catch (error) {
        const message =
          error instanceof EngineClientError && error.status === 401
            ? "Sign in to access engine session controls."
            : error instanceof Error
              ? error.message
              : "Workspace state update failed";
        setState((prev) => ({ ...prev, error: message }));
        return undefined;
      }
    },
    [],
  );

  const deleteSession = useCallback(
    async (sessionId?: string): Promise<EngineDeleteSessionResponse | undefined> => {
      const targetId = sessionId ?? state.activeSession?.session_id;
      if (!targetId) {
        setState((prev) => ({ ...prev, error: "No session selected for delete." }));
        return undefined;
      }
      const result = await run(() => engineClient.deleteSession(targetId));
      if (!result) {
        return undefined;
      }
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
      return result;
    },
    [run, state.activeSession],
  );

  const stageAudit = useCallback(
    async (
      payload?: EngineStageAuditPayload,
      sessionId?: string,
    ): Promise<EngineStageAuditResponse | undefined> => {
      const targetId = sessionId ?? state.activeSession?.session_id;
      if (!targetId) {
        setState((prev) => ({ ...prev, error: "No session selected for stage audit." }));
        return undefined;
      }
      const audit = await run(() => engineClient.stageAuditSession(targetId, payload));
      if (!audit) {
        return undefined;
      }
      setState((prev) => ({
        ...prev,
        lastAudit: audit,
      }));
      return audit;
    },
    [run, state.activeSession],
  );

  const getOperatorSessionState = useCallback(async (): Promise<EngineOperatorResponse | undefined> => {
    const result = await run(() => engineClient.getOperatorSessionState());
    if (!result) {
      return undefined;
    }
    applyOperatorResponse(result);
    return result;
  }, [applyOperatorResponse, run]);

  const lockOperatorFrame = useCallback(
    async (payload: EngineOperatorFramePayload): Promise<EngineOperatorResult | undefined> => {
      const result = await run(() => engineClient.lockOperatorFrame(payload));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run],
  );

  const runOperatorReport = useCallback(
    async (payload: EngineOperatorReportPayload): Promise<EngineOperatorResult | undefined> => {
      const result = await run(() => engineClient.runOperatorReport(payload));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run],
  );

  const lockOperatorReport = useCallback(async (): Promise<EngineOperatorResult | undefined> => {
    const result = await run(() => engineClient.lockOperatorReport());
    return applyOperatorResult(result);
  }, [applyOperatorResult, run]);

  const setOperatorThresholdDecision = useCallback(
    async (payload: { decision: "recommend" | "hold"; hold_reason?: string }): Promise<EngineOperatorResult | undefined> => {
      const result = await run(() => engineClient.setOperatorThresholdDecision(payload));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run],
  );

  const commitOperatorIteration = useCallback(
    async (payload: { carry_forward_frame?: Record<string, unknown> }): Promise<EngineOperatorResult | undefined> => {
      const result = await run(() => engineClient.commitOperatorIteration(payload));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run],
  );

  const abandonOperatorSession = useCallback(
    async (payload: { reason?: string } = {}): Promise<EngineOperatorResponse | undefined> => {
      const result = await run(() => engineClient.abandonOperatorSession(payload));
      if (!result) {
        return undefined;
      }
      applyOperatorResponse(result);
      return result;
    },
    [applyOperatorResponse, run],
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
    getOperatorSessionState,
    lockOperatorFrame,
    runOperatorReport,
    lockOperatorReport,
    setOperatorThresholdDecision,
    commitOperatorIteration,
    abandonOperatorSession,
  };
}

export type { EngineFrame };
