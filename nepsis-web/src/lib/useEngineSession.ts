"use client";

import { useCallback, useState } from "react";

import {
  EngineClientError,
  type EngineAssistDisposition,
  type EngineCreateSessionPayload,
  type EngineDeleteSessionResponse,
  type EngineFrame,
  type EngineOperatorFramePayload,
  type EngineOperatorPacket,
  type EngineOperatorPacketState,
  type EngineOperatorPacketResult,
  type EngineOperatorReportPayload,
  type EngineOperatorResponse,
  type EngineOperatorResult,
  type EnginePacketResponse,
  type PacketProvenanceResponse,
  type EngineReframePayload,
  type EngineRoute,
  type SessionAuditExport,
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
  operatorPacket: EngineOperatorPacket | null;
  operatorPacketState: EngineOperatorPacketState | null;
  provenance: PacketProvenanceResponse | null;
  auditExport: SessionAuditExport | null;
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

function isOperatorPacket(value: unknown): value is EngineOperatorPacket {
  return Boolean(
    value &&
      typeof value === "object" &&
      (value as { schema_id?: unknown }).schema_id === "nepsis.operator_packet",
  );
}

function isOperatorPacketState(value: unknown): value is EngineOperatorPacketState {
  return Boolean(
    value &&
      typeof value === "object" &&
      (value as { schema_id?: unknown }).schema_id === "nepsis.operator_packet_state",
  );
}

function packetFrameToEngineFrame(packet: EngineOperatorPacket): EngineFrame | null {
  const frame = packet.frame;
  if (!frame || typeof frame !== "object") {
    return null;
  }
  return {
    frame_id: `${packet.packet_id}:frame`,
    frame_version: 1,
    text: typeof frame.text === "string" ? frame.text : "",
    objective_type: typeof frame.objective_type === "string" ? frame.objective_type : "sensemake",
    domain: typeof frame.domain === "string" ? frame.domain : null,
    time_horizon: typeof frame.time_horizon === "string" ? frame.time_horizon : null,
    rationale_for_change:
      typeof frame.rationale_for_change === "string" ? frame.rationale_for_change : null,
    constraints_hard: Array.isArray(frame.constraints_hard)
      ? frame.constraints_hard.filter((item): item is string => typeof item === "string")
      : [],
    constraints_soft: Array.isArray(frame.constraints_soft)
      ? frame.constraints_soft.filter((item): item is string => typeof item === "string")
      : [],
    costs: { c_fp: null, c_fn: null, c_delay: null },
  };
}

function packetLatestAudit(packet: EngineOperatorPacket): EngineStageAuditResponse | undefined {
  return packet.latest_audit && Object.keys(packet.latest_audit).length > 0
    ? (packet.latest_audit as EngineStageAuditResponse)
    : undefined;
}

function operatorPacketToResponse(packet: EngineOperatorPacket): EngineOperatorResponse {
  const session: EngineSessionSummary = {
    session_id: packet.loop_id,
    family: packet.family,
    created_at: packet.created_at,
    stage: packet.phase === "frame_draft" ? "draft" : "operator",
    steps: packet.latest_step ? 1 : 0,
    packet_count: packet.audit_trace.length + packet.previous_trace.length,
    frame: packetFrameToEngineFrame(packet),
    branch_id: null,
    lineage_version: null,
    parent_frame_id: null,
    operator_phase: packet.phase,
    operator_ambient: false,
  };
  return {
    session_id: packet.loop_id,
    phase: packet.phase,
    legal_next_tools: packet.legal_next_tools,
    session,
    audit: packetLatestAudit(packet),
    step: packet.latest_step as EngineStepResponse | undefined,
    packet,
  };
}

function operatorPacketStateToResponse(
  state: EngineOperatorPacketState,
  packet: EngineOperatorPacket,
): EngineOperatorResponse {
  return operatorPacketToResponse({
    ...packet,
    phase: state.phase,
    legal_next_tools: state.legal_next_tools,
    audit_trace: state.audit_trace,
    latest_audit: state.latest_audit,
  });
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
    operatorPacket: null,
    operatorPacketState: null,
    provenance: null,
    auditExport: null,
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
      provenance: null,
      auditExport: null,
    }));
  }, []);

  const applyOperatorResult = useCallback(
    (result: EngineOperatorPacketResult | undefined): EngineOperatorResult | undefined => {
      if (!result) {
        return undefined;
      }
      if (isPhaseRejection(result)) {
        setState((prev) => ({ ...prev, error: phaseRejectionMessage(result) }));
        return result;
      }
      if (isOperatorPacket(result)) {
        setState((prev) => ({ ...prev, operatorPacket: result, operatorPacketState: null }));
        const response = operatorPacketToResponse(result);
        applyOperatorResponse(response);
        return response;
      }
      return undefined;
    },
    [applyOperatorResponse],
  );

  const applyOperatorPacketState = useCallback(
    (
      result: EngineOperatorPacketState,
      packet: EngineOperatorPacket | null,
    ): EngineOperatorResponse | undefined => {
      const response = packet ? operatorPacketStateToResponse(result, packet) : undefined;
      setState((prev) => ({
        ...prev,
        operatorPacketState: result,
        activeSession: response?.session ?? prev.activeSession,
        sessions: response ? upsertSession(prev.sessions, response.session) : prev.sessions,
        lastAudit: response?.audit ?? prev.lastAudit,
        provenance: null,
        auditExport: null,
      }));
      return response;
    },
    [],
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
        operatorPacket: null,
        operatorPacketState: null,
        provenance: null,
        auditExport: null,
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
        const provenance = await engineClient.getSessionProvenance(sessionId).catch(() => null);
        return { session, packetResponse, provenance };
      });
      if (!loaded) {
        return undefined;
      }
      setState((prev) => ({
        ...prev,
        activeSession: loaded.session,
        sessions: upsertSession(prev.sessions, loaded.session),
        packets: loaded.packetResponse.packets,
        operatorPacket: null,
        operatorPacketState: null,
        provenance: loaded.provenance,
        auditExport: null,
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
        provenance: null,
        auditExport: null,
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

  const refreshProvenance = useCallback(
    async (sessionId?: string): Promise<PacketProvenanceResponse | undefined> => {
      const targetId = sessionId ?? state.activeSession?.session_id;
      if (!targetId) {
        setState((prev) => ({ ...prev, error: "No session selected for provenance refresh." }));
        return undefined;
      }
      const provenance = await run(() => engineClient.getSessionProvenance(targetId));
      if (!provenance) {
        return undefined;
      }
      setState((prev) => ({ ...prev, provenance }));
      return provenance;
    },
    [run, state.activeSession],
  );

  const exportSessionAudit = useCallback(
    async (sessionId?: string): Promise<SessionAuditExport | undefined> => {
      const targetId = sessionId ?? state.activeSession?.session_id;
      if (!targetId) {
        setState((prev) => ({ ...prev, error: "No session selected for audit export." }));
        return undefined;
      }
      const auditExport = await run(() => engineClient.getSessionAuditExport(targetId));
      if (!auditExport) {
        return undefined;
      }
      setState((prev) => ({ ...prev, auditExport }));
      return auditExport;
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
          operatorPacket: activeSession ? prev.operatorPacket : null,
          operatorPacketState: activeSession ? prev.operatorPacketState : null,
          provenance: activeSession ? prev.provenance : null,
          auditExport: activeSession ? prev.auditExport : null,
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
    const result = await run(async () =>
      state.operatorPacket
        ? engineClient.getOperatorSessionState({ packet: state.operatorPacket })
        : engineClient.startOperatorPacket(),
    );
    if (!result) {
      return undefined;
    }
    if (isOperatorPacketState(result)) {
      return applyOperatorPacketState(result, state.operatorPacket);
    }
    const applied = applyOperatorResult(result);
    return isPhaseRejection(applied) ? undefined : applied;
  }, [applyOperatorPacketState, applyOperatorResult, run, state.operatorPacket]);

  const lockOperatorFrame = useCallback(
    async (
      payload: EngineOperatorFramePayload & { assist_acceptances?: EngineAssistDisposition[] },
    ): Promise<EngineOperatorResult | undefined> => {
      const result = await run(async () => {
        const packet =
          state.operatorPacket ??
          (await engineClient.startOperatorPacket({
            family: payload.family,
            frame: payload.frame,
            governance: payload.governance ?? payload.governance_costs,
          }));
        return engineClient.lockOperatorFrame({ ...payload, packet });
      });
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run, state.operatorPacket],
  );

  const runOperatorReport = useCallback(
    async (payload: EngineOperatorReportPayload): Promise<EngineOperatorResult | undefined> => {
      const packet = state.operatorPacket;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No operator packet is active." }));
        return undefined;
      }
      const result = await run(() => engineClient.runOperatorReport({ ...payload, packet }));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run, state.operatorPacket],
  );

  const lockOperatorReport = useCallback(async (): Promise<EngineOperatorResult | undefined> => {
    const packet = state.operatorPacket;
    if (!packet) {
      setState((prev) => ({ ...prev, error: "No operator packet is active." }));
      return undefined;
    }
    const result = await run(() => engineClient.lockOperatorReport({ packet }));
    return applyOperatorResult(result);
  }, [applyOperatorResult, run, state.operatorPacket]);

  const setOperatorThresholdDecision = useCallback(
    async (payload: {
      decision: "recommend" | "hold";
      hold_reason?: string;
      assist_acceptances?: EngineAssistDisposition[];
    }): Promise<EngineOperatorResult | undefined> => {
      const packet = state.operatorPacket;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No operator packet is active." }));
        return undefined;
      }
      const result = await run(() => engineClient.setOperatorThresholdDecision({ ...payload, packet }));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run, state.operatorPacket],
  );

  const startOperatorV3LayerLoop = useCallback(
    async (payload: {
      goal: string;
      scope: string;
      initial_context?: string;
    }): Promise<EngineOperatorResult | undefined> => {
      const packet = state.operatorPacket;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No operator packet is active." }));
        return undefined;
      }
      const result = await run(() => engineClient.startOperatorV3LayerLoop({ ...payload, packet }));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run, state.operatorPacket],
  );

  const setOperatorV3LayerField = useCallback(
    async (payload: {
      layer: string;
      field: string;
      value: unknown;
      assist_acceptances?: EngineAssistDisposition[];
    }): Promise<EngineOperatorResult | undefined> => {
      const packet = state.operatorPacket;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No operator packet is active." }));
        return undefined;
      }
      const result = await run(() => engineClient.setOperatorV3LayerField({ ...payload, packet }));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run, state.operatorPacket],
  );

  const setOperatorV3LayerArtifact = useCallback(
    async (payload: {
      layer: string;
      artifact: Record<string, unknown>;
    }): Promise<EngineOperatorResult | undefined> => {
      const packet = state.operatorPacket;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No operator packet is active." }));
        return undefined;
      }
      let currentPacket = packet;
      let lastResult: EngineOperatorPacketResult | undefined;
      for (const [field, value] of Object.entries(payload.artifact)) {
        const result = await run(() =>
          engineClient.setOperatorV3LayerField({
            packet: currentPacket,
            layer: payload.layer,
            field,
            value,
          }),
        );
        if (!result) {
          return undefined;
        }
        lastResult = result;
        const applied = applyOperatorResult(result);
        if (isPhaseRejection(applied)) {
          return applied;
        }
        if (!isOperatorPacket(result)) {
          return applied;
        }
        currentPacket = result;
      }
      return applyOperatorResult(lastResult);
    },
    [applyOperatorResult, run, state.operatorPacket],
  );

  const proposeOperatorV3Layer = useCallback(
    async (payload: { layer: string }): Promise<EngineOperatorResult | undefined> => {
      const packet = state.operatorPacket;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No operator packet is active." }));
        return undefined;
      }
      const result = await run(() => engineClient.proposeOperatorV3Layer({ ...payload, packet }));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run, state.operatorPacket],
  );

  const lockOperatorV3Layer = useCallback(
    async (payload: {
      layer: string;
      lock_assertion: Record<string, unknown>;
    }): Promise<EngineOperatorResult | undefined> => {
      const packet = state.operatorPacket;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No operator packet is active." }));
        return undefined;
      }
      const result = await run(() => engineClient.lockOperatorV3Layer({ ...payload, packet }));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run, state.operatorPacket],
  );

  const commitOperatorIteration = useCallback(
    async (payload: {
      carry_forward_frame?: Record<string, unknown>;
      assist_acceptances?: EngineAssistDisposition[];
    }): Promise<EngineOperatorResult | undefined> => {
      const packet = state.operatorPacket;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No operator packet is active." }));
        return undefined;
      }
      const result = await run(() => engineClient.commitOperatorIteration({ ...payload, packet }));
      return applyOperatorResult(result);
    },
    [applyOperatorResult, run, state.operatorPacket],
  );

  const abandonOperatorSession = useCallback(
    async (payload: { reason?: string } = {}): Promise<EngineOperatorResponse | undefined> => {
      const packet = state.operatorPacket;
      if (!packet) {
        setState((prev) => ({ ...prev, error: "No operator packet is active." }));
        return undefined;
      }
      const result = await run(() => engineClient.abandonOperatorSession({ ...payload, packet }));
      if (!result) {
        return undefined;
      }
      const applied = applyOperatorResult(result);
      return isPhaseRejection(applied) ? undefined : applied;
    },
    [applyOperatorResult, run, state.operatorPacket],
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
    refreshProvenance,
    exportSessionAudit,
    deleteSession,
    stageAudit,
    updateWorkspaceState,
    getOperatorSessionState,
    lockOperatorFrame,
    runOperatorReport,
    lockOperatorReport,
    setOperatorThresholdDecision,
    startOperatorV3LayerLoop,
    setOperatorV3LayerField,
    setOperatorV3LayerArtifact,
    proposeOperatorV3Layer,
    lockOperatorV3Layer,
    commitOperatorIteration,
    abandonOperatorSession,
  };
}

export type { EngineFrame };
