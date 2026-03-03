"use client";

import { useEffect, useMemo, useState } from "react";

import {
  type EngineFamily,
  type EngineFrame,
  type EngineReframePayload,
  type EngineStepResponse,
} from "@/lib/engineClient";
import { useEngineSession } from "@/lib/useEngineSession";

type ChatRole = "human" | "nepsis";
type DetachedRole = "human" | "assistant";
type DetachedModel = "gpt-4.1" | "o3" | "claude-sonnet" | "gemini";

type ChatMessage = {
  id: string;
  role: ChatRole;
  text: string;
  at: string;
};

type DetachedMessage = {
  id: string;
  role: DetachedRole;
  text: string;
  at: string;
  model: DetachedModel;
  source: string | null;
};

type RiskPosture = "red_first" | "balanced" | "blue_first";

type FrameDraft = {
  text: string;
  objective_type: string;
  domain: string;
  time_horizon: string;
  constraints_hard_text: string;
  constraints_soft_text: string;
  red_definition: string;
  blue_goals: string;
  risk_posture: RiskPosture;
};

type NextFrameDraft = {
  text: string;
  rationale_for_change: string;
  objective_type: string;
  domain: string;
  time_horizon: string;
  constraints_hard_text: string;
  constraints_soft_text: string;
};

type FrameTimelineEntry = {
  key: string;
  sessionId: string;
  frameVersion: number;
  text: string;
  note: string;
  at: string;
};

type PacketEvent = {
  id: string;
  label: string;
  raw: string;
  packetId: string;
  packetIndex: number;
  eventIndex: number;
  iteration: number | null;
  stage: string | null;
  frameVersion: number | null;
  at: string | null;
};

type CompactTimelineItem = {
  id: string;
  kind: "frame" | "event";
  label: string;
  at: string | null;
  order: number;
  frame?: FrameTimelineEntry;
  event?: PacketEvent;
};

type SignBuildResult = {
  sign: Record<string, unknown> | null;
  error: string | null;
};

const OBJECTIVE_OPTIONS = ["explain", "decide", "predict", "debug", "design", "sensemake"] as const;
const HORIZON_OPTIONS = ["immediate", "short", "medium", "long", "indefinite"] as const;
const DEVTOOLS_STORAGE_KEY = "nepsis_engine_devtools_enabled";

const RISK_POSTURES: Record<
  RiskPosture,
  {
    label: string;
    summary: string;
    c_fp: number;
    c_fn: number;
  }
> = {
  red_first: {
    label: "Red-first protection",
    summary: "Bias early action when catastrophic misses are plausible.",
    c_fp: 1,
    c_fn: 200,
  },
  balanced: {
    label: "Balanced",
    summary: "General-purpose cost posture with moderate caution.",
    c_fp: 1,
    c_fn: 9,
  },
  blue_first: {
    label: "Blue-first utility",
    summary: "Require stronger evidence before interruption or escalation.",
    c_fp: 8,
    c_fn: 10,
  },
};

const FAMILY_HINTS: Record<EngineFamily, string> = {
  safety: "General safety and governance loop.",
  clinical: "Clinical manifold; parses symptom/flag narratives into structured signs.",
  puzzle: "Word puzzle manifold; include `letters:` and `candidate:` in report notes.",
};

const DEFAULT_FRAME_DRAFT: FrameDraft = {
  text: "",
  objective_type: "sensemake",
  domain: "general",
  time_horizon: "short",
  constraints_hard_text: "",
  constraints_soft_text: "",
  red_definition: "",
  blue_goals: "",
  risk_posture: "balanced",
};

const DEFAULT_NEXT_FRAME_DRAFT: NextFrameDraft = {
  text: "",
  rationale_for_change: "",
  objective_type: "",
  domain: "",
  time_horizon: "",
  constraints_hard_text: "",
  constraints_soft_text: "",
};

const FRAME_STARTER_MESSAGE: ChatMessage = {
  id: "frame-start",
  role: "nepsis",
  text: "Start by describing the real question, risk asymmetry, and constraints that must hold.",
  at: new Date().toISOString(),
};

const REPORT_STARTER_MESSAGE: ChatMessage = {
  id: "report-start",
  role: "nepsis",
  text: "Add observations, tests, and contradictory evidence. Run CALL + REPORT when ready.",
  at: new Date().toISOString(),
};

const POSTERIOR_STARTER_MESSAGE: ChatMessage = {
  id: "posterior-start",
  role: "nepsis",
  text: "Review posterior mix, ruin flags, and threshold gate. Then draft what carries forward.",
  at: new Date().toISOString(),
};

const DETACHED_STARTER: DetachedMessage = {
  id: "detached-start",
  role: "assistant",
  text: "Model sandbox is detached from Nepsis state. Use it to compare model behavior before committing anything.",
  at: new Date().toISOString(),
  model: "gpt-4.1",
  source: null,
};

function createMessage(role: ChatRole, text: string): ChatMessage {
  return {
    id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    text,
    at: new Date().toISOString(),
  };
}

function createDetachedMessage(
  role: DetachedRole,
  text: string,
  model: DetachedModel,
  source: string | null,
): DetachedMessage {
  return {
    id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    text,
    at: new Date().toISOString(),
    model,
    source,
  };
}

function optionalText(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function parseLineList(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function lineListToText(values: string[]): string {
  return values.join("\n");
}

function shortSession(value: string): string {
  return value.length > 10 ? `${value.slice(0, 8)}...` : value;
}

function formatPct(value: number | undefined | null): string {
  if (value == null || !Number.isFinite(value)) {
    return "n/a";
  }
  return `${Math.round(value * 100)}%`;
}

function parseBoolTag(text: string, tag: string): boolean | undefined {
  const regex = new RegExp(`${tag}\\s*[:=]\\s*(true|false|yes|no|1|0)`, "i");
  const match = text.match(regex);
  if (!match) {
    return undefined;
  }
  const token = match[1].toLowerCase();
  return token === "true" || token === "yes" || token === "1";
}

function containsAny(haystack: string, terms: readonly string[]): boolean {
  return terms.some((term) => haystack.includes(term));
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  return value as Record<string, unknown>;
}

function readString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string");
}

function stageEventLabel(event: string): string {
  if (event === "ITERATE") {
    return "RESET";
  }
  return event;
}

function toTimestamp(value: string | null): number {
  if (!value) {
    return Number.NaN;
  }
  const ts = Date.parse(value);
  return Number.isFinite(ts) ? ts : Number.NaN;
}

function buildPacketEvents(packets: Record<string, unknown>[]): PacketEvent[] {
  const events: PacketEvent[] = [];
  packets.forEach((packet, packetIndex) => {
    const p = asRecord(packet);
    if (!p) {
      return;
    }
    const meta = asRecord(p.meta);
    const stageEvents = readStringArray(p.stage_events);
    const packetId = readString(meta?.packet_id) ?? `packet-${packetIndex}`;
    const iteration = readNumber(meta?.iteration);
    const stage = readString(p.stage);
    const at = readString(meta?.created_at);
    const frameVersionRecord = asRecord(p.frame_version);
    const frameVersion = readNumber(frameVersionRecord?.frame_version);

    stageEvents.forEach((event, eventIndex) => {
      events.push({
        id: `${packetId}:${eventIndex}`,
        label: stageEventLabel(event),
        raw: event,
        packetId,
        packetIndex,
        eventIndex,
        iteration,
        stage,
        frameVersion,
        at,
      });
    });
  });
  return events;
}

function deriveSafetySign(text: string): SignBuildResult {
  const lower = text.toLowerCase();
  const criticalFromTag = parseBoolTag(text, "critical_signal");
  const policyFromTag = parseBoolTag(text, "policy_violation");
  const critical_signal =
    criticalFromTag ??
    containsAny(lower, [
      "critical",
      "catastrophic",
      "ruin",
      "urgent",
      "imminent",
      "red flag",
      "unsafe",
      "severe",
    ]);
  const policy_violation = policyFromTag ?? containsAny(lower, ["policy", "violation", "non-compliant"]);
  return {
    sign: {
      critical_signal,
      policy_violation,
      notes: optionalText(text),
    },
    error: null,
  };
}

function deriveClinicalSign(text: string): SignBuildResult {
  const lower = text.toLowerCase();
  const value = (tag: string, terms: readonly string[], fallback = false): boolean => {
    const tagged = parseBoolTag(text, tag);
    if (tagged !== undefined) {
      return tagged;
    }
    if (containsAny(lower, terms)) {
      return true;
    }
    return fallback;
  };
  return {
    sign: {
      radicular_pain: value("radicular_pain", ["radicular", "shooting pain", "nerve root"]),
      spasm_present: value("spasm_present", ["spasm", "muscle spasm", "muscle tight"]),
      saddle_anesthesia: value("saddle_anesthesia", ["saddle anesthesia", "saddle numbness"]),
      bladder_dysfunction: value("bladder_dysfunction", ["bladder dysfunction", "urinary retention", "incontinence"]),
      bilateral_weakness: value("bilateral_weakness", ["bilateral weakness", "both legs weak"]),
      progression: value("progression", ["worsening", "progression", "deteriorating"]),
      fever: value("fever", ["fever", "febrile"]),
      notes: optionalText(text),
    },
    error: null,
  };
}

function derivePuzzleSign(text: string): SignBuildResult {
  const lettersMatch = text.match(/letters\s*[:=]\s*([A-Za-z]+)/i);
  const candidateMatch = text.match(/candidate\s*[:=]\s*([A-Za-z]+)/i);
  if (!lettersMatch || !candidateMatch) {
    return {
      sign: null,
      error: "Puzzle family requires `letters:` and `candidate:` in report notes.",
    };
  }
  return {
    sign: {
      letters: lettersMatch[1].toUpperCase(),
      candidate: candidateMatch[1].toUpperCase(),
    },
    error: null,
  };
}

function deriveSignFromNarrative(family: EngineFamily, text: string): SignBuildResult {
  if (!optionalText(text)) {
    return {
      sign: null,
      error: "Report notes are empty. Add at least one observation before CALL + REPORT.",
    };
  }
  if (family === "clinical") {
    return deriveClinicalSign(text);
  }
  if (family === "puzzle") {
    return derivePuzzleSign(text);
  }
  return deriveSafetySign(text);
}

function buildFramePayloadFromDraft(draft: FrameDraft): EngineReframePayload["frame"] {
  const payload: EngineReframePayload["frame"] = {};
  const text = optionalText(draft.text);
  const objectiveType = optionalText(draft.objective_type);
  const domain = optionalText(draft.domain);
  const horizon = optionalText(draft.time_horizon);
  const hard = parseLineList(draft.constraints_hard_text);
  const soft = parseLineList(draft.constraints_soft_text);
  const rationaleParts = [
    optionalText(draft.red_definition) ? `Red channel: ${draft.red_definition.trim()}` : null,
    optionalText(draft.blue_goals) ? `Blue channel: ${draft.blue_goals.trim()}` : null,
  ].filter((item): item is string => item !== null);

  if (text) {
    payload.text = text;
  }
  if (objectiveType) {
    payload.objective_type = objectiveType;
  }
  if (domain) {
    payload.domain = domain;
  }
  if (horizon) {
    payload.time_horizon = horizon;
  }
  if (hard.length > 0) {
    payload.constraints_hard = hard;
  }
  if (soft.length > 0) {
    payload.constraints_soft = soft;
  }
  if (rationaleParts.length > 0) {
    payload.rationale_for_change = rationaleParts.join(" | ");
  }
  return payload;
}

function buildNextFramePayload(draft: NextFrameDraft): EngineReframePayload["frame"] {
  const payload: EngineReframePayload["frame"] = {};
  const text = optionalText(draft.text);
  const rationale = optionalText(draft.rationale_for_change);
  const objective = optionalText(draft.objective_type);
  const domain = optionalText(draft.domain);
  const horizon = optionalText(draft.time_horizon);
  const hard = parseLineList(draft.constraints_hard_text);
  const soft = parseLineList(draft.constraints_soft_text);

  if (text) {
    payload.text = text;
  }
  if (rationale) {
    payload.rationale_for_change = rationale;
  }
  if (objective) {
    payload.objective_type = objective;
  }
  if (domain) {
    payload.domain = domain;
  }
  if (horizon) {
    payload.time_horizon = horizon;
  }
  if (hard.length > 0) {
    payload.constraints_hard = hard;
  }
  if (soft.length > 0) {
    payload.constraints_soft = soft;
  }
  return payload;
}

function hydrateFrameDraft(frame: EngineFrame | null): FrameDraft {
  if (!frame) {
    return DEFAULT_FRAME_DRAFT;
  }
  return {
    text: frame.text ?? "",
    objective_type: frame.objective_type ?? "sensemake",
    domain: frame.domain ?? "",
    time_horizon: frame.time_horizon ?? "short",
    constraints_hard_text: lineListToText(frame.constraints_hard),
    constraints_soft_text: lineListToText(frame.constraints_soft),
    red_definition: frame.rationale_for_change ?? "",
    blue_goals: "",
    risk_posture: "balanced",
  };
}

function hydrateNextFrameDraft(frame: EngineFrame | null): NextFrameDraft {
  if (!frame) {
    return DEFAULT_NEXT_FRAME_DRAFT;
  }
  return {
    text: frame.text ?? "",
    rationale_for_change: frame.rationale_for_change ?? "",
    objective_type: frame.objective_type ?? "",
    domain: frame.domain ?? "",
    time_horizon: frame.time_horizon ?? "",
    constraints_hard_text: lineListToText(frame.constraints_hard),
    constraints_soft_text: lineListToText(frame.constraints_soft),
  };
}

function frameCoachReply(draft: FrameDraft): string {
  const missing: string[] = [];
  if (!optionalText(draft.text)) {
    missing.push("core question");
  }
  if (!optionalText(draft.red_definition)) {
    missing.push("red channel trigger definition");
  }
  if (!optionalText(draft.blue_goals)) {
    missing.push("blue channel optimization goal");
  }
  if (missing.length > 0) {
    return `Captured. Before lock, clarify: ${missing.join(", ")}.`;
  }
  const hardCount = parseLineList(draft.constraints_hard_text).length;
  const softCount = parseLineList(draft.constraints_soft_text).length;
  return `Frame looks lock-ready. Constraints in play: hard=${hardCount}, soft=${softCount}.`;
}

function reportCoachReply(result: EngineStepResponse): string {
  const action = result.governance?.recommended_action ?? result.decision;
  const warning = result.governance?.warning_level ?? "green";
  return `Report updated. Warning=${warning}. Recommended next action: ${action}.`;
}

function warningBadgeClass(level: string | undefined): string {
  if (level === "red") {
    return "bg-red-500/20 text-red-200 border-red-500/40";
  }
  if (level === "yellow") {
    return "bg-amber-500/20 text-amber-100 border-amber-500/40";
  }
  return "bg-emerald-500/20 text-emerald-100 border-emerald-500/40";
}

export default function EnginePage() {
  const {
    loading,
    error,
    clearError,
    healthy,
    sessions,
    activeSession,
    packets,
    refreshHealth,
    refreshSessions,
    createSession,
    loadSession,
    step,
    reframe,
    refreshPackets,
  } = useEngineSession();

  const [localError, setLocalError] = useState<string | null>(null);
  const [developerToolsEnabled, setDeveloperToolsEnabled] = useState(false);
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);
  const [sandboxOpen, setSandboxOpen] = useState(false);

  const [family, setFamily] = useState<EngineFamily>("safety");
  const [sessionToOpen, setSessionToOpen] = useState<string>("");

  const [frameDraft, setFrameDraft] = useState<FrameDraft>(DEFAULT_FRAME_DRAFT);
  const [nextFrameDraft, setNextFrameDraft] = useState<NextFrameDraft>(DEFAULT_NEXT_FRAME_DRAFT);

  const [frameChat, setFrameChat] = useState<ChatMessage[]>([FRAME_STARTER_MESSAGE]);
  const [reportChat, setReportChat] = useState<ChatMessage[]>([REPORT_STARTER_MESSAGE]);
  const [posteriorChat, setPosteriorChat] = useState<ChatMessage[]>([POSTERIOR_STARTER_MESSAGE]);

  const [frameInput, setFrameInput] = useState("");
  const [reportInput, setReportInput] = useState("");
  const [posteriorInput, setPosteriorInput] = useState("");
  const [reportCorpus, setReportCorpus] = useState("");

  const [frameLocked, setFrameLocked] = useState(false);
  const [reportLocked, setReportLocked] = useState(false);
  const [frameCollapsed, setFrameCollapsed] = useState(false);

  const [reportResult, setReportResult] = useState<EngineStepResponse | null>(null);
  const [frameTimeline, setFrameTimeline] = useState<FrameTimelineEntry[]>([]);

  const [detachedModel, setDetachedModel] = useState<DetachedModel>("gpt-4.1");
  const [detachedCompare, setDetachedCompare] = useState(false);
  const [detachedSource, setDetachedSource] = useState("");
  const [detachedInput, setDetachedInput] = useState("");
  const [detachedChat, setDetachedChat] = useState<DetachedMessage[]>([DETACHED_STARTER]);

  const packetEvents = useMemo(() => buildPacketEvents(packets), [packets]);
  const compactTimeline = useMemo<CompactTimelineItem[]>(() => {
    const frameItems: CompactTimelineItem[] = frameTimeline.map((entry, idx) => ({
      id: `frame:${entry.key}`,
      kind: "frame",
      label: `Frame v${entry.frameVersion}`,
      at: entry.at,
      order: idx,
      frame: entry,
    }));
    const eventItems: CompactTimelineItem[] = packetEvents.map((event, idx) => ({
      id: `event:${event.id}`,
      kind: "event",
      label: event.label,
      at: event.at,
      order: idx + 10000,
      event,
    }));
    const all = [...frameItems, ...eventItems];
    all.sort((a, b) => {
      const ta = toTimestamp(a.at);
      const tb = toTimestamp(b.at);
      const hasTa = Number.isFinite(ta);
      const hasTb = Number.isFinite(tb);
      if (hasTa && hasTb && ta !== tb) {
        return ta - tb;
      }
      if (hasTa && !hasTb) {
        return -1;
      }
      if (!hasTa && hasTb) {
        return 1;
      }
      return a.order - b.order;
    });
    return all;
  }, [frameTimeline, packetEvents]);
  const [selectedTimelineId, setSelectedTimelineId] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      await Promise.all([refreshHealth(), refreshSessions()]);
    })();
  }, [refreshHealth, refreshSessions]);

  useEffect(() => {
    if (sessions.length > 0 && !sessionToOpen) {
      setSessionToOpen(sessions[0].session_id);
    }
  }, [sessions, sessionToOpen]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(DEVTOOLS_STORAGE_KEY);
      if (stored === "1") {
        setDeveloperToolsEnabled(true);
      }
    } catch {
      // Ignore localStorage failures and keep default (hidden devtools).
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(DEVTOOLS_STORAGE_KEY, developerToolsEnabled ? "1" : "0");
    } catch {
      // Ignore persistence failures.
    }
  }, [developerToolsEnabled]);

  useEffect(() => {
    if (!developerToolsEnabled) {
      setSystemStatusOpen(false);
    }
  }, [developerToolsEnabled]);

  useEffect(() => {
    if (compactTimeline.length === 0) {
      setSelectedTimelineId(null);
      return;
    }
    if (!selectedTimelineId || !compactTimeline.some((item) => item.id === selectedTimelineId)) {
      setSelectedTimelineId(compactTimeline[compactTimeline.length - 1].id);
    }
  }, [compactTimeline, selectedTimelineId]);

  const currentStageStep = !frameLocked ? 1 : !reportLocked ? 2 : 3;
  const userMode = !developerToolsEnabled;
  const showOperatorControls = developerToolsEnabled;

  function clearAllErrors() {
    clearError();
    setLocalError(null);
  }

  function appendFrameTimeline(sessionId: string, frame: EngineFrame | null | undefined, note: string) {
    if (!frame) {
      return;
    }
    const key = `${sessionId}:${frame.frame_version}`;
    setFrameTimeline((prev) => {
      if (prev.some((entry) => entry.key === key)) {
        return prev;
      }
      const next = [
        ...prev,
        {
          key,
          sessionId,
          frameVersion: frame.frame_version,
          text: frame.text,
          note,
          at: new Date().toISOString(),
        },
      ];
      return next.sort((a, b) => a.frameVersion - b.frameVersion);
    });
  }

  function resetDownstreamStages() {
    setReportLocked(false);
    setReportResult(null);
    setReportCorpus("");
    setReportInput("");
    setReportChat([REPORT_STARTER_MESSAGE]);
    setPosteriorChat([POSTERIOR_STARTER_MESSAGE]);
  }

  function pushFrameMessage(role: ChatRole, text: string) {
    setFrameChat((prev) => [...prev, createMessage(role, text)]);
  }

  function pushReportMessage(role: ChatRole, text: string) {
    setReportChat((prev) => [...prev, createMessage(role, text)]);
  }

  function pushPosteriorMessage(role: ChatRole, text: string) {
    setPosteriorChat((prev) => [...prev, createMessage(role, text)]);
  }

  async function handleOpenSession() {
    clearAllErrors();
    if (!sessionToOpen) {
      setLocalError("Select a session to open.");
      return;
    }
    const opened = await loadSession(sessionToOpen);
    if (!opened) {
      return;
    }
    setFamily(opened.family);
    setFrameDraft(hydrateFrameDraft(opened.frame));
    setNextFrameDraft(hydrateNextFrameDraft(opened.frame));
    setFrameLocked(opened.stage !== "draft");
    setReportLocked(false);
    setFrameCollapsed(opened.stage !== "draft");
    setReportResult(null);
    setFrameChat([
      FRAME_STARTER_MESSAGE,
      createMessage("nepsis", `Loaded session ${shortSession(opened.session_id)} at stage ${opened.stage}.`),
    ]);
    setReportChat([REPORT_STARTER_MESSAGE]);
    setPosteriorChat([POSTERIOR_STARTER_MESSAGE]);
    setReportCorpus("");
    setReportInput("");
    appendFrameTimeline(opened.session_id, opened.frame, "Session opened");
    await refreshPackets(opened.session_id);
  }

  async function handleNewWorkspace() {
    clearAllErrors();
    setFrameLocked(false);
    setFrameCollapsed(false);
    resetDownstreamStages();
    setFrameDraft(DEFAULT_FRAME_DRAFT);
    setNextFrameDraft(DEFAULT_NEXT_FRAME_DRAFT);
    setFrameChat([FRAME_STARTER_MESSAGE]);
    setFrameTimeline([]);
    await refreshSessions();
  }

  function handleSendFrameMessage() {
    clearAllErrors();
    const text = optionalText(frameInput);
    if (!text) {
      return;
    }
    pushFrameMessage("human", text);
    pushFrameMessage("nepsis", frameCoachReply(frameDraft));
    setFrameInput("");
  }

  function handleSendReportMessage() {
    clearAllErrors();
    const text = optionalText(reportInput);
    if (!text) {
      return;
    }
    pushReportMessage("human", text);
    pushReportMessage("nepsis", "Noted. Add more evidence or run CALL + REPORT.");
    setReportCorpus((prev) => (prev ? `${prev}\n${text}` : text));
    setReportInput("");
  }

  function handleSendPosteriorMessage() {
    clearAllErrors();
    const text = optionalText(posteriorInput);
    if (!text) {
      return;
    }
    pushPosteriorMessage("human", text);
    pushPosteriorMessage("nepsis", "Captured. Convert that into the next-frame fields, then commit.");
    setPosteriorInput("");
  }

  function handleSendDetachedMessage() {
    clearAllErrors();
    const text = optionalText(detachedInput);
    if (!text) {
      return;
    }
    const source = optionalText(detachedSource) ?? null;
    setDetachedChat((prev) => [
      ...prev,
      createDetachedMessage("human", text, detachedModel, source),
      createDetachedMessage(
        "assistant",
        detachedCompare
          ? `Comparison mode enabled. Sandbox currently set to ${detachedModel}.`
          : `Captured in sandbox (${detachedModel}). This does not alter Nepsis stage state.`,
        detachedModel,
        source,
      ),
    ]);
    setDetachedInput("");
  }

  async function handleLockFrame() {
    clearAllErrors();
    const text = optionalText(frameDraft.text);
    if (!text) {
      setLocalError("Frame text is required before lock.");
      return;
    }

    const costs = RISK_POSTURES[frameDraft.risk_posture];
    const framePayload = buildFramePayloadFromDraft(frameDraft);
    framePayload.text = text;

    let sessionId = activeSession?.session_id ?? "";
    let resultingFrame: EngineFrame | null = null;

    if (!activeSession || activeSession.family !== family) {
      const created = await createSession({
        family,
        emit_packet: true,
        governance: { c_fp: costs.c_fp, c_fn: costs.c_fn },
        frame: framePayload as EngineFrame & { text: string },
      });
      if (!created) {
        return;
      }
      sessionId = created.session_id;
      resultingFrame = created.frame;
      pushFrameMessage("nepsis", `Frame locked and new session created (${shortSession(created.session_id)}).`);
      await refreshPackets(created.session_id);
    } else {
      const updated = await reframe({ frame: framePayload });
      if (!updated) {
        return;
      }
      sessionId = activeSession.session_id;
      resultingFrame = updated;
      pushFrameMessage("nepsis", `Frame locked on session ${shortSession(activeSession.session_id)}.`);
    }

    setFrameLocked(true);
    setFrameCollapsed(true);
    resetDownstreamStages();
    if (resultingFrame) {
      appendFrameTimeline(sessionId, resultingFrame, "Frame locked");
      setNextFrameDraft(hydrateNextFrameDraft(resultingFrame));
    }
    await refreshSessions();
  }

  function handleUnlockFrame() {
    clearAllErrors();
    setFrameLocked(false);
    setFrameCollapsed(false);
    resetDownstreamStages();
    pushFrameMessage("nepsis", "Frame unlocked for edits. Downstream stages were reset.");
  }

  async function handleRunReport() {
    clearAllErrors();
    if (!frameLocked) {
      setLocalError("Lock Frame first.");
      return;
    }
    if (!activeSession) {
      setLocalError("No active session. Lock Frame to create or open a session.");
      return;
    }

    const reportText = [reportCorpus, optionalText(reportInput) ?? ""].filter(Boolean).join("\n");
    const signResult = deriveSignFromNarrative(activeSession.family, reportText);
    if (!signResult.sign) {
      setLocalError(signResult.error ?? "Could not build report sign payload.");
      return;
    }

    const result = await step({ sign: signResult.sign, commit: false });
    if (!result) {
      return;
    }

    setReportResult(result);
    if (optionalText(reportInput)) {
      pushReportMessage("human", reportInput.trim());
      setReportCorpus((prev) => (prev ? `${prev}\n${reportInput.trim()}` : reportInput.trim()));
      setReportInput("");
    }
    pushReportMessage("nepsis", reportCoachReply(result));
    pushPosteriorMessage("nepsis", "Posterior updated. Review trust indicators and choose carry-forward edits.");
    await refreshPackets(result.session.session_id);
    await refreshSessions();
  }

  function handleLockReport() {
    clearAllErrors();
    if (!reportResult) {
      setLocalError("Run CALL + REPORT before locking this stage.");
      return;
    }
    setReportLocked(true);
    pushReportMessage("nepsis", "Report locked. Posterior stage is now active.");
    if (reportResult.governance?.recommended_action) {
      setNextFrameDraft((prev) => ({
        ...prev,
        rationale_for_change:
          prev.rationale_for_change ||
          `Governance recommendation: ${reportResult.governance?.recommended_action}`,
      }));
    }
  }

  function handleUnlockReport() {
    clearAllErrors();
    setReportLocked(false);
    pushReportMessage("nepsis", "Report unlocked for more testing.");
  }

  async function handleCommitIteration() {
    clearAllErrors();
    if (!frameLocked || !reportLocked) {
      setLocalError("Lock Frame and Lock Report before committing iteration.");
      return;
    }
    if (!activeSession) {
      setLocalError("No active session.");
      return;
    }
    const payload = buildNextFramePayload(nextFrameDraft);
    if (!payload.text) {
      setLocalError("Next-frame text is required to commit.");
      return;
    }

    const updated = await reframe({ frame: payload });
    if (!updated) {
      return;
    }

    appendFrameTimeline(activeSession.session_id, updated, "Committed to next priors");
    setFrameDraft((prev) => ({
      ...prev,
      text: updated.text,
      objective_type: updated.objective_type,
      domain: updated.domain ?? "",
      time_horizon: updated.time_horizon ?? "",
      constraints_hard_text: lineListToText(updated.constraints_hard),
      constraints_soft_text: lineListToText(updated.constraints_soft),
      red_definition: updated.rationale_for_change ?? prev.red_definition,
    }));
    setNextFrameDraft(hydrateNextFrameDraft(updated));
    setFrameLocked(false);
    setFrameCollapsed(false);
    resetDownstreamStages();
    pushPosteriorMessage("nepsis", "Iteration committed. Priors stage reopened for the next cycle.");
    pushFrameMessage("nepsis", `Frame v${updated.frame_version} is now the working prior.`);
    await refreshSessions();
  }

  const governance = reportResult?.governance;
  const posteriorRows = useMemo(
    () =>
      Object.entries(reportResult?.posterior ?? {}).sort((a, b) => {
        return b[1] - a[1];
      }),
    [reportResult?.posterior],
  );
  const mergedError = localError ?? error;
  const activeStage = activeSession?.stage ?? "none";
  const whyNotConverging = governance?.why_not_converging ?? [];
  const topInterpretation = posteriorRows[0] ?? null;
  const secondInterpretation = posteriorRows[1] ?? null;
  const topMargin =
    topInterpretation && secondInterpretation ? Math.max(0, topInterpretation[1] - secondInterpretation[1]) : null;
  const gateCrossed =
    governance?.p_bad != null && governance?.theta != null ? governance.p_bad >= governance.theta : null;
  const showReportPanel = showOperatorControls || currentStageStep >= 2;
  const showPosteriorPanel = showOperatorControls || currentStageStep >= 3;
  const showTimeline = showOperatorControls || currentStageStep >= 3;

  const selectedTimeline = compactTimeline.find((item) => item.id === selectedTimelineId) ?? null;
  const selectedPacket = selectedTimeline?.event
    ? asRecord(packets[selectedTimeline.event.packetIndex])
    : null;
  const selectedPacketResult = asRecord(selectedPacket?.result);
  const selectedPacketState = asRecord(selectedPacket?.state);
  const selectedPacketCarry = asRecord(selectedPacket?.carry_forward);

  return (
    <div className="mx-auto flex w-full max-w-[1850px] flex-col gap-4 px-4 py-6">
      <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">Nepsis Co-Reasoning Workspace</h1>
            <p className="mt-1 max-w-3xl text-sm text-nepsis-muted">
              Guided progression: <span className="font-medium text-nepsis-text">Frame</span> →{" "}
              <span className="font-medium text-nepsis-text">Call &amp; Report</span> →{" "}
              <span className="font-medium text-nepsis-text">Posterior / New Priors</span>.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setDeveloperToolsEnabled((prev) => !prev)}
              className="rounded-full border border-nepsis-border px-3 py-1.5 font-mono text-xs hover:border-nepsis-accent"
            >
              {developerToolsEnabled ? "Close </>" : "</> DevTools"}
            </button>

            <button
              onClick={() => setSandboxOpen(true)}
              className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
            >
              Open Model Sandbox
            </button>
            {developerToolsEnabled && (
              <button
                onClick={() => setSystemStatusOpen((prev) => !prev)}
                className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
              >
                System Status
              </button>
            )}
          </div>
        </div>

        {developerToolsEnabled && systemStatusOpen && (
          <div className="mt-3 grid gap-2 rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs text-nepsis-muted md:grid-cols-3">
            <div>
              backend:{" "}
              <span className={healthy ? "text-green-400" : healthy === false ? "text-red-400" : "text-yellow-300"}>
                {healthy === null ? "unknown" : healthy ? "healthy" : "unreachable"}
              </span>
            </div>
            <div>active session: {activeSession ? shortSession(activeSession.session_id) : "none"}</div>
            <div>stage: {activeStage}</div>
            <div>packets: {packets.length}</div>
            <div>frame locked: {frameLocked ? "yes" : "no"}</div>
            <div>report locked: {reportLocked ? "yes" : "no"}</div>
          </div>
        )}

        {showOperatorControls && (
          <div className="mt-3 grid gap-3 lg:grid-cols-[1.1fr_1fr_auto]">
            <label className="block text-xs text-nepsis-muted">
              Open Existing Session
              <select
                value={sessionToOpen}
                onChange={(event) => setSessionToOpen(event.target.value)}
                className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-sm text-nepsis-text"
              >
                <option value="">Select...</option>
                {sessions.map((session) => (
                  <option key={session.session_id} value={session.session_id}>
                    {shortSession(session.session_id)} · {session.family} · stage={session.stage}
                  </option>
                ))}
              </select>
            </label>
            <div className="rounded-lg border border-nepsis-border bg-black/20 px-3 py-2 text-xs text-nepsis-muted">
              <div>active: {activeSession ? shortSession(activeSession.session_id) : "none"}</div>
              <div>stage: {activeStage}</div>
              <div>packets: {packets.length}</div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => void handleOpenSession()}
                className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
              >
                Open Session
              </button>
              <button
                onClick={() => void handleNewWorkspace()}
                className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
              >
                New Workspace
              </button>
              <button
                onClick={() => void refreshSessions()}
                className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
              >
                Refresh
              </button>
            </div>
          </div>
        )}

        {userMode && (
          <div className="mt-3 flex flex-wrap gap-2 text-xs">
            <span
              className={`rounded-full border px-3 py-1 ${
                currentStageStep === 1
                  ? "border-nepsis-accent bg-nepsis-accent/10 text-nepsis-text"
                  : "border-nepsis-border text-nepsis-muted"
              }`}
            >
              1. Frame
            </span>
            <span
              className={`rounded-full border px-3 py-1 ${
                currentStageStep === 2
                  ? "border-nepsis-accent bg-nepsis-accent/10 text-nepsis-text"
                  : currentStageStep > 2
                    ? "border-green-500/40 bg-green-500/10 text-green-200"
                    : "border-nepsis-border text-nepsis-muted"
              }`}
            >
              2. Call &amp; Report
            </span>
            <span
              className={`rounded-full border px-3 py-1 ${
                currentStageStep === 3
                  ? "border-nepsis-accent bg-nepsis-accent/10 text-nepsis-text"
                  : "border-nepsis-border text-nepsis-muted"
              }`}
            >
              3. Posterior / New Priors
            </span>
          </div>
        )}
      </section>

      {mergedError && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {mergedError}
        </div>
      )}

      <div className={`grid gap-4 ${userMode ? "grid-cols-1" : "2xl:grid-cols-3"}`}>
        <section className="flex min-h-[760px] flex-col rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">1) Priors / Frame</h2>
              <p className="text-xs text-nepsis-muted">Objective, horizon, domain, constraints, and risk posture.</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setFrameCollapsed((prev) => !prev)}
                className="rounded-full border border-nepsis-border px-2 py-0.5 text-[11px] hover:border-nepsis-accent"
              >
                {frameCollapsed ? "Expand" : "Collapse"}
              </button>
              <span
                className={`rounded-full border px-2 py-0.5 text-[11px] ${
                  frameLocked
                    ? "border-green-500/40 bg-green-500/15 text-green-200"
                    : "border-nepsis-border bg-black/20 text-nepsis-muted"
                }`}
              >
                {frameLocked ? "Locked" : "Open"}
              </span>
            </div>
          </div>

          {userMode && frameLocked && frameCollapsed ? (
            <div className="flex-1 space-y-3">
              <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                <div className="text-nepsis-muted">Frame summary</div>
                <div className="mt-1 text-nepsis-text">{frameDraft.text || "(no frame text yet)"}</div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-nepsis-muted">
                  <div>objective: {frameDraft.objective_type || "n/a"}</div>
                  <div>domain: {frameDraft.domain || "n/a"}</div>
                  <div>hard: {parseLineList(frameDraft.constraints_hard_text).length}</div>
                  <div>soft: {parseLineList(frameDraft.constraints_soft_text).length}</div>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex-1 space-y-3">
              <div className="h-44 overflow-auto rounded-lg border border-nepsis-border bg-black/20 p-2 text-xs">
                {frameChat.map((message) => (
                  <div key={message.id} className="mb-2">
                    <span className={message.role === "human" ? "text-nepsis-accent" : "text-nepsis-muted"}>
                      {message.role === "human" ? "You" : "Nepsis"}
                    </span>
                    <span className="text-nepsis-muted"> · {new Date(message.at).toLocaleTimeString()}</span>
                    <div className="mt-0.5 whitespace-pre-wrap text-nepsis-text">{message.text}</div>
                  </div>
                ))}
              </div>

              <div className="flex gap-2">
                <textarea
                  value={frameInput}
                  onChange={(event) => setFrameInput(event.target.value)}
                  rows={2}
                  placeholder="Discuss frame assumptions..."
                  className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                />
                <button
                  onClick={handleSendFrameMessage}
                  className="h-fit rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
                >
                  Send
                </button>
              </div>

              <label className="block text-xs text-nepsis-muted">
                Family
                <select
                  value={family}
                  onChange={(event) => setFamily(event.target.value as EngineFamily)}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-sm"
                >
                  <option value="safety">safety</option>
                  <option value="clinical">clinical</option>
                  <option value="puzzle">puzzle</option>
                </select>
                <span className="mt-1 block text-[11px]">{FAMILY_HINTS[family]}</span>
              </label>

              <label className="block text-xs text-nepsis-muted">
                Frame question
                <textarea
                  value={frameDraft.text}
                  onChange={(event) => setFrameDraft((prev) => ({ ...prev, text: event.target.value }))}
                  rows={3}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-sm"
                />
              </label>

              <div className="grid grid-cols-2 gap-2">
                <label className="block text-xs text-nepsis-muted">
                  Objective
                  <select
                    value={frameDraft.objective_type}
                    onChange={(event) =>
                      setFrameDraft((prev) => ({ ...prev, objective_type: event.target.value }))
                    }
                    className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-sm"
                  >
                    {OBJECTIVE_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs text-nepsis-muted">
                  Time horizon
                  <select
                    value={frameDraft.time_horizon}
                    onChange={(event) =>
                      setFrameDraft((prev) => ({ ...prev, time_horizon: event.target.value }))
                    }
                    className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-sm"
                  >
                    {HORIZON_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <label className="block text-xs text-nepsis-muted">
                Domain
                <input
                  value={frameDraft.domain}
                  onChange={(event) => setFrameDraft((prev) => ({ ...prev, domain: event.target.value }))}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-sm"
                />
              </label>

              <div className="grid grid-cols-2 gap-2">
                <label className="block text-xs text-nepsis-muted">
                  Hard constraints (1/line)
                  <textarea
                    value={frameDraft.constraints_hard_text}
                    onChange={(event) =>
                      setFrameDraft((prev) => ({
                        ...prev,
                        constraints_hard_text: event.target.value,
                      }))
                    }
                    rows={4}
                    className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                  />
                </label>
                <label className="block text-xs text-nepsis-muted">
                  Soft constraints (1/line)
                  <textarea
                    value={frameDraft.constraints_soft_text}
                    onChange={(event) =>
                      setFrameDraft((prev) => ({
                        ...prev,
                        constraints_soft_text: event.target.value,
                      }))
                    }
                    rows={4}
                    className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                  />
                </label>
              </div>

              <label className="block text-xs text-nepsis-muted">
                Red channel definition
                <textarea
                  value={frameDraft.red_definition}
                  onChange={(event) => setFrameDraft((prev) => ({ ...prev, red_definition: event.target.value }))}
                  rows={2}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                />
              </label>
              <label className="block text-xs text-nepsis-muted">
                Blue channel goals
                <textarea
                  value={frameDraft.blue_goals}
                  onChange={(event) => setFrameDraft((prev) => ({ ...prev, blue_goals: event.target.value }))}
                  rows={2}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                />
              </label>

              <label className="block text-xs text-nepsis-muted">
                Risk posture
                <select
                  value={frameDraft.risk_posture}
                  onChange={(event) =>
                    setFrameDraft((prev) => ({
                      ...prev,
                      risk_posture: event.target.value as RiskPosture,
                    }))
                  }
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-sm"
                >
                  <option value="red_first">{RISK_POSTURES.red_first.label}</option>
                  <option value="balanced">{RISK_POSTURES.balanced.label}</option>
                  <option value="blue_first">{RISK_POSTURES.blue_first.label}</option>
                </select>
                <span className="mt-1 block text-[11px]">{RISK_POSTURES[frameDraft.risk_posture].summary}</span>
              </label>
            </div>
          )}

          <div className="mt-3 flex gap-2">
            {!frameLocked ? (
              <button
                onClick={() => void handleLockFrame()}
                disabled={loading}
                className="rounded-full bg-nepsis-accent px-4 py-2 text-xs font-semibold text-black disabled:opacity-60"
              >
                Lock Frame →
              </button>
            ) : (
              <button
                onClick={handleUnlockFrame}
                className="rounded-full border border-nepsis-border px-4 py-2 text-xs hover:border-nepsis-accent"
              >
                Unlock Frame
              </button>
            )}
          </div>
        </section>

        {showReportPanel && (
          <section
            className={`flex min-h-[760px] flex-col rounded-2xl border border-nepsis-border bg-nepsis-panel p-4 ${
              !frameLocked ? "pointer-events-none opacity-50" : ""
            }`}
          >
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">2) Call &amp; Report</h2>
                <p className="text-xs text-nepsis-muted">Observations input, payload preview, and report run.</p>
              </div>
              <span
                className={`rounded-full border px-2 py-0.5 text-[11px] ${
                  reportLocked
                    ? "border-green-500/40 bg-green-500/15 text-green-200"
                    : "border-nepsis-border bg-black/20 text-nepsis-muted"
                }`}
              >
                {reportLocked ? "Locked" : "Open"}
              </span>
            </div>

            {userMode && reportLocked && currentStageStep > 2 ? (
              <div className="flex-1 space-y-3">
                <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                  <div className="text-nepsis-muted">Report summary</div>
                  <div className="mt-1 text-nepsis-text">
                    decision: {reportResult?.decision ?? "n/a"} · action: {reportResult?.governance?.recommended_action ?? "n/a"}
                  </div>
                  <div className="mt-1 text-nepsis-muted">
                    warning: {reportResult?.governance?.warning_level ?? "n/a"} · violations: {reportResult?.violation_count ?? 0}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex-1 space-y-3">
                <div className="h-48 overflow-auto rounded-lg border border-nepsis-border bg-black/20 p-2 text-xs">
                  {reportChat.map((message) => (
                    <div key={message.id} className="mb-2">
                      <span className={message.role === "human" ? "text-nepsis-accent" : "text-nepsis-muted"}>
                        {message.role === "human" ? "You" : "Nepsis"}
                      </span>
                      <span className="text-nepsis-muted"> · {new Date(message.at).toLocaleTimeString()}</span>
                      <div className="mt-0.5 whitespace-pre-wrap text-nepsis-text">{message.text}</div>
                    </div>
                  ))}
                </div>

                <div className="flex gap-2">
                  <textarea
                    value={reportInput}
                    onChange={(event) => setReportInput(event.target.value)}
                    rows={3}
                    placeholder="Observations, tests, contradictions..."
                    className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                  />
                  <button
                    onClick={handleSendReportMessage}
                    className="h-fit rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
                  >
                    Send
                  </button>
                </div>

                <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                  <div className="mb-1 text-nepsis-muted">CALL payload preview</div>
                  <pre className="max-h-40 overflow-auto text-[11px] text-nepsis-muted">
                    {JSON.stringify(
                      deriveSignFromNarrative(activeSession?.family ?? family, reportCorpus || reportInput).sign,
                      null,
                      2,
                    )}
                  </pre>
                </div>

                {reportResult && (
                  <div className="space-y-2 rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full border border-nepsis-border px-2 py-0.5">
                        decision: {reportResult.decision}
                      </span>
                      <span className="rounded-full border border-nepsis-border px-2 py-0.5">
                        stage: {reportResult.stage}
                      </span>
                      <span
                        className={`rounded-full border px-2 py-0.5 ${
                          warningBadgeClass(reportResult.governance?.warning_level)
                        }`}
                      >
                        warning: {reportResult.governance?.warning_level ?? "n/a"}
                      </span>
                    </div>
                    <div className="text-nepsis-muted">
                      cause: {reportResult.cause ?? "none"} · violations: {reportResult.violation_count} · ruin:{" "}
                      {reportResult.is_ruin ? "yes" : "no"}
                    </div>
                    <div className="text-nepsis-muted">
                      recommended action: {reportResult.governance?.recommended_action ?? reportResult.decision}
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              <button
                onClick={() => void handleRunReport()}
                disabled={loading}
                className="rounded-full bg-nepsis-accent px-4 py-2 text-xs font-semibold text-black disabled:opacity-60"
              >
                Run CALL + REPORT
              </button>
              {!reportLocked ? (
                <button
                  onClick={handleLockReport}
                  className="rounded-full border border-nepsis-border px-4 py-2 text-xs hover:border-nepsis-accent"
                >
                  Lock Report →
                </button>
              ) : (
                <button
                  onClick={handleUnlockReport}
                  className="rounded-full border border-nepsis-border px-4 py-2 text-xs hover:border-nepsis-accent"
                >
                  Unlock Report
                </button>
              )}
            </div>
          </section>
        )}

        {showPosteriorPanel && (
          <section
            className={`flex min-h-[760px] flex-col rounded-2xl border border-nepsis-border bg-nepsis-panel p-4 ${
              !reportLocked ? "pointer-events-none opacity-50" : ""
            }`}
          >
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">3) Posterior / Thresholds / New Priors</h2>
                <p className="text-xs text-nepsis-muted">Decision hierarchy first, then metrics and carry-forward.</p>
              </div>
              <span className="rounded-full border border-nepsis-border bg-black/20 px-2 py-0.5 text-[11px] text-nepsis-muted">
                {reportLocked ? "Ready to commit" : "Locked"}
              </span>
            </div>

            <div className="flex-1 space-y-3">
              <div className="h-24 overflow-auto rounded-lg border border-nepsis-border bg-black/20 p-2 text-xs">
                {posteriorChat.map((message) => (
                  <div key={message.id} className="mb-2">
                    <span className={message.role === "human" ? "text-nepsis-accent" : "text-nepsis-muted"}>
                      {message.role === "human" ? "You" : "Nepsis"}
                    </span>
                    <span className="text-nepsis-muted"> · {new Date(message.at).toLocaleTimeString()}</span>
                    <div className="mt-0.5 whitespace-pre-wrap text-nepsis-text">{message.text}</div>
                  </div>
                ))}
              </div>

              <div className="flex gap-2">
                <textarea
                  value={posteriorInput}
                  onChange={(event) => setPosteriorInput(event.target.value)}
                  rows={2}
                  placeholder="Carry-forward discussion..."
                  className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                />
                <button
                  onClick={handleSendPosteriorMessage}
                  className="h-fit rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
                >
                  Send
                </button>
              </div>

              <div className="grid gap-2 md:grid-cols-3">
                <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                  <div className="text-nepsis-muted">Decision</div>
                  <div className="mt-1 font-mono text-nepsis-text">{topInterpretation?.[0] ?? "n/a"}</div>
                  <div className="mt-1 text-nepsis-muted">weight: {formatPct(topInterpretation?.[1])}</div>
                  <div className="text-nepsis-muted">margin: {formatPct(topMargin)}</div>
                </div>
                <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                  <div className="text-nepsis-muted">Ruin status</div>
                  <div className="mt-1 text-nepsis-text">
                    {reportResult?.ruin_hits?.length ? reportResult.ruin_hits.join(", ") : "none"}
                  </div>
                  <div className="mt-1 text-nepsis-muted">ruin_mass: {formatPct(governance?.ruin_mass)}</div>
                </div>
                <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                  <div className="text-nepsis-muted">Gate result</div>
                  <div className="mt-1 text-nepsis-text">
                    p_bad {formatPct(governance?.p_bad)} vs theta {formatPct(governance?.theta)}
                  </div>
                  <div className="mt-1 text-nepsis-muted">
                    gate: {gateCrossed == null ? "n/a" : gateCrossed ? "crossed" : "not crossed"}
                  </div>
                </div>
              </div>

              <div className="rounded-lg border border-nepsis-border bg-black/20 p-3">
                <div className="mb-2 text-xs text-nepsis-muted">Posterior distribution</div>
                <div className="space-y-2">
                  {posteriorRows.length === 0 && <div className="text-xs text-nepsis-muted">No posterior yet.</div>}
                  {posteriorRows.map(([name, value]) => (
                    <div key={name} className="space-y-1 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-nepsis-text">{name}</span>
                        <span className="text-nepsis-muted">{formatPct(value)}</span>
                      </div>
                      <div className="h-2 rounded-full bg-nepsis-border">
                        <div
                          className="h-2 rounded-full bg-gradient-to-r from-nepsis-accent to-nepsis-accentSoft"
                          style={{ width: `${Math.max(2, Math.round(value * 100))}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {showOperatorControls && whyNotConverging.length > 0 && (
                <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                  <div className="mb-2 text-nepsis-muted">Why not converging?</div>
                  <div className="space-y-2">
                    {whyNotConverging.map((reason) => (
                      <div key={reason.code} className="rounded border border-nepsis-border px-2 py-1.5">
                        <div className="font-medium text-nepsis-text">{reason.title}</div>
                        <div className="text-nepsis-muted">{reason.message}</div>
                        <div className="mt-0.5 text-[11px] text-nepsis-accent">
                          Next discriminator: {reason.next_discriminator}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <label className="block text-xs text-nepsis-muted">
                Next frame text
                <textarea
                  value={nextFrameDraft.text}
                  onChange={(event) => setNextFrameDraft((prev) => ({ ...prev, text: event.target.value }))}
                  rows={3}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                />
              </label>

              <label className="block text-xs text-nepsis-muted">
                Rationale for change
                <textarea
                  value={nextFrameDraft.rationale_for_change}
                  onChange={(event) =>
                    setNextFrameDraft((prev) => ({ ...prev, rationale_for_change: event.target.value }))
                  }
                  rows={2}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                />
              </label>

              <div className="grid grid-cols-2 gap-2">
                <label className="block text-xs text-nepsis-muted">
                  Objective (optional)
                  <select
                    value={nextFrameDraft.objective_type}
                    onChange={(event) =>
                      setNextFrameDraft((prev) => ({ ...prev, objective_type: event.target.value }))
                    }
                    className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                  >
                    <option value="">no change</option>
                    {OBJECTIVE_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block text-xs text-nepsis-muted">
                  Time horizon (optional)
                  <select
                    value={nextFrameDraft.time_horizon}
                    onChange={(event) =>
                      setNextFrameDraft((prev) => ({ ...prev, time_horizon: event.target.value }))
                    }
                    className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                  >
                    <option value="">no change</option>
                    {HORIZON_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                </label>
              </div>

              <label className="block text-xs text-nepsis-muted">
                Domain (optional)
                <input
                  value={nextFrameDraft.domain}
                  onChange={(event) => setNextFrameDraft((prev) => ({ ...prev, domain: event.target.value }))}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                />
              </label>
            </div>

            <div className="mt-3 flex gap-2">
              <button
                onClick={() => void handleCommitIteration()}
                disabled={loading}
                className="rounded-full bg-nepsis-accent px-4 py-2 text-xs font-semibold text-black disabled:opacity-60"
              >
                Commit Iteration
              </button>
            </div>
          </section>
        )}
      </div>

      {showTimeline && (
        <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Timeline</h3>
            <div className="text-xs text-nepsis-muted">{compactTimeline.length} items</div>
          </div>

          <div className="overflow-x-auto rounded-lg border border-nepsis-border bg-black/20 p-2">
            <div className="flex min-w-max items-center gap-2 text-xs">
              {compactTimeline.length === 0 && <div className="text-nepsis-muted">No timeline items yet.</div>}
              {compactTimeline.map((item, index) => (
                <div key={item.id} className="flex items-center gap-2">
                  <button
                    onClick={() => setSelectedTimelineId(item.id)}
                    className={`rounded-full border px-3 py-1 ${
                      selectedTimelineId === item.id
                        ? "border-nepsis-accent bg-nepsis-accent/10 text-nepsis-text"
                        : "border-nepsis-border text-nepsis-muted"
                    }`}
                  >
                    {item.label}
                  </button>
                  {index < compactTimeline.length - 1 && <span className="text-nepsis-muted">—</span>}
                </div>
              ))}
            </div>
          </div>

          {selectedTimeline && (
            <div className="mt-3 rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
              {selectedTimeline.kind === "frame" && selectedTimeline.frame && (
                <div className="space-y-2">
                  <div className="text-nepsis-muted">Frame timeline detail</div>
                  <div className="font-mono text-nepsis-accent">v{selectedTimeline.frame.frameVersion}</div>
                  <div className="text-nepsis-text">{selectedTimeline.frame.text}</div>
                  <div className="text-nepsis-muted">{selectedTimeline.frame.note}</div>
                </div>
              )}

              {selectedTimeline.kind === "event" && selectedTimeline.event && (
                <div className="space-y-2">
                  <div className="text-nepsis-muted">Packet event detail</div>
                  <div className="grid gap-2 md:grid-cols-3">
                    <div>
                      <div className="text-nepsis-muted">Event</div>
                      <div className="text-nepsis-text">
                        {selectedTimeline.event.label} ({selectedTimeline.event.raw})
                      </div>
                    </div>
                    <div>
                      <div className="text-nepsis-muted">Iteration</div>
                      <div className="text-nepsis-text">{selectedTimeline.event.iteration ?? "n/a"}</div>
                    </div>
                    <div>
                      <div className="text-nepsis-muted">Stage</div>
                      <div className="text-nepsis-text">{selectedTimeline.event.stage ?? "n/a"}</div>
                    </div>
                  </div>
                  {showOperatorControls ? (
                    <>
                      <div className="grid gap-2 md:grid-cols-3">
                        <div className="rounded border border-nepsis-border px-2 py-1.5">
                          <div className="text-nepsis-muted">Decision</div>
                          <div className="text-nepsis-text">{readString(selectedPacketResult?.decision) ?? "n/a"}</div>
                        </div>
                        <div className="rounded border border-nepsis-border px-2 py-1.5">
                          <div className="text-nepsis-muted">Cause</div>
                          <div className="text-nepsis-text">{readString(selectedPacketResult?.cause) ?? "n/a"}</div>
                        </div>
                        <div className="rounded border border-nepsis-border px-2 py-1.5">
                          <div className="text-nepsis-muted">State</div>
                          <div className="text-nepsis-text">{readString(selectedPacketState?.description) ?? "n/a"}</div>
                        </div>
                      </div>
                      {selectedPacketCarry && (
                        <pre className="max-h-24 overflow-auto rounded border border-nepsis-border bg-black/30 p-2 text-[11px] text-nepsis-muted">
                          {JSON.stringify(selectedPacketCarry, null, 2)}
                        </pre>
                      )}
                    </>
                  ) : (
                    <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                      Enable <span className="font-mono text-nepsis-text">DevTools</span> to inspect raw packet details.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {sandboxOpen && (
        <div className="fixed inset-0 z-50">
          <button
            aria-label="Close sandbox overlay"
            onClick={() => setSandboxOpen(false)}
            className="absolute inset-0 bg-black/60"
          />
          <aside className="absolute right-0 top-0 h-full w-full max-w-md border-l border-nepsis-border bg-nepsis-panel p-4 shadow-2xl shadow-black/60">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">Model Sandbox</h2>
                <p className="text-xs text-nepsis-muted">Detached model interaction workspace.</p>
              </div>
              <button
                onClick={() => setSandboxOpen(false)}
                className="rounded-full border border-nepsis-border px-2 py-0.5 text-xs hover:border-nepsis-accent"
              >
                Close
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <label className="block text-nepsis-muted">
                Model
                <select
                  value={detachedModel}
                  onChange={(event) => setDetachedModel(event.target.value as DetachedModel)}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-nepsis-text"
                >
                  <option value="gpt-4.1">gpt-4.1</option>
                  <option value="o3">o3</option>
                  <option value="claude-sonnet">claude-sonnet</option>
                  <option value="gemini">gemini</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-nepsis-muted">
                <input
                  type="checkbox"
                  checked={detachedCompare}
                  onChange={(event) => setDetachedCompare(event.target.checked)}
                />
                Multi-model comparison view
              </label>
              <label className="block text-nepsis-muted">
                Optional input source
                <input
                  value={detachedSource}
                  onChange={(event) => setDetachedSource(event.target.value)}
                  placeholder="URL, doc path, or note"
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-nepsis-text"
                />
              </label>
            </div>

            <div className="mt-3 h-[52vh] overflow-auto rounded-lg border border-nepsis-border bg-black/20 p-2 text-xs">
              {detachedChat.map((message) => (
                <div key={message.id} className="mb-2">
                  <div className="flex items-center justify-between gap-2 text-[11px]">
                    <span className={message.role === "human" ? "text-nepsis-accent" : "text-nepsis-muted"}>
                      {message.role === "human" ? "You" : "Assistant"}
                    </span>
                    <span className="text-nepsis-muted">{message.model}</span>
                  </div>
                  <div className="text-[11px] text-nepsis-muted">
                    {new Date(message.at).toLocaleTimeString()}
                    {message.source ? ` · src: ${message.source}` : ""}
                  </div>
                  <div className="mt-0.5 whitespace-pre-wrap text-nepsis-text">{message.text}</div>
                </div>
              ))}
            </div>

            <div className="mt-3 flex gap-2">
              <textarea
                value={detachedInput}
                onChange={(event) => setDetachedInput(event.target.value)}
                rows={3}
                placeholder="Sandbox prompt..."
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
              />
              <button
                onClick={handleSendDetachedMessage}
                className="h-fit rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
              >
                Send
              </button>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
