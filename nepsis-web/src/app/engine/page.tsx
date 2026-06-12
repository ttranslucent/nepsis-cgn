"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  type EngineFamily,
  type EngineFrame,
  type EngineOperatorResult,
  type EngineReframePayload,
  type EngineStageAuditResponse,
  type EngineStepResponse,
  type PacketProvenanceRecord,
  isPhaseRejection,
} from "@/lib/engineClient";
import {
  type GateResult,
  type GateStatus,
  type InterpretationContradictionsStatus,
  type StageCoach,
  type ThresholdDecision,
  buildFrameCoach,
  buildInterpretationCoach,
  buildThresholdCoach,
  evaluateFrameGate,
  evaluateInterpretationGate,
  evaluateThresholdGate,
} from "@/lib/nepsisGates";
import {
  consumeConnectedNotice,
  getStoredOpenAiKey,
  hasStoredOpenAiKey,
} from "@/lib/clientStorage";
import { OperatorAccessNotice } from "@/app/components/OperatorAccessNotice";
import { publicSiteMode } from "@/lib/publicMode";
import { useEngineSession } from "@/lib/useEngineSession";
import {
  requestOperatorModel,
  type OperatorAssistTarget,
} from "@/lib/operatorModelClient";
import {
  FRAME_ASSIST_TARGETS,
  assistTargetTextFromFramePayload,
  buildAssistDispositions,
  canonicalFieldText,
  readRationaleSegment,
  targetLabel,
  type AssistReview,
} from "@/app/engine/operatorAssist";
import { withCsrfHeader } from "@/lib/csrfClient";

type ChatRole = "human" | "nepsis";
type DetachedRole = "human" | "assistant";
type DetachedModel = "gpt-4.1" | "gpt-4.1-mini" | "o3" | "o4-mini";

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
  key_uncertainty: string;
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
  lineageVersion: number;
  branchId: string;
  parentFrameId: string | null;
  gateFrameStatus: GateStatus;
  gateInterpretationStatus: GateStatus;
  gateThresholdStatus: GateStatus;
  text: string;
  note: string;
  at: string;
  audit: FrameTimelineAuditSnapshot | null;
};

type FrameTimelineAuditSnapshot = {
  stage: string;
  policyName: string;
  policyVersion: string;
  sourcePacketCount: number;
  sourceLatestPacketId: string | null;
  sourceLatestIteration: number | null;
  contextApplied: boolean;
  frameCoachSummary: string;
  interpretationCoachSummary: string;
  thresholdCoachSummary: string;
};

type FrameTimelineMeta = {
  branchId?: string;
  parentFrameId?: string | null;
  lineageVersion?: number;
  audit?: EngineStageAuditResponse | null;
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

type AudienceMode = "public" | "research";

type ModelComparisonSnapshot = {
  id: string;
  model: DetachedModel;
  at: string;
  source: string | null;
  note: string | null;
  framePacket: ReturnType<typeof evaluateFrameGate>["packet"];
  interpretationPacket: ReturnType<typeof evaluateInterpretationGate>["packet"];
  thresholdPacket: ReturnType<typeof evaluateThresholdGate>["packet"];
  gateFrameStatus: GateStatus;
  gateInterpretationStatus: GateStatus;
  gateThresholdStatus: GateStatus;
  recommendation: string | null;
  warningLevel: string | null;
};

type GateStageId = "frame" | "interpretation" | "threshold";

type UnresolvedGateItem = {
  key: string;
  stageId: GateStageId;
  stage: string;
  label: string;
  detail: string;
  targetId: string;
};

type StageAuditContextOverrides = {
  frame?: Record<string, unknown>;
  interpretation?: Record<string, unknown>;
  threshold?: Record<string, unknown>;
};

type StageAuditMode = "canonical" | "preview";

type StageAuditRequest = {
  sessionId?: string;
  overrides?: StageAuditContextOverrides;
  mode?: StageAuditMode;
};

type AuthSessionState = {
  authenticated: boolean;
  engineControlAllowed: boolean;
  user: string | null;
};

type EngineWorkspaceState = {
  schema_version: "2026-05-19";
  frame_locked: boolean;
  report_locked: boolean;
  report_corpus: string;
  report_input: string;
  last_evaluated_report_text: string;
  contradictions_status: InterpretationContradictionsStatus;
  contradictions_note: string;
  threshold_decision: ThresholdDecision;
  threshold_hold_reason: string;
  report_result: EngineStepResponse | null;
  stage_audit_context: StageAuditContextOverrides;
};

type EngineWorkspaceStateOverrides = Partial<Omit<EngineWorkspaceState, "schema_version">>;

const MODEL_SNAPSHOT_STORAGE_PREFIX = "nepsis_engine_model_snapshots";

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
  key_uncertainty: "",
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
  at: "",
};

const REPORT_STARTER_MESSAGE: ChatMessage = {
  id: "report-start",
  role: "nepsis",
  text: "Add observations, tests, and contradictory evidence. Run CALL + REPORT when ready.",
  at: "",
};

const POSTERIOR_STARTER_MESSAGE: ChatMessage = {
  id: "posterior-start",
  role: "nepsis",
  text: "Review posterior mix, ruin flags, and threshold gate. Then draft what carries forward.",
  at: "",
};

const DETACHED_STARTER: DetachedMessage = {
  id: "detached-start",
  role: "assistant",
  text: "Model sandbox is detached from Nepsis state. Browser-stored OpenAI keys are for local demos only.",
  at: "",
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

function containsAffirmedAny(haystack: string, terms: readonly string[]): boolean {
  return terms.some((term) => containsAffirmedTerm(haystack, term));
}

function containsAffirmedTerm(haystack: string, term: string): boolean {
  let start = 0;
  while (start < haystack.length) {
    const index = haystack.indexOf(term, start);
    if (index === -1) {
      return false;
    }
    if (!isNegatedEvidenceWindow(haystack, index, term.length)) {
      return true;
    }
    start = index + term.length;
  }
  return false;
}

function isNegatedEvidenceWindow(text: string, termIndex: number, termLength: number): boolean {
  const before = text.slice(Math.max(0, termIndex - 72), termIndex);
  const after = text.slice(termIndex + termLength, termIndex + termLength + 48);
  const around = `${before}${text.slice(termIndex, termIndex + termLength)}${after}`;
  return (
    /\b(no|not|without|none|denies|denied|absent|negative for|unconfirmed)\b/.test(before) ||
    /\bnot\s+(confirmed|present|observed|identified|established)\b/.test(after) ||
    /\b(no|not|without)\b[^.!?\n;]{0,80}\b(confirmed|present|observed|identified|established|yet)\b/.test(around)
  );
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

function packetMatchesCurrent(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function readBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function isContradictionsStatus(value: unknown): value is InterpretationContradictionsStatus {
  return value === "unreviewed" || value === "none_identified" || value === "declared";
}

function isThresholdDecision(value: unknown): value is ThresholdDecision {
  return value === "undecided" || value === "recommend" || value === "hold";
}

function isEngineStepResponse(value: unknown): value is EngineStepResponse {
  const record = asRecord(value);
  return Boolean(
    record &&
      typeof record.decision === "string" &&
      typeof record.stage === "string" &&
      asRecord(record.posterior) &&
      asRecord(record.session),
  );
}

function readWorkspaceState(value: unknown): Partial<EngineWorkspaceState> | null {
  const record = asRecord(value);
  if (!record || record.schema_version !== "2026-05-19") {
    return null;
  }
  const stageAuditContext = asRecord(record.stage_audit_context);
  return {
    frame_locked: readBoolean(record.frame_locked, false),
    report_locked: readBoolean(record.report_locked, false),
    report_corpus: readString(record.report_corpus) ?? "",
    report_input: readString(record.report_input) ?? "",
    last_evaluated_report_text: readString(record.last_evaluated_report_text) ?? "",
    contradictions_status: isContradictionsStatus(record.contradictions_status)
      ? record.contradictions_status
      : "unreviewed",
    contradictions_note: readString(record.contradictions_note) ?? "",
    threshold_decision: isThresholdDecision(record.threshold_decision) ? record.threshold_decision : "undecided",
    threshold_hold_reason: readString(record.threshold_hold_reason) ?? "",
    report_result: isEngineStepResponse(record.report_result) ? record.report_result : null,
    stage_audit_context: stageAuditContext as StageAuditContextOverrides | undefined,
  };
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

function formatMessageTime(value: string): string | null {
  const ts = toTimestamp(value);
  if (!Number.isFinite(ts)) {
    return null;
  }
  return new Date(ts).toLocaleTimeString();
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

function provenanceForPacket(
  records: PacketProvenanceRecord[] | null | undefined,
  packetId: string | null | undefined,
): PacketProvenanceRecord | null {
  if (!records || !packetId) {
    return null;
  }
  return records.find((record) => record.packet_id === packetId) ?? null;
}

function shortHash(value: string | null | undefined): string {
  if (!value) {
    return "n/a";
  }
  return value.replace(/^sha256:/, "").slice(0, 12);
}

function deriveSafetySign(text: string): SignBuildResult {
  const lower = text.toLowerCase();
  const criticalFromTag = parseBoolTag(text, "critical_signal");
  const policyFromTag = parseBoolTag(text, "policy_violation");
  const critical_signal =
    criticalFromTag ??
    containsAffirmedAny(lower, [
      "critical",
      "catastrophic",
      "ruin",
      "urgent",
      "imminent",
      "red flag",
      "unsafe",
      "severe",
    ]);
  const policy_violation =
    policyFromTag ?? containsAffirmedAny(lower, ["policy violation", "violation", "non-compliant"]);
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
  const uncertainty = optionalText(draft.key_uncertainty);
  const hard = parseLineList(draft.constraints_hard_text);
  const soft = parseLineList(draft.constraints_soft_text);
  const rationaleParts = [
    optionalText(draft.red_definition) ? `Red channel: ${draft.red_definition.trim()}` : null,
    optionalText(draft.blue_goals) ? `Blue channel: ${draft.blue_goals.trim()}` : null,
    uncertainty ? `Uncertainty: ${uncertainty}` : null,
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
  const rationale = frame.rationale_for_change ?? "";
  return {
    text: frame.text ?? "",
    objective_type: frame.objective_type ?? "sensemake",
    domain: frame.domain ?? "",
    time_horizon: frame.time_horizon ?? "short",
    key_uncertainty: readRationaleSegment(rationale, "Uncertainty"),
    constraints_hard_text: lineListToText(frame.constraints_hard),
    constraints_soft_text: lineListToText(frame.constraints_soft),
    red_definition: readRationaleSegment(rationale, "Red channel"),
    blue_goals: readRationaleSegment(rationale, "Blue channel"),
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

function warningBadgeClass(level: string | undefined): string {
  if (level === "red") {
    return "bg-red-500/20 text-red-200 border-red-500/40";
  }
  if (level === "yellow") {
    return "bg-amber-500/20 text-amber-100 border-amber-500/40";
  }
  return "bg-emerald-500/20 text-emerald-100 border-emerald-500/40";
}

function gateBadgeClass(status: GateStatus): string {
  if (status === "PASS") {
    return "border-emerald-500/40 bg-emerald-500/15 text-emerald-200";
  }
  if (status === "WARN") {
    return "border-amber-500/40 bg-amber-500/15 text-amber-100";
  }
  return "border-red-500/40 bg-red-500/15 text-red-200";
}

function gateTextClass(status: GateStatus): string {
  if (status === "PASS") {
    return "text-emerald-300";
  }
  if (status === "WARN") {
    return "text-amber-200";
  }
  return "text-red-200";
}

function gateMissingText<TPacket>(gate: GateResult<TPacket>): string {
  if (gate.missing.length > 0) {
    return gate.missing.join(", ");
  }
  if (gate.warnings.length > 0) {
    return gate.warnings.join(", ");
  }
  return "All required checks passed.";
}

function coachMessage(coach: StageCoach): string {
  if (coach.prompts.length === 0) {
    return coach.summary;
  }
  return `${coach.summary}\nNext: ${coach.prompts.join(" ")}`;
}

function phaseRejectionMessage(result: EngineOperatorResult): string | null {
  if (!isPhaseRejection(result)) {
    return null;
  }
  const missing = result.missing.length > 0 ? ` Missing: ${result.missing.join(", ")}.` : "";
  const prompts = result.coach_prompts.length > 0 ? ` ${result.coach_prompts.join(" ")}` : "";
  return `${result.attempted_tool} refused at ${result.current_phase}.${missing}${prompts}`;
}

function normalizeGateStatus(value: unknown): GateStatus | null {
  if (value === "PASS" || value === "WARN" || value === "BLOCK") {
    return value;
  }
  return null;
}

function gateMissingTextForStage(
  stage: GateStageId,
  fallbackGate: GateResult<unknown>,
  audit: EngineStageAuditResponse | null | undefined,
): string {
  const gate = audit?.[stage];
  if (gate && gate.missing.length > 0) {
    return gate.missing.join(", ");
  }
  if (gate && gate.warnings.length > 0) {
    return gate.warnings.join(", ");
  }
  return gateMissingText(fallbackGate);
}

function selectCoach(
  stage: GateStageId,
  fallback: StageCoach,
  audit: EngineStageAuditResponse | null | undefined,
): StageCoach {
  if (!audit) {
    return fallback;
  }
  const gate = audit[stage];
  if (!gate || typeof gate !== "object") {
    return fallback;
  }
  const coach = (gate as { coach?: unknown }).coach;
  if (!coach || typeof coach !== "object") {
    return fallback;
  }
  const maybeSummary = (coach as { summary?: unknown }).summary;
  const maybePrompts = (coach as { prompts?: unknown }).prompts;
  const maybeStatus = (coach as { status?: unknown }).status;
  if (typeof maybeSummary !== "string" || !Array.isArray(maybePrompts)) {
    return fallback;
  }
  const prompts = maybePrompts.filter((value): value is string => typeof value === "string" && value.trim().length > 0);
  const status = maybeStatus === "PASS" || maybeStatus === "WARN" || maybeStatus === "BLOCK" ? maybeStatus : fallback.status;
  return {
    status,
    summary: maybeSummary,
    prompts,
  };
}

function frameTimelineAuditSnapshot(
  audit: EngineStageAuditResponse | null | undefined,
): FrameTimelineAuditSnapshot | null {
  if (!audit) {
    return null;
  }
  const policyName =
    typeof audit.policy?.name === "string" && audit.policy.name.trim().length > 0
      ? audit.policy.name
      : "unknown_policy";
  const policyVersion =
    typeof audit.policy?.version === "string" && audit.policy.version.trim().length > 0
      ? audit.policy.version
      : "unknown_version";
  return {
    stage: audit.stage,
    policyName,
    policyVersion,
    sourcePacketCount: audit.source.packet_count,
    sourceLatestPacketId: audit.source.latest_packet_id,
    sourceLatestIteration: audit.source.latest_iteration,
    contextApplied: audit.source.context_applied,
    frameCoachSummary: audit.frame.coach.summary,
    interpretationCoachSummary: audit.interpretation.coach.summary,
    thresholdCoachSummary: audit.threshold.coach.summary,
  };
}

function pipelineStateClass(state: "pass" | "warn" | "block" | "pending"): string {
  if (state === "pass") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-200";
  }
  if (state === "warn") {
    return "border-amber-500/40 bg-amber-500/10 text-amber-100";
  }
  if (state === "block") {
    return "border-red-500/40 bg-red-500/10 text-red-200";
  }
  return "border-nepsis-border bg-black/20 text-nepsis-muted";
}

function sessionBranchContext(sessionId: string): string {
  return sessionId.slice(0, 6) || "ws";
}

function parseBranchCounter(branchId: string | null | undefined): number {
  if (!branchId) {
    return 1;
  }
  const match = branchId.match(/-b(\d+)$/i);
  if (!match) {
    return 1;
  }
  const parsed = Number.parseInt(match[1], 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return 1;
  }
  return parsed;
}

function deltaMarker(changed: boolean): string {
  return changed ? "delta" : "same";
}

function gateTargetId(stageId: GateStageId, checkKey: string): string {
  if (stageId === "frame") {
    if (checkKey === "problem_statement") {
      return "frame-problem-statement";
    }
    if (checkKey === "catastrophic_outcome") {
      return "frame-catastrophic-outcome";
    }
    if (checkKey === "optimization_goal") {
      return "frame-optimization-goal";
    }
    if (checkKey === "decision_horizon") {
      return "frame-decision-horizon";
    }
    if (checkKey === "key_uncertainty") {
      return "frame-key-uncertainty";
    }
    if (checkKey === "constraint_structure") {
      return "frame-constraints-hard";
    }
    return "stage-frame";
  }
  if (stageId === "interpretation") {
    if (checkKey === "report_text") {
      return "report-input";
    }
    if (checkKey === "hypothesis_count" || checkKey === "evidence_count" || checkKey === "evaluation_freshness") {
      return "report-run-button";
    }
    if (checkKey === "contradictions_declared") {
      return "report-contradictions-status";
    }
    if (checkKey === "contradiction_density") {
      return "report-contradictions-note";
    }
    return "stage-interpretation";
  }
  if (checkKey === "posterior_available") {
    return "threshold-posterior";
  }
  if (checkKey === "loss_asymmetry" || checkKey === "red_override_metadata") {
    return "threshold-gate-metrics";
  }
  if (checkKey === "decision_declared" || checkKey === "red_override_enforced") {
    return "threshold-decision-select";
  }
  if (checkKey === "hold_reason") {
    return "threshold-hold-reason";
  }
  return "stage-threshold";
}

function isModelSnapshot(value: unknown): value is ModelComparisonSnapshot {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Partial<ModelComparisonSnapshot>;
  return (
    typeof candidate.id === "string" &&
    typeof candidate.model === "string" &&
    typeof candidate.at === "string" &&
    typeof candidate.gateFrameStatus === "string" &&
    typeof candidate.gateInterpretationStatus === "string" &&
    typeof candidate.gateThresholdStatus === "string" &&
    typeof candidate.framePacket === "object" &&
    candidate.framePacket !== null &&
    typeof candidate.interpretationPacket === "object" &&
    candidate.interpretationPacket !== null &&
    typeof candidate.thresholdPacket === "object" &&
    candidate.thresholdPacket !== null
  );
}

function pulseJumpTarget(target: HTMLElement): void {
  const previousOutline = target.style.outline;
  const previousOutlineOffset = target.style.outlineOffset;
  target.style.outline = "2px solid rgba(255, 206, 92, 0.95)";
  target.style.outlineOffset = "2px";
  window.setTimeout(() => {
    target.style.outline = previousOutline;
    target.style.outlineOffset = previousOutlineOffset;
  }, 1400);
}

function highlightAndScroll(targetId: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.requestAnimationFrame(() => {
    const target = document.getElementById(targetId);
    if (!target) {
      return;
    }
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    if (
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLInputElement ||
      target instanceof HTMLSelectElement ||
      target instanceof HTMLButtonElement
    ) {
      target.focus();
    }
    pulseJumpTarget(target as HTMLElement);
  });
}

function nextIncompleteFrameTarget(draft: FrameDraft): string {
  if (!optionalText(draft.text)) return "frame-problem-statement";
  if (!optionalText(draft.key_uncertainty)) return "frame-key-uncertainty";
  if (parseLineList(draft.constraints_hard_text).length === 0) return "frame-constraints-hard";
  if (parseLineList(draft.constraints_soft_text).length === 0) return "frame-constraints-soft";
  if (!optionalText(draft.red_definition)) return "frame-catastrophic-outcome";
  if (!optionalText(draft.blue_goals)) return "frame-optimization-goal";
  return "stage-frame";
}

export default function EnginePage() {
  const router = useRouter();
  const pathname = usePathname();
  const liveOperatorSurface = pathname.startsWith("/operator");

  const {
    loading,
    error,
    clearError,
    healthy,
    sessions,
    activeSession,
    packets,
    provenance,
    auditExport,
    refreshHealth,
    refreshSessions,
    loadSession,
    refreshPackets,
    refreshProvenance,
    exportSessionAudit,
    stageAudit,
    updateWorkspaceState,
    lockOperatorFrame,
    runOperatorReport,
    lockOperatorReport,
    setOperatorThresholdDecision,
    commitOperatorIteration,
    abandonOperatorSession,
    lastAudit,
  } = useEngineSession();

  const [localError, setLocalError] = useState<string | null>(null);
  const [audienceMode, setAudienceMode] = useState<AudienceMode>("public");
  const [developerToolsEnabled, setDeveloperToolsEnabled] = useState(false);
  const [systemStatusOpen, setSystemStatusOpen] = useState(false);
  const [sandboxOpen, setSandboxOpen] = useState(false);
  const [authSession, setAuthSession] = useState<AuthSessionState | null>(null);
  const [hasConnectedKey, setHasConnectedKey] = useState<boolean | null>(null);
  const [showConnectedNotice, setShowConnectedNotice] = useState(false);
  const [connectedFromQuery, setConnectedFromQuery] = useState(false);

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
  const [lastEvaluatedReportText, setLastEvaluatedReportText] = useState("");
  const [contradictionsStatus, setContradictionsStatus] =
    useState<InterpretationContradictionsStatus>("unreviewed");
  const [contradictionsNote, setContradictionsNote] = useState("");
  const [thresholdDecision, setThresholdDecision] = useState<ThresholdDecision>("undecided");
  const [thresholdHoldReason, setThresholdHoldReason] = useState("");

  const [frameLocked, setFrameLocked] = useState(false);
  const [reportLocked, setReportLocked] = useState(false);
  const [frameCollapsed, setFrameCollapsed] = useState(false);

  const [reportResult, setReportResult] = useState<EngineStepResponse | null>(null);
  const [frameTimeline, setFrameTimeline] = useState<FrameTimelineEntry[]>([]);
  const [activeBranchId, setActiveBranchId] = useState("ws-b1");
  const [, setBranchCounter] = useState(1);
  const [pendingBranchParentFrameId, setPendingBranchParentFrameId] = useState<string | null>(null);
  const [modelSnapshots, setModelSnapshots] = useState<ModelComparisonSnapshot[]>([]);
  const [loadedSnapshotStorageKey, setLoadedSnapshotStorageKey] = useState<string | null>(null);

  const [detachedModel, setDetachedModel] = useState<DetachedModel>("gpt-4.1");
  const [detachedCompare, setDetachedCompare] = useState(false);
  const [detachedSource, setDetachedSource] = useState("");
  const [detachedInput, setDetachedInput] = useState("");
  const [detachedChat, setDetachedChat] = useState<DetachedMessage[]>([DETACHED_STARTER]);
  const [detachedBusy, setDetachedBusy] = useState(false);
  const [modelAssistOpen, setModelAssistOpen] = useState(false);
  const [modelAssistBusy, setModelAssistBusy] = useState(false);
  const [activeAssistTarget, setActiveAssistTarget] = useState<OperatorAssistTarget | null>(null);
  const [assistReviews, setAssistReviews] = useState<AssistReview[]>([]);
  const [editingAssistId, setEditingAssistId] = useState<string | null>(null);

  const snapshotStorageKey = useMemo(
    () => `${MODEL_SNAPSHOT_STORAGE_PREFIX}:${activeSession?.session_id ?? "workspace"}`,
    [activeSession?.session_id],
  );
  const packetEvents = useMemo(() => buildPacketEvents(packets), [packets]);
  const compactTimeline = useMemo<CompactTimelineItem[]>(() => {
    const frameItems: CompactTimelineItem[] = frameTimeline.map((entry, idx) => ({
      id: `frame:${entry.key}`,
      kind: "frame",
      label: `L${entry.lineageVersion} · ${entry.branchId} · v${entry.frameVersion}`,
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
    let cancelled = false;

    async function loadWorkspaceState() {
      let nextAuth: AuthSessionState | null = null;
      try {
        const res = await fetch("/api/auth/session", { cache: "no-store" });
        if (res.ok) {
          const data = (await res.json()) as Partial<AuthSessionState>;
          nextAuth = {
            authenticated: Boolean(data.authenticated),
            engineControlAllowed: Boolean(data.engineControlAllowed),
            user: typeof data.user === "string" ? data.user : null,
          };
        }
      } catch {
        nextAuth = null;
      }

      if (cancelled) {
        return;
      }
      setAuthSession(nextAuth);

      await refreshHealth();
      if (nextAuth?.engineControlAllowed) {
        await refreshSessions();
      }
    }

    void loadWorkspaceState();
    return () => {
      cancelled = true;
    };
  }, [refreshHealth, refreshSessions]);

  useEffect(() => {
    if (sessions.length > 0 && !sessionToOpen) {
      setSessionToOpen(sessions[0].session_id);
    }
  }, [sessions, sessionToOpen]);

  useEffect(() => {
    if (!activeSession) {
      return;
    }
    const resolvedBranchId = activeSession.branch_id ?? `${sessionBranchContext(activeSession.session_id)}-b1`;
    setActiveBranchId(resolvedBranchId);
    setBranchCounter(parseBranchCounter(resolvedBranchId));
    setPendingBranchParentFrameId(activeSession.parent_frame_id ?? null);
  }, [activeSession]);

  useEffect(() => {
    if (!activeSession?.session_id || packets.length === 0) {
      return;
    }
    void refreshProvenance(activeSession.session_id);
  }, [activeSession?.session_id, packets.length, refreshProvenance]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    setConnectedFromQuery(new URLSearchParams(window.location.search).get("connected") === "1");
  }, []);

  useEffect(() => {
    let connected = connectedFromQuery;
    try {
      connected = connected || consumeConnectedNotice();
      setHasConnectedKey(hasStoredOpenAiKey());
    } catch {
      setHasConnectedKey(false);
    }
    setShowConnectedNotice(connected);
  }, [connectedFromQuery]);

  useEffect(() => {
    if (!connectedFromQuery) {
      return;
    }
    router.replace("/engine");
  }, [connectedFromQuery, router]);

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

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    try {
      const raw = window.localStorage.getItem(snapshotStorageKey);
      if (!raw) {
        setModelSnapshots([]);
      } else {
        const parsed = JSON.parse(raw);
        const next = Array.isArray(parsed) ? parsed.filter(isModelSnapshot) : [];
        setModelSnapshots(next);
      }
    } catch {
      setModelSnapshots([]);
    } finally {
      setLoadedSnapshotStorageKey(snapshotStorageKey);
    }
  }, [snapshotStorageKey]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (loadedSnapshotStorageKey !== snapshotStorageKey) {
      return;
    }
    try {
      window.localStorage.setItem(snapshotStorageKey, JSON.stringify(modelSnapshots));
    } catch {
      // Ignore localStorage persistence errors.
    }
  }, [snapshotStorageKey, loadedSnapshotStorageKey, modelSnapshots]);

  const currentStageStep = !frameLocked ? 1 : !reportLocked ? 2 : 3;
  const userMode = !developerToolsEnabled;
  const showOperatorControls = developerToolsEnabled;
  const panelHeightClass = userMode ? "min-h-[640px]" : "min-h-[760px]";
  const frameHardConstraints = useMemo(
    () => parseLineList(frameDraft.constraints_hard_text),
    [frameDraft.constraints_hard_text],
  );
  const frameSoftConstraints = useMemo(
    () => parseLineList(frameDraft.constraints_soft_text),
    [frameDraft.constraints_soft_text],
  );
  const reportDraftText = useMemo(
    () => [reportCorpus, optionalText(reportInput) ?? ""].filter(Boolean).join("\n"),
    [reportCorpus, reportInput],
  );
  const evidenceLineCount = useMemo(() => parseLineList(reportDraftText).length, [reportDraftText]);
  const governance = reportResult?.governance;
  const posteriorRows = useMemo(
    () =>
      Object.entries(reportResult?.posterior ?? {}).sort((a, b) => {
        return b[1] - a[1];
      }),
    [reportResult?.posterior],
  );
  const posteriorHypotheses = useMemo(() => posteriorRows.map(([name]) => name), [posteriorRows]);
  const gateCrossed =
    governance?.p_bad != null && governance?.theta != null ? governance.p_bad >= governance.theta : null;

  const frameGate = useMemo(
    () =>
      evaluateFrameGate({
        problemStatement: frameDraft.text,
        catastrophicOutcome: frameDraft.red_definition,
        optimizationGoal: frameDraft.blue_goals,
        decisionHorizon: frameDraft.time_horizon,
        keyUncertainty: frameDraft.key_uncertainty,
        hardConstraints: frameHardConstraints,
        softConstraints: frameSoftConstraints,
      }),
    [frameDraft, frameHardConstraints, frameSoftConstraints],
  );
  const interpretationGate = useMemo(
    () =>
      evaluateInterpretationGate({
        reportText: reportDraftText,
        posteriorHypotheses,
        evidenceCount: evidenceLineCount,
        reportSynced: reportDraftText.trim() === lastEvaluatedReportText.trim(),
        contradictionsStatus,
        contradictionsNote,
        contradictionDensity: governance?.contradiction_density ?? null,
      }),
    [
      reportDraftText,
      posteriorHypotheses,
      evidenceLineCount,
      lastEvaluatedReportText,
      contradictionsStatus,
      contradictionsNote,
      governance?.contradiction_density,
    ],
  );
  const thresholdGate = useMemo(
    () =>
      evaluateThresholdGate({
        posteriorHypotheses,
        lossTreat: governance?.loss_treat,
        lossNotTreat: governance?.loss_notreat,
        warningLevel: governance?.warning_level,
        gateCrossed,
        recommendation: governance?.recommended_action ?? reportResult?.decision ?? null,
        decision: thresholdDecision,
        holdReason: thresholdHoldReason,
      }),
    [
      posteriorHypotheses,
      governance?.loss_treat,
      governance?.loss_notreat,
      governance?.warning_level,
      gateCrossed,
      governance?.recommended_action,
      reportResult?.decision,
      thresholdDecision,
      thresholdHoldReason,
    ],
  );
  const frameGateView = useMemo<GateResult<unknown>>(() => {
    const status = normalizeGateStatus(lastAudit?.frame?.status);
    if (!lastAudit?.frame || status == null || !packetMatchesCurrent(lastAudit.frame.packet, frameGate.packet)) {
      return frameGate as unknown as GateResult<unknown>;
    }
    return {
      status,
      checks: lastAudit.frame.checks,
      missing: lastAudit.frame.missing,
      warnings: lastAudit.frame.warnings,
      packet: lastAudit.frame.packet,
    };
  }, [lastAudit, frameGate]);
  const interpretationGateView = useMemo<GateResult<unknown>>(() => {
    const status = normalizeGateStatus(lastAudit?.interpretation?.status);
    if (
      !lastAudit?.interpretation ||
      status == null ||
      !packetMatchesCurrent(lastAudit.interpretation.packet, interpretationGate.packet)
    ) {
      return interpretationGate as unknown as GateResult<unknown>;
    }
    return {
      status,
      checks: lastAudit.interpretation.checks,
      missing: lastAudit.interpretation.missing,
      warnings: lastAudit.interpretation.warnings,
      packet: lastAudit.interpretation.packet,
    };
  }, [lastAudit, interpretationGate]);
  const thresholdGateView = useMemo<GateResult<unknown>>(() => {
    const status = normalizeGateStatus(lastAudit?.threshold?.status);
    if (!lastAudit?.threshold || status == null || !packetMatchesCurrent(lastAudit.threshold.packet, thresholdGate.packet)) {
      return thresholdGate as unknown as GateResult<unknown>;
    }
    return {
      status,
      checks: lastAudit.threshold.checks,
      missing: lastAudit.threshold.missing,
      warnings: lastAudit.threshold.warnings,
      packet: lastAudit.threshold.packet,
    };
  }, [lastAudit, thresholdGate]);
  const displayFrameGateStatus = frameGateView.status;
  const displayInterpretationGateStatus = interpretationGateView.status;
  const displayThresholdGateStatus = thresholdGateView.status;
  const frameCoach = useMemo(() => buildFrameCoach(frameGate), [frameGate]);
  const interpretationCoach = useMemo(
    () => buildInterpretationCoach(interpretationGate),
    [interpretationGate],
  );
  const thresholdCoach = useMemo(() => buildThresholdCoach(thresholdGate), [thresholdGate]);
  const displayFrameCoach = useMemo(
    () => selectCoach("frame", frameCoach, lastAudit),
    [frameCoach, lastAudit],
  );
  const displayInterpretationCoach = useMemo(
    () => selectCoach("interpretation", interpretationCoach, lastAudit),
    [interpretationCoach, lastAudit],
  );
  const displayThresholdCoach = useMemo(
    () => selectCoach("threshold", thresholdCoach, lastAudit),
    [thresholdCoach, lastAudit],
  );
  const latestSessionFrameEntry = useMemo(() => {
    if (!activeSession) {
      return null;
    }
    return (
      [...frameTimeline]
        .filter((entry) => entry.sessionId === activeSession.session_id)
        .sort((a, b) => a.lineageVersion - b.lineageVersion)
        .at(-1) ?? null
    );
  }, [frameTimeline, activeSession]);
  const audienceLabels = useMemo(() => {
    if (audienceMode === "research") {
      return {
        stage1: "Priors / Frame",
        stage2: "Interpretation Engine",
        stage3: "Posterior / Thresholds",
        stage1Subtitle: "Objective, horizon, domain, constraints, and risk posture.",
        stage2Subtitle: "Interpretants, evidence linkage, contradiction discipline, and report state.",
        stage3Subtitle: "Posterior confidence, thresholds, and carry-forward update policy.",
        history: "Reasoning Lineage",
      };
    }
    return {
      stage1: "Context",
      stage2: "Reasoning",
      stage3: "Decision",
      stage1Subtitle: "Define the question, constraints, and key risks before running evidence.",
      stage2Subtitle: "Gather evidence, compare explanations, and log contradictions.",
      stage3Subtitle: "Decide whether to act or hold, then draft the next revision.",
      history: "Reasoning History",
    };
  }, [audienceMode]);
  const baselineSnapshot = useMemo(
    () => modelSnapshots.find((snapshot) => snapshot.model === "gpt-4.1") ?? modelSnapshots[0] ?? null,
    [modelSnapshots],
  );
  const modelDeltaRows = useMemo(() => {
    if (!baselineSnapshot) {
      return [];
    }
    return modelSnapshots
      .filter((snapshot) => snapshot.id !== baselineSnapshot.id)
      .map((snapshot) => {
        const frameDeltaCount = [
          snapshot.framePacket.problem_statement !== baselineSnapshot.framePacket.problem_statement,
          snapshot.framePacket.catastrophic_outcome !== baselineSnapshot.framePacket.catastrophic_outcome,
          snapshot.framePacket.optimization_goal !== baselineSnapshot.framePacket.optimization_goal,
          snapshot.framePacket.key_uncertainty !== baselineSnapshot.framePacket.key_uncertainty,
        ].filter(Boolean).length;
        const interpretationDeltaCount = [
          snapshot.interpretationPacket.hypothesis_count !== baselineSnapshot.interpretationPacket.hypothesis_count,
          snapshot.interpretationPacket.evidence_count !== baselineSnapshot.interpretationPacket.evidence_count,
          snapshot.interpretationPacket.contradictions_status !==
            baselineSnapshot.interpretationPacket.contradictions_status,
        ].filter(Boolean).length;
        const thresholdDeltaCount = [
          snapshot.thresholdPacket.decision !== baselineSnapshot.thresholdPacket.decision,
          snapshot.thresholdPacket.gate_crossed !== baselineSnapshot.thresholdPacket.gate_crossed,
          snapshot.thresholdPacket.recommendation !== baselineSnapshot.thresholdPacket.recommendation,
        ].filter(Boolean).length;
        return {
          snapshot,
          frameDeltaCount,
          interpretationDeltaCount,
          thresholdDeltaCount,
          gateStatusDelta:
            snapshot.gateFrameStatus !== baselineSnapshot.gateFrameStatus ||
            snapshot.gateInterpretationStatus !== baselineSnapshot.gateInterpretationStatus ||
            snapshot.gateThresholdStatus !== baselineSnapshot.gateThresholdStatus,
        };
      });
  }, [modelSnapshots, baselineSnapshot]);
  const processSteps = useMemo(
    () => [
      {
        label: "Extract frame",
        state:
          displayFrameGateStatus === "PASS"
            ? "pass"
            : displayFrameGateStatus === "WARN"
              ? "warn"
              : "block",
      },
      {
        label: "Validate completeness",
        state:
          displayFrameGateStatus === "PASS"
            ? "pass"
            : displayFrameGateStatus === "WARN"
              ? "warn"
              : "block",
      },
      {
        label: "Run interpretation",
        state: reportResult ? "pass" : frameLocked ? "warn" : "pending",
      },
      {
        label: "Compute posterior",
        state: posteriorRows.length > 0 ? "pass" : reportResult ? "warn" : "pending",
      },
      {
        label: "Apply thresholds",
        state:
          reportResult == null
            ? "pending"
            : displayThresholdGateStatus === "PASS"
              ? "pass"
              : displayThresholdGateStatus === "WARN"
                ? "warn"
                : "block",
      },
    ] as const,
    [
      displayFrameGateStatus,
      reportResult,
      frameLocked,
      posteriorRows.length,
      displayThresholdGateStatus,
    ],
  );
  const unresolvedBlocks = useMemo<UnresolvedGateItem[]>(() => {
    const stages: Array<{ stageId: GateStageId; stage: string; gate: GateResult<unknown> }> = [
      { stageId: "frame", stage: audienceLabels.stage1, gate: frameGateView },
      {
        stageId: "interpretation",
        stage: audienceLabels.stage2,
        gate: interpretationGateView,
      },
      { stageId: "threshold", stage: audienceLabels.stage3, gate: thresholdGateView },
    ];
    return stages.flatMap((entry) =>
      entry.gate.checks
        .filter((check) => check.status === "block")
        .map((check) => ({
          key: `${entry.stageId}:${check.key}`,
          stageId: entry.stageId,
          stage: entry.stage,
          label: check.label,
          detail: check.detail,
          targetId: gateTargetId(entry.stageId, check.key),
        })),
    );
  }, [
    audienceLabels.stage1,
    audienceLabels.stage2,
    audienceLabels.stage3,
    frameGateView,
    interpretationGateView,
    thresholdGateView,
  ]);
  const unresolvedWarnings = useMemo<UnresolvedGateItem[]>(() => {
    const stages: Array<{ stageId: GateStageId; stage: string; gate: GateResult<unknown> }> = [
      { stageId: "frame", stage: audienceLabels.stage1, gate: frameGateView },
      {
        stageId: "interpretation",
        stage: audienceLabels.stage2,
        gate: interpretationGateView,
      },
      { stageId: "threshold", stage: audienceLabels.stage3, gate: thresholdGateView },
    ];
    return stages.flatMap((entry) =>
      entry.gate.checks
        .filter((check) => check.status === "warn")
        .map((check) => ({
          key: `${entry.stageId}:${check.key}`,
          stageId: entry.stageId,
          stage: entry.stage,
          label: check.label,
          detail: check.detail,
          targetId: gateTargetId(entry.stageId, check.key),
        })),
    );
  }, [
    audienceLabels.stage1,
    audienceLabels.stage2,
    audienceLabels.stage3,
    frameGateView,
    interpretationGateView,
    thresholdGateView,
  ]);

  function clearAllErrors() {
    clearError();
    setLocalError(null);
  }

  function assistInputForTarget(target: OperatorAssistTarget): string {
    switch (target) {
      case "frame.text":
        return frameDraft.text;
      case "frame.key_uncertainty":
        return frameDraft.key_uncertainty;
      case "frame.constraints_hard":
        return frameDraft.constraints_hard_text;
      case "frame.constraints_soft":
        return frameDraft.constraints_soft_text;
      case "frame.red_definition":
        return frameDraft.red_definition;
      case "frame.blue_goals":
        return frameDraft.blue_goals;
      case "threshold.hold_reason":
        return thresholdHoldReason;
      case "next_frame.text":
        return nextFrameDraft.text;
    }
  }

  async function requestFieldAssist(target: OperatorAssistTarget, input: string = assistInputForTarget(target)) {
    clearAllErrors();
    const prompt = optionalText(input) ?? `Suggest ${targetLabel(target)} for the current Nepsis operator loop.`;
    setModelAssistOpen(true);
    setActiveAssistTarget(target);
    setModelAssistBusy(true);
    try {
      const result = await requestOperatorModel({
        mode: "suggest_field",
        target,
        input: prompt,
        context: {
          family,
          current_frame: frameDraft,
          threshold_decision: thresholdDecision,
          threshold_hold_reason: thresholdHoldReason,
          next_frame: nextFrameDraft,
          gate_status: {
            frame: displayFrameGateStatus,
            interpretation: displayInterpretationGateStatus,
            threshold: displayThresholdGateStatus,
          },
        },
      });
      if (result.suggestions.length === 0) {
        setLocalError(`Model assist returned no suggestion for ${targetLabel(target)}.`);
        return;
      }
      setAssistReviews((prev) => [
        ...prev,
        ...result.suggestions.map((suggestion) => ({
          ...suggestion,
          uiStatus: "draft" as const,
          createdAt: new Date().toISOString(),
          model: result.model,
        })),
      ]);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "Model assist failed.");
    } finally {
      setModelAssistBusy(false);
      setActiveAssistTarget(null);
    }
  }

  function editAssist(id: string, value: string) {
    setAssistReviews((prev) =>
      prev.map((review) => (review.id === id ? { ...review, editedValue: value } : review)),
    );
  }

  function rejectAssist(id: string) {
    setEditingAssistId(null);
    setAssistReviews((prev) =>
      prev.map((review) => (review.id === id ? { ...review, uiStatus: "rejected" } : review)),
    );
  }

  function applyAssist(review: AssistReview) {
    const text = review.editedValue ?? canonicalFieldText(review.proposedValue);
    if (review.target === "frame.text") {
      setFrameDraft((prev) => ({ ...prev, text }));
    }
    if (review.target === "frame.key_uncertainty") {
      setFrameDraft((prev) => ({ ...prev, key_uncertainty: text }));
    }
    if (review.target === "frame.constraints_hard") {
      setFrameDraft((prev) => ({ ...prev, constraints_hard_text: text }));
    }
    if (review.target === "frame.constraints_soft") {
      setFrameDraft((prev) => ({ ...prev, constraints_soft_text: text }));
    }
    if (review.target === "frame.red_definition") {
      setFrameDraft((prev) => ({ ...prev, red_definition: text }));
    }
    if (review.target === "frame.blue_goals") {
      setFrameDraft((prev) => ({ ...prev, blue_goals: text }));
    }
    if (review.target === "threshold.hold_reason") {
      setThresholdHoldReason(text);
    }
    if (review.target === "next_frame.text") {
      setNextFrameDraft((prev) => ({ ...prev, text }));
    }
    setEditingAssistId(null);
    setAssistReviews((prev) =>
      prev.map((item) =>
        item.id === review.id
          ? { ...item, uiStatus: review.editedValue !== undefined ? "edited" : "accepted" }
          : item,
      ),
    );
  }

  async function transitionAssistDispositions(
    currentFieldText: (target: OperatorAssistTarget) => string | null,
    reviews: AssistReview[] = assistReviews,
  ) {
    try {
      return await buildAssistDispositions(reviews, currentFieldText);
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "Could not build assist disposition metadata.");
      return null;
    }
  }

  function clearRecordedAssistReviews(recordedTargets: Set<OperatorAssistTarget>) {
    setAssistReviews((prev) =>
      prev.filter((review) => review.uiStatus !== "rejected" && !recordedTargets.has(review.target)),
    );
  }

  function jumpToUnresolvedCheck(item: UnresolvedGateItem) {
    clearAllErrors();
    if (!showOperatorControls) {
      if (item.stageId === "frame") {
        setFrameCollapsed(false);
      }
      if (item.stageId === "interpretation" && !frameLocked) {
        setLocalError(`Complete ${audienceLabels.stage1} first to access this check.`);
        return;
      }
      if (item.stageId === "threshold" && !reportLocked) {
        setLocalError(`Complete ${audienceLabels.stage2} first to access this check.`);
        return;
      }
    }
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(() => {
      const target =
        document.getElementById(item.targetId) ??
        document.getElementById(
          item.stageId === "frame"
            ? "stage-frame"
            : item.stageId === "interpretation"
              ? "stage-interpretation"
              : "stage-threshold",
        );
      if (!target) {
        return;
      }
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      if (
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLInputElement ||
        target instanceof HTMLSelectElement ||
        target instanceof HTMLButtonElement
      ) {
        target.focus();
      }
      pulseJumpTarget(target as HTMLElement);
    });
  }

  function appendFrameTimeline(
    sessionId: string,
    frame: EngineFrame | null | undefined,
    note: string,
    meta: FrameTimelineMeta = {},
  ) {
    if (!frame) {
      return;
    }
    const key = `${sessionId}:${frame.frame_version}`;
    setFrameTimeline((prev) => {
      if (prev.some((entry) => entry.key === key)) {
        return prev;
      }
      const sessionEntries = [...prev]
        .filter((entry) => entry.sessionId === sessionId)
        .sort((a, b) => a.lineageVersion - b.lineageVersion);
      const latestSessionEntry = sessionEntries.at(-1) ?? null;
      const lineageVersion = meta.lineageVersion ?? (latestSessionEntry?.lineageVersion ?? 0) + 1;
      const next = [
        ...prev,
        {
          key,
          sessionId,
          frameVersion: frame.frame_version,
          lineageVersion,
          branchId: meta.branchId ?? activeBranchId,
          parentFrameId: meta.parentFrameId ?? latestSessionEntry?.key ?? null,
          gateFrameStatus: displayFrameGateStatus,
          gateInterpretationStatus: displayInterpretationGateStatus,
          gateThresholdStatus: displayThresholdGateStatus,
          text: frame.text,
          note,
          at: new Date().toISOString(),
          audit: frameTimelineAuditSnapshot(meta.audit),
        },
      ];
      return next.sort((a, b) => a.lineageVersion - b.lineageVersion);
    });
  }

  function resetDownstreamStages() {
    setReportLocked(false);
    setReportResult(null);
    setReportCorpus("");
    setReportInput("");
    setLastEvaluatedReportText("");
    setContradictionsStatus("unreviewed");
    setContradictionsNote("");
    setThresholdDecision("undecided");
    setThresholdHoldReason("");
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

  function captureModelSnapshot(note: string | null = null) {
    const source = optionalText(detachedSource) ?? null;
    const snapshot: ModelComparisonSnapshot = {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      model: detachedModel,
      at: new Date().toISOString(),
      source,
      note,
      framePacket: frameGate.packet,
      interpretationPacket: interpretationGate.packet,
      thresholdPacket: thresholdGate.packet,
      gateFrameStatus: displayFrameGateStatus,
      gateInterpretationStatus: displayInterpretationGateStatus,
      gateThresholdStatus: displayThresholdGateStatus,
      recommendation: governance?.recommended_action ?? reportResult?.decision ?? null,
      warningLevel: governance?.warning_level ?? null,
    };
    setModelSnapshots((prev) => {
      const withoutExisting = prev.filter(
        (entry) => !(entry.model === snapshot.model && entry.source === snapshot.source),
      );
      return [...withoutExisting, snapshot].sort((a, b) => a.model.localeCompare(b.model));
    });
  }

  function clearModelSnapshots() {
    setModelSnapshots([]);
  }

  const requestBackendStageAudit = useCallback(
    async ({
      sessionId,
      overrides,
      mode = "canonical",
    }: StageAuditRequest = {}) => {
      const targetId = sessionId ?? activeSession?.session_id;
      if (!targetId) {
        return undefined;
      }
      if (mode === "canonical") {
        return stageAudit(undefined, targetId);
      }
      const frameContext = {
        ...(frameGate.packet as unknown as Record<string, unknown>),
        ...(overrides?.frame ?? {}),
      };
      const interpretationContext = {
        ...(interpretationGate.packet as unknown as Record<string, unknown>),
        ...(overrides?.interpretation ?? {}),
      };
      const thresholdContext = {
        ...(thresholdGate.packet as unknown as Record<string, unknown>),
        decision: thresholdDecision,
        hold_reason: thresholdHoldReason,
        ...(overrides?.threshold ?? {}),
      };
      return stageAudit(
        {
          context: {
            frame: frameContext,
            interpretation: interpretationContext,
            threshold: thresholdContext,
          },
        },
        targetId,
      );
    },
    [
      activeSession?.session_id,
      frameGate.packet,
      interpretationGate.packet,
      thresholdGate.packet,
      thresholdDecision,
      thresholdHoldReason,
      stageAudit,
    ],
  );

  const buildWorkspaceState = useCallback(
    (overrides: EngineWorkspaceStateOverrides = {}): EngineWorkspaceState => {
      const stageAuditContext: StageAuditContextOverrides =
        overrides.stage_audit_context ?? {
          frame: frameGate.packet as unknown as Record<string, unknown>,
          interpretation: interpretationGate.packet as unknown as Record<string, unknown>,
          threshold: {
            ...(thresholdGate.packet as unknown as Record<string, unknown>),
            decision: overrides.threshold_decision ?? thresholdDecision,
            hold_reason: overrides.threshold_hold_reason ?? thresholdHoldReason,
          },
        };
      return {
        schema_version: "2026-05-19",
        frame_locked: overrides.frame_locked ?? frameLocked,
        report_locked: overrides.report_locked ?? reportLocked,
        report_corpus: overrides.report_corpus ?? reportCorpus,
        report_input: overrides.report_input ?? reportInput,
        last_evaluated_report_text: overrides.last_evaluated_report_text ?? lastEvaluatedReportText,
        contradictions_status: overrides.contradictions_status ?? contradictionsStatus,
        contradictions_note: overrides.contradictions_note ?? contradictionsNote,
        threshold_decision: overrides.threshold_decision ?? thresholdDecision,
        threshold_hold_reason: overrides.threshold_hold_reason ?? thresholdHoldReason,
        report_result: "report_result" in overrides ? (overrides.report_result ?? null) : reportResult,
        stage_audit_context: stageAuditContext,
      };
    },
    [
      contradictionsNote,
      contradictionsStatus,
      frameGate.packet,
      frameLocked,
      interpretationGate.packet,
      lastEvaluatedReportText,
      reportCorpus,
      reportInput,
      reportLocked,
      reportResult,
      thresholdDecision,
      thresholdGate.packet,
      thresholdHoldReason,
    ],
  );

  const persistWorkspaceState = useCallback(
    async (overrides: EngineWorkspaceStateOverrides = {}, sessionId?: string) => {
      const targetId = sessionId ?? activeSession?.session_id;
      if (!targetId) {
        return undefined;
      }
      return updateWorkspaceState(targetId, {
        workspace_state: buildWorkspaceState(overrides) as unknown as Record<string, unknown>,
      });
    },
    [activeSession?.session_id, buildWorkspaceState, updateWorkspaceState],
  );

  useEffect(() => {
    if (!activeSession?.session_id || typeof window === "undefined") {
      return;
    }
    if (frameLocked || reportResult || reportLocked || lastEvaluatedReportText.trim()) {
      return;
    }
    const timeout = window.setTimeout(() => {
      void stageAudit(undefined, activeSession.session_id);
    }, 450);
    return () => {
      window.clearTimeout(timeout);
    };
  }, [activeSession?.session_id, frameLocked, lastEvaluatedReportText, reportLocked, reportResult, stageAudit]);

  useEffect(() => {
    if (!activeSession?.session_id || typeof window === "undefined" || !frameLocked) {
      return;
    }
    const timeout = window.setTimeout(() => {
      void persistWorkspaceState();
    }, 700);
    return () => {
      window.clearTimeout(timeout);
    };
  }, [
    activeSession?.session_id,
    contradictionsNote,
    contradictionsStatus,
    frameLocked,
    lastEvaluatedReportText,
    persistWorkspaceState,
    reportCorpus,
    reportInput,
    reportLocked,
    reportResult,
    thresholdDecision,
    thresholdHoldReason,
  ]);

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
    const workspace = readWorkspaceState(opened.workspace_state);
    const restoredReportResult = workspace?.report_result ?? null;
    const restoredReportCorpus = workspace?.report_corpus ?? "";
    const restoredReportInput = workspace?.report_input ?? "";
    const restoredReportLocked = Boolean(workspace?.report_locked && restoredReportResult);
    const restoredFrameLocked = workspace?.frame_locked ?? opened.stage !== "draft";
    setFamily(opened.family);
    setFrameDraft(hydrateFrameDraft(opened.frame));
    setNextFrameDraft(hydrateNextFrameDraft(opened.frame));
    setFrameLocked(restoredFrameLocked);
    setReportLocked(restoredReportLocked);
    setFrameCollapsed(restoredFrameLocked);
    setReportResult(restoredReportResult);
    setFrameChat([
      FRAME_STARTER_MESSAGE,
      createMessage(
        "nepsis",
        workspace
          ? `Loaded session ${shortSession(opened.session_id)} with saved gate context.`
          : `Loaded session ${shortSession(opened.session_id)} at stage ${opened.stage}.`,
      ),
    ]);
    setReportChat([REPORT_STARTER_MESSAGE]);
    setPosteriorChat(
      restoredReportResult
        ? [
            POSTERIOR_STARTER_MESSAGE,
            createMessage("nepsis", "Restored the last evaluated report and threshold context."),
          ]
        : [POSTERIOR_STARTER_MESSAGE],
    );
    setReportCorpus(restoredReportCorpus);
    setReportInput(restoredReportInput);
    setLastEvaluatedReportText(workspace?.last_evaluated_report_text ?? "");
    setContradictionsStatus(workspace?.contradictions_status ?? "unreviewed");
    setContradictionsNote(workspace?.contradictions_note ?? "");
    setThresholdDecision(workspace?.threshold_decision ?? "undecided");
    setThresholdHoldReason(workspace?.threshold_hold_reason ?? "");
    setAssistReviews([]);
    setEditingAssistId(null);
    setActiveAssistTarget(null);
    const initialBranchId = opened.branch_id ?? `${sessionBranchContext(opened.session_id)}-b1`;
    setActiveBranchId(initialBranchId);
    setBranchCounter(parseBranchCounter(initialBranchId));
    setPendingBranchParentFrameId(opened.parent_frame_id ?? null);
    await refreshPackets(opened.session_id);
    const audit = await requestBackendStageAudit({
      sessionId: opened.session_id,
      mode: "canonical",
    });
    appendFrameTimeline(opened.session_id, opened.frame, "Session opened", {
      branchId: initialBranchId,
      parentFrameId: opened.parent_frame_id ?? null,
      lineageVersion: opened.lineage_version ?? undefined,
      audit,
    });
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
    setActiveBranchId("ws-b1");
    setBranchCounter(1);
    setPendingBranchParentFrameId(null);
    setModelSnapshots([]);
    setAssistReviews([]);
    setEditingAssistId(null);
    setActiveAssistTarget(null);
    await refreshSessions();
  }

  async function handleSendFrameMessage() {
    clearAllErrors();
    const text = optionalText(frameInput);
    if (!text) {
      return;
    }
    pushFrameMessage("human", text);
    const audit = await requestBackendStageAudit({ mode: "preview" });
    pushFrameMessage("nepsis", coachMessage(selectCoach("frame", frameCoach, audit ?? lastAudit)));
    setFrameInput("");
  }

  async function handleSendReportMessage() {
    clearAllErrors();
    const text = optionalText(reportInput);
    if (!text) {
      return;
    }
    const previewReportText = [reportCorpus, text].filter(Boolean).join("\n");
    const previewInterpretationGate = evaluateInterpretationGate({
      reportText: previewReportText,
      posteriorHypotheses,
      evidenceCount: parseLineList(previewReportText).length,
      reportSynced: previewReportText.trim() === lastEvaluatedReportText.trim(),
      contradictionsStatus,
      contradictionsNote,
      contradictionDensity: governance?.contradiction_density ?? null,
    });
    const previewCoach = buildInterpretationCoach(previewInterpretationGate);
    const audit = await requestBackendStageAudit({
      mode: "preview",
      overrides: {
        interpretation: {
          ...previewInterpretationGate.packet,
        },
      },
    });
    pushReportMessage("human", text);
    pushReportMessage("nepsis", coachMessage(selectCoach("interpretation", previewCoach, audit ?? lastAudit)));
    setReportCorpus((prev) => (prev ? `${prev}\n${text}` : text));
    setReportInput("");
  }

  async function handleSendPosteriorMessage() {
    clearAllErrors();
    const text = optionalText(posteriorInput);
    if (!text) {
      return;
    }
    const audit = await requestBackendStageAudit({
      mode: "preview",
      overrides: {
        threshold: {
          decision: thresholdDecision,
          hold_reason: thresholdHoldReason,
        },
      },
    });
    pushPosteriorMessage("human", text);
    pushPosteriorMessage("nepsis", coachMessage(selectCoach("threshold", thresholdCoach, audit ?? lastAudit)));
    setPosteriorInput("");
  }

  async function handleSendDetachedMessage() {
    clearAllErrors();
    const text = optionalText(detachedInput);
    if (!text) {
      return;
    }
    const source = optionalText(detachedSource) ?? null;
    setDetachedChat((prev) => [...prev, createDetachedMessage("human", text, detachedModel, source)]);
    setDetachedInput("");
    setDetachedBusy(true);
    try {
      const apiKey = getStoredOpenAiKey();
      const res = await fetch("/api/run-with-nepsis", {
        method: "POST",
        headers: withCsrfHeader({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          prompt: text,
          model: detachedModel,
          apiKey: apiKey ?? undefined,
        }),
      });
      const data = (await res.json().catch(() => null)) as
        | {
            error?: unknown;
            detail?: unknown;
            outputText?: unknown;
            rawAnswer?: unknown;
          }
        | null;
      if (!res.ok) {
        const message =
          typeof data?.detail === "string"
            ? data.detail
            : typeof data?.error === "string"
              ? data.error
              : "Sandbox request failed.";
        throw new Error(message);
      }
      const outputText =
        typeof data?.outputText === "string"
          ? data.outputText
          : typeof data?.rawAnswer === "string"
            ? data.rawAnswer
            : "";
      setDetachedChat((prev) => [
        ...prev,
        createDetachedMessage(
          "assistant",
          outputText || `No text returned from ${detachedModel}.`,
          detachedModel,
          source,
        ),
      ]);
      if (detachedCompare) {
        captureModelSnapshot(text);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Sandbox request failed.";
      setLocalError(message);
      setDetachedChat((prev) => [
        ...prev,
        createDetachedMessage("assistant", `Sandbox request failed: ${message}`, detachedModel, source),
      ]);
    } finally {
      setDetachedBusy(false);
    }
  }

  async function handleLockFrame() {
    clearAllErrors();
    if (authSession && !authSession.engineControlAllowed) {
      setLocalError("Sign in to create or update engine sessions.");
      pushFrameMessage("nepsis", "Engine session controls are locked until you sign in.");
      return;
    }
    let auditForAction: EngineStageAuditResponse | undefined;
    let frameActionStatus = displayFrameGateStatus;
    if (activeSession) {
      auditForAction = await requestBackendStageAudit({
        sessionId: activeSession.session_id,
        mode: "preview",
      });
      frameActionStatus = normalizeGateStatus(auditForAction?.frame?.status) ?? frameActionStatus;
    }
    if (frameActionStatus !== "PASS") {
      setLocalError(`Frame gate blocked: ${gateMissingTextForStage("frame", frameGateView, auditForAction ?? lastAudit)}`);
      pushFrameMessage("nepsis", coachMessage(selectCoach("frame", frameCoach, auditForAction ?? lastAudit)));
      return;
    }

    const text = optionalText(frameDraft.text);
    if (!text) {
      setLocalError("Frame text is required before lock.");
      return;
    }

    const costs = RISK_POSTURES[frameDraft.risk_posture];
    const framePayload = buildFramePayloadFromDraft(frameDraft);
    framePayload.text = text;
    const assistAcceptances = await transitionAssistDispositions((target) =>
      assistTargetTextFromFramePayload(target, framePayload as Record<string, unknown>),
    );
    if (assistAcceptances === null) {
      return;
    }

    const locked = await lockOperatorFrame({
      family,
      governance: { c_fp: costs.c_fp, c_fn: costs.c_fn },
      frame: framePayload as EngineFrame & { text: string },
      assist_acceptances: assistAcceptances,
    });
    if (!locked) {
      return;
    }
    if (isPhaseRejection(locked)) {
      const rejection = phaseRejectionMessage(locked) ?? "Frame lock refused by service phase gate.";
      setLocalError(rejection);
      pushFrameMessage("nepsis", rejection);
      return;
    }

    const sessionId = locked.session.session_id;
    const resultingFrame = locked.session.frame;
    const resolvedBranchId = locked.session.branch_id ?? `${sessionBranchContext(sessionId)}-b1`;
    const timelineMeta: FrameTimelineMeta = {
      branchId: resolvedBranchId,
      parentFrameId: locked.session.parent_frame_id ?? null,
      lineageVersion: locked.session.lineage_version ?? undefined,
    };
    setActiveBranchId(resolvedBranchId);
    setBranchCounter(parseBranchCounter(resolvedBranchId));
    setPendingBranchParentFrameId(locked.session.parent_frame_id ?? null);
    pushFrameMessage("nepsis", `Frame locked on operator session ${shortSession(sessionId)}.`);
    await refreshPackets(sessionId);

    setFrameLocked(true);
    setFrameCollapsed(true);
    clearRecordedAssistReviews(FRAME_ASSIST_TARGETS);
    resetDownstreamStages();
    setPendingBranchParentFrameId(null);
    await refreshSessions();
    const auditAfterLock = await requestBackendStageAudit({
      sessionId,
      mode: "canonical",
    });
    if (resultingFrame) {
      appendFrameTimeline(sessionId, resultingFrame, "Frame locked", {
        ...timelineMeta,
        audit: auditAfterLock ?? auditForAction ?? lastAudit,
      });
      setNextFrameDraft(hydrateNextFrameDraft(resultingFrame));
    }
    await persistWorkspaceState(
      {
        frame_locked: true,
        report_locked: false,
        report_corpus: "",
        report_input: "",
        last_evaluated_report_text: "",
        contradictions_status: "unreviewed",
        contradictions_note: "",
        threshold_decision: "undecided",
        threshold_hold_reason: "",
        report_result: null,
        stage_audit_context: {
          frame: frameGate.packet as unknown as Record<string, unknown>,
        },
      },
      sessionId,
    );
  }

  async function handleUnlockFrame() {
    clearAllErrors();
    if (activeSession) {
      const abandoned = await abandonOperatorSession({ reason: "Frame unlocked before commit." });
      if (abandoned) {
        const nextBranchId = abandoned.session.branch_id ?? `${sessionBranchContext(abandoned.session_id)}-b1`;
        setBranchCounter(parseBranchCounter(nextBranchId));
        setActiveBranchId(nextBranchId);
        setPendingBranchParentFrameId(abandoned.session.parent_frame_id ?? null);
        pushFrameMessage(
          "nepsis",
          `Frame unlocked for edits. The previous operator loop was abandoned and ${shortSession(abandoned.session_id)} is ready.`,
        );
      }
    } else {
      pushFrameMessage(
        "nepsis",
        "Frame unlocked for edits. Downstream stages were reset. Next lock creates a new frame version.",
      );
    }
    setFrameLocked(false);
    setFrameCollapsed(false);
    resetDownstreamStages();
    void persistWorkspaceState({
      frame_locked: false,
      report_locked: false,
      report_corpus: "",
      report_input: "",
      last_evaluated_report_text: "",
      contradictions_status: "unreviewed",
      contradictions_note: "",
      threshold_decision: "undecided",
      threshold_hold_reason: "",
      report_result: null,
      stage_audit_context: {},
    });
  }

  async function handleRunReport() {
    clearAllErrors();
    if (reportLocked) {
      setLocalError("Unlock Report before running a new evaluation.");
      return;
    }
    if (!frameLocked) {
      setLocalError("Lock Frame first.");
      return;
    }
    if (!activeSession) {
      setLocalError("No active session. Lock Frame to create or open a session.");
      return;
    }

    const signResult = deriveSignFromNarrative(activeSession.family, reportDraftText);
    if (!signResult.sign) {
      setLocalError(signResult.error ?? "Could not build report sign payload.");
      return;
    }

    const evaluatedReportText = reportDraftText.trim();
    const reportRun = await runOperatorReport({
      report_text: evaluatedReportText,
      sign: signResult.sign,
      interpretation: {
        report_text: evaluatedReportText,
        evidence_count: parseLineList(evaluatedReportText).length,
        report_synced: true,
        contradictions_status: contradictionsStatus,
        contradictions_note: contradictionsNote,
      },
    });
    if (!reportRun) {
      return;
    }
    if (isPhaseRejection(reportRun)) {
      const rejection = phaseRejectionMessage(reportRun) ?? "Report run refused by service phase gate.";
      setLocalError(rejection);
      pushReportMessage("nepsis", rejection);
      return;
    }
    const result = reportRun.step;
    if (!result) {
      setLocalError("Operator report did not return a step result.");
      return;
    }
    const evaluatedInterpretationGate = evaluateInterpretationGate({
      reportText: evaluatedReportText,
      posteriorHypotheses: Object.keys(result.posterior ?? {}),
      evidenceCount: parseLineList(evaluatedReportText).length,
      reportSynced: true,
      contradictionsStatus,
      contradictionsNote,
      contradictionDensity: result.governance?.contradiction_density ?? null,
    });
    const evaluatedThresholdGate = evaluateThresholdGate({
      posteriorHypotheses: Object.keys(result.posterior ?? {}),
      lossTreat: result.governance?.loss_treat,
      lossNotTreat: result.governance?.loss_notreat,
      warningLevel: result.governance?.warning_level ?? null,
      gateCrossed:
        result.governance?.p_bad != null && result.governance?.theta != null
          ? result.governance.p_bad >= result.governance.theta
          : null,
      recommendation: result.governance?.recommended_action ?? result.decision,
      decision: "undecided",
      holdReason: "",
    });
    const interpretationCoachAfterEval = buildInterpretationCoach(evaluatedInterpretationGate);
    const thresholdCoachAfterEval = buildThresholdCoach(evaluatedThresholdGate);
    const audit =
      reportRun.audit ??
      (await requestBackendStageAudit({
        sessionId: result.session.session_id,
        mode: "preview",
        overrides: {
          interpretation: {
            ...evaluatedInterpretationGate.packet,
          },
          threshold: {
            ...evaluatedThresholdGate.packet,
            decision: "undecided",
            hold_reason: "",
          },
        },
      }));

    const persistedStageContext: StageAuditContextOverrides = {
      frame: frameGate.packet as unknown as Record<string, unknown>,
      interpretation: evaluatedInterpretationGate.packet as unknown as Record<string, unknown>,
      threshold: {
        ...(evaluatedThresholdGate.packet as unknown as Record<string, unknown>),
        decision: "undecided",
        hold_reason: "",
      },
    };
    setReportResult(result);
    setLastEvaluatedReportText(evaluatedReportText);
    setThresholdDecision("undecided");
    setThresholdHoldReason("");
    if (optionalText(reportInput)) {
      pushReportMessage("human", reportInput.trim());
      setReportCorpus((prev) => (prev ? `${prev}\n${reportInput.trim()}` : reportInput.trim()));
      setReportInput("");
    }
    pushReportMessage(
      "nepsis",
      coachMessage(selectCoach("interpretation", interpretationCoachAfterEval, audit ?? lastAudit)),
    );
    pushPosteriorMessage(
      "nepsis",
      coachMessage(selectCoach("threshold", thresholdCoachAfterEval, audit ?? lastAudit)),
    );
    await persistWorkspaceState(
      {
        frame_locked: true,
        report_locked: false,
        report_corpus: evaluatedReportText,
        report_input: "",
        last_evaluated_report_text: evaluatedReportText,
        contradictions_status: contradictionsStatus,
        contradictions_note: contradictionsNote,
        threshold_decision: "undecided",
        threshold_hold_reason: "",
        report_result: result,
        stage_audit_context: persistedStageContext,
      },
      result.session.session_id,
    );
    await refreshPackets(result.session.session_id);
    await refreshSessions();
  }

  async function handleLockReport() {
    clearAllErrors();
    const auditForAction = await requestBackendStageAudit({ mode: "preview" });
    const interpretationActionStatus =
      normalizeGateStatus(auditForAction?.interpretation?.status) ?? displayInterpretationGateStatus;
    if (!reportResult) {
      setLocalError("Run CALL + REPORT before locking this stage.");
      pushReportMessage(
        "nepsis",
        coachMessage(selectCoach("interpretation", interpretationCoach, auditForAction ?? lastAudit)),
      );
      return;
    }
    if (interpretationActionStatus !== "PASS") {
      setLocalError(
        `Interpretation gate blocked: ${gateMissingTextForStage("interpretation", interpretationGateView, auditForAction ?? lastAudit)}`,
      );
      pushReportMessage(
        "nepsis",
        coachMessage(selectCoach("interpretation", interpretationCoach, auditForAction ?? lastAudit)),
      );
      return;
    }
    const locked = await lockOperatorReport();
    if (!locked) {
      return;
    }
    if (isPhaseRejection(locked)) {
      const rejection = phaseRejectionMessage(locked) ?? "Report lock refused by service phase gate.";
      setLocalError(rejection);
      pushReportMessage("nepsis", rejection);
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
    await persistWorkspaceState({
      report_locked: true,
      stage_audit_context: {
        frame: frameGate.packet as unknown as Record<string, unknown>,
        interpretation: interpretationGate.packet as unknown as Record<string, unknown>,
        threshold: {
          ...(thresholdGate.packet as unknown as Record<string, unknown>),
          decision: thresholdDecision,
          hold_reason: thresholdHoldReason,
        },
      },
    });
  }

  function handleUnlockReport() {
    clearAllErrors();
    setReportLocked(false);
    pushReportMessage("nepsis", "Report unlocked for more testing. Threshold stage will require a new pass.");
    void persistWorkspaceState({ report_locked: false });
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
    const auditForAction = await requestBackendStageAudit({ mode: "preview" });
    const thresholdActionStatus =
      normalizeGateStatus(auditForAction?.threshold?.status) ?? displayThresholdGateStatus;
    if (thresholdActionStatus !== "PASS") {
      setLocalError(
        `Threshold gate blocked: ${gateMissingTextForStage("threshold", thresholdGateView, auditForAction ?? lastAudit)}`,
      );
      pushPosteriorMessage(
        "nepsis",
        coachMessage(selectCoach("threshold", thresholdCoach, auditForAction ?? lastAudit)),
      );
      return;
    }
    if (thresholdDecision === "undecided") {
      setLocalError("Choose recommend action or hold before committing.");
      return;
    }
    const thresholdAssistTargets = new Set<OperatorAssistTarget>(["threshold.hold_reason"]);
    const thresholdAssistAcceptances = await transitionAssistDispositions((target) =>
      target === "threshold.hold_reason" ? thresholdHoldReason : null,
    );
    if (thresholdAssistAcceptances === null) {
      return;
    }
    const thresholdSet = await setOperatorThresholdDecision({
      decision: thresholdDecision,
      hold_reason: thresholdHoldReason,
      assist_acceptances: thresholdAssistAcceptances,
    });
    if (!thresholdSet) {
      return;
    }
    if (isPhaseRejection(thresholdSet)) {
      const rejection = phaseRejectionMessage(thresholdSet) ?? "Threshold decision refused by service phase gate.";
      setLocalError(rejection);
      pushPosteriorMessage("nepsis", rejection);
      return;
    }
    const reviewsAfterThreshold = assistReviews.filter(
      (review) => review.uiStatus !== "rejected" && !thresholdAssistTargets.has(review.target),
    );
    clearRecordedAssistReviews(thresholdAssistTargets);
    const payload = buildNextFramePayload(nextFrameDraft);
    if (!payload.text) {
      setLocalError("Next-frame text is required to commit.");
      return;
    }
    const commitAssistAcceptances = await transitionAssistDispositions(
      (target) => (target === "next_frame.text" && typeof payload.text === "string" ? payload.text : null),
      reviewsAfterThreshold,
    );
    if (commitAssistAcceptances === null) {
      return;
    }

    const committed = await commitOperatorIteration({
      carry_forward_frame: payload,
      assist_acceptances: commitAssistAcceptances,
    });
    if (!committed) {
      return;
    }
    if (isPhaseRejection(committed)) {
      const rejection = phaseRejectionMessage(committed) ?? "Iteration commit refused by service phase gate.";
      setLocalError(rejection);
      pushPosteriorMessage("nepsis", rejection);
      return;
    }

    const updatedFrame = committed.session.frame;
    if (!updatedFrame) {
      setLocalError("Committed operator session did not return a carry-forward frame.");
      return;
    }
    const resolvedBranchId = committed.session.branch_id ?? activeBranchId;
    appendFrameTimeline(activeSession.session_id, updatedFrame, "Committed to next priors", {
      branchId: resolvedBranchId,
      parentFrameId: committed.session.parent_frame_id ?? pendingBranchParentFrameId,
      lineageVersion: committed.session.lineage_version ?? undefined,
      audit: committed.audit ?? auditForAction ?? lastAudit,
    });
    setActiveBranchId(resolvedBranchId);
    setBranchCounter(parseBranchCounter(resolvedBranchId));
    setFrameDraft((prev) => ({
      ...prev,
      text: updatedFrame.text,
      objective_type: updatedFrame.objective_type,
      domain: updatedFrame.domain ?? "",
      time_horizon: updatedFrame.time_horizon ?? "",
      key_uncertainty:
        readRationaleSegment(updatedFrame.rationale_for_change, "Uncertainty") || prev.key_uncertainty,
      constraints_hard_text: lineListToText(updatedFrame.constraints_hard),
      constraints_soft_text: lineListToText(updatedFrame.constraints_soft),
      red_definition: readRationaleSegment(updatedFrame.rationale_for_change, "Red channel") || prev.red_definition,
      blue_goals: readRationaleSegment(updatedFrame.rationale_for_change, "Blue channel") || prev.blue_goals,
    }));
    setNextFrameDraft(hydrateNextFrameDraft(updatedFrame));
    setAssistReviews([]);
    setActiveAssistTarget(null);
    setEditingAssistId(null);
    setFrameLocked(false);
    setFrameCollapsed(false);
    resetDownstreamStages();
    setPendingBranchParentFrameId(null);
    pushPosteriorMessage("nepsis", "Iteration committed. Priors stage reopened for the next cycle.");
    pushFrameMessage("nepsis", `Frame v${updatedFrame.frame_version} is now the working prior.`);
    await persistWorkspaceState(
      {
        frame_locked: false,
        report_locked: false,
        report_corpus: "",
        report_input: "",
        last_evaluated_report_text: "",
        contradictions_status: "unreviewed",
        contradictions_note: "",
        threshold_decision: "undecided",
        threshold_hold_reason: "",
        report_result: null,
        stage_audit_context: {},
      },
      activeSession.session_id,
    );
    await refreshSessions();
    await requestBackendStageAudit({
      sessionId: activeSession.session_id,
      mode: "canonical",
    });
  }

  const mergedError = localError ?? error;
  const backendStatusLabel =
    healthy == null
      ? "checking backend"
      : healthy
        ? "reachable"
        : mergedError?.includes("NEPSIS_API_BASE_URL")
          ? "not configured"
          : "unreachable";
  const backendStatusTone =
    healthy == null
      ? "text-yellow-300"
      : healthy
        ? "text-green-400"
        : mergedError?.includes("NEPSIS_API_BASE_URL")
          ? "text-amber-300"
          : "text-red-400";
  const backendHelpMessage =
    healthy === false
      ? mergedError ??
        "Engine backend is unreachable. Start the Nepsis API server or set NEPSIS_API_BASE_URL for this deployment."
      : null;
  const activeStage = activeSession?.stage ?? "none";
  const backendAuditSource = lastAudit
    ? lastAudit.source.context_applied
      ? lastAudit.source.context_source === "session"
        ? "saved session context"
        : "preview context"
      : "canonical session"
    : "n/a";
  const engineAccessLabel =
    authSession == null
      ? "checking access"
      : authSession.engineControlAllowed
        ? authSession.user
          ? `signed in as ${authSession.user}`
          : "anonymous access enabled"
        : "sign in required";
  const llmKeyLabel =
    hasConnectedKey == null ? "checking key" : hasConnectedKey ? "browser key stored" : "no browser key";
  const whyNotConverging = useMemo(
    () => governance?.why_not_converging ?? [],
    [governance?.why_not_converging],
  );
  const topInterpretation = posteriorRows[0] ?? null;
  const secondInterpretation = posteriorRows[1] ?? null;
  const topMargin =
    topInterpretation && secondInterpretation ? Math.max(0, topInterpretation[1] - secondInterpretation[1]) : null;
  const finalDecisionBrief = useMemo(() => {
    if (
      !reportResult ||
      displayFrameGateStatus !== "PASS" ||
      displayInterpretationGateStatus !== "PASS" ||
      displayThresholdGateStatus !== "PASS"
    ) {
      return null;
    }
    const evidence = parseLineList(lastEvaluatedReportText || reportDraftText).slice(0, 4);
    const decisionLabel =
      thresholdDecision === "hold"
        ? "Hold for clarification"
        : thresholdDecision === "recommend"
          ? "Recommend action"
          : "Undecided";
    return {
      decisionLabel,
      frame: frameDraft.text || "n/a",
      redBoundary: frameDraft.red_definition || "n/a",
      topInterpretation: topInterpretation?.[0] ?? "n/a",
      topWeight: formatPct(topInterpretation?.[1]),
      warningLevel: governance?.warning_level ?? "n/a",
      recommendedAction: governance?.recommended_action ?? reportResult.decision,
      rationale:
        thresholdDecision === "hold"
          ? thresholdHoldReason || "Hold selected; clarification rationale is not specified."
          : `Proceed with ${governance?.recommended_action ?? reportResult.decision}.`,
      evidence,
      nextDiscriminator:
        whyNotConverging[0]?.next_discriminator ||
        thresholdHoldReason ||
        "Monitor for new evidence that changes the red boundary or posterior.",
    };
  }, [
    displayFrameGateStatus,
    displayInterpretationGateStatus,
    displayThresholdGateStatus,
    frameDraft.red_definition,
    frameDraft.text,
    governance?.recommended_action,
    governance?.warning_level,
    lastEvaluatedReportText,
    reportDraftText,
    reportResult,
    thresholdDecision,
    thresholdHoldReason,
    topInterpretation,
    whyNotConverging,
  ]);
  const showReportPanel = showOperatorControls || currentStageStep >= 2;
  const showPosteriorPanel = showOperatorControls || currentStageStep >= 3;
  const showTimeline = showOperatorControls || currentStageStep >= 3;

  const selectedTimeline = compactTimeline.find((item) => item.id === selectedTimelineId) ?? null;
  const selectedPacket = selectedTimeline?.event
    ? asRecord(packets[selectedTimeline.event.packetIndex])
    : null;
  const selectedPacketMeta = asRecord(selectedPacket?.meta);
  const selectedPacketId =
    readString(selectedPacketMeta?.packet_id) ??
    readString(selectedPacket?.packet_id) ??
    selectedTimeline?.event?.packetId ??
    null;
  const selectedProvenance = provenanceForPacket(provenance?.records, selectedPacketId);
  const selectedPacketResult = asRecord(selectedPacket?.result);
  const selectedPacketState = asRecord(selectedPacket?.state);
  const selectedPacketCarry = asRecord(selectedPacket?.carry_forward);

  function assistButton(target: OperatorAssistTarget, label: string, disabled = false) {
    const busy = modelAssistBusy && activeAssistTarget === target;
    return (
      <button
        type="button"
        aria-label={`Assist ${label}`}
        onClick={() => void requestFieldAssist(target)}
        disabled={disabled || modelAssistBusy}
        className="mt-1 rounded-full border border-nepsis-border px-2 py-0.5 text-[11px] text-nepsis-muted hover:border-nepsis-accent hover:text-nepsis-text disabled:opacity-50"
      >
        {busy ? "Working..." : `Assist ${label}`}
      </button>
    );
  }

  function assistReviewPanel() {
    if (!liveOperatorSurface || (!modelAssistOpen && assistReviews.length === 0)) {
      return null;
    }
    return (
      <section
        id="operator-assist-review"
        className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4"
      >
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Model Assist Review</h2>
            <p className="text-xs text-nepsis-muted">
              Field suggestions stay advisory until accepted, edited, or rejected.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setModelAssistOpen(false)}
            className="rounded-full border border-nepsis-border px-2 py-0.5 text-xs hover:border-nepsis-accent"
          >
            Hide
          </button>
        </div>
        {assistReviews.length === 0 ? (
          <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs text-nepsis-muted">
            No model suggestions waiting for review.
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {assistReviews.map((review) => {
              const editing = editingAssistId === review.id;
              const value = review.editedValue ?? canonicalFieldText(review.proposedValue);
              return (
                <div key={review.id} className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <div className="font-semibold text-nepsis-text">{review.title}</div>
                      <div className="mt-1 text-nepsis-muted">
                        {targetLabel(review.target)} · {review.uiStatus}
                      </div>
                    </div>
                    <span className="rounded-full border border-nepsis-border px-2 py-0.5 text-[11px] text-nepsis-muted">
                      {review.model}
                    </span>
                  </div>
                  {editing ? (
                    <textarea
                      aria-label="Edit suggestion"
                      className="mt-2 w-full rounded-lg border border-nepsis-border bg-black/30 p-2 text-nepsis-text"
                      rows={4}
                      value={value}
                      onChange={(event) => editAssist(review.id, event.target.value)}
                    />
                  ) : (
                    <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg border border-nepsis-border bg-black/30 p-2 text-nepsis-text">
                      {value}
                    </pre>
                  )}
                  {review.rationale ? <div className="mt-2 text-nepsis-muted">{review.rationale}</div> : null}
                  {review.riskNote ? <div className="mt-1 text-amber-300">{review.riskNote}</div> : null}
                  <div className="mt-3 flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => applyAssist(review)}
                      disabled={review.uiStatus !== "draft"}
                      className="rounded-full bg-nepsis-accent px-3 py-1 text-xs font-semibold text-black disabled:opacity-50"
                    >
                      Accept suggestion
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingAssistId(review.id)}
                      disabled={review.uiStatus !== "draft"}
                      className="rounded-full border border-nepsis-border px-3 py-1 text-xs text-nepsis-muted hover:border-nepsis-accent disabled:opacity-50"
                    >
                      Edit before accepting
                    </button>
                    <button
                      type="button"
                      onClick={() => rejectAssist(review.id)}
                      disabled={review.uiStatus !== "draft"}
                      className="rounded-full border border-nepsis-border px-3 py-1 text-xs text-nepsis-muted hover:border-nepsis-accent disabled:opacity-50"
                    >
                      Reject
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>
    );
  }

  const publicMode = publicSiteMode();

  if (publicMode && authSession === null) {
    return <OperatorAccessNotice checking />;
  }

  if (publicMode && authSession && !authSession.engineControlAllowed) {
    return <OperatorAccessNotice />;
  }

  return (
    <div className="mx-auto flex w-full max-w-[1850px] flex-col gap-4 px-4 py-6">
      <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold">
              {liveOperatorSurface ? "Live Operator Workspace" : "Nepsis Engine Workspace"}
            </h1>
            {liveOperatorSurface && (
              <span className="mt-2 inline-flex rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-amber-100">
                Live mode
              </span>
            )}
            <p className="mt-1 max-w-3xl text-sm text-nepsis-muted">
              Guided flow: <span className="font-medium text-nepsis-text">{audienceLabels.stage1}</span> →{" "}
              <span className="font-medium text-nepsis-text">{audienceLabels.stage2}</span> →{" "}
              <span className="font-medium text-nepsis-text">{audienceLabels.stage3}</span>.
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
              onClick={() => setAudienceMode((prev) => (prev === "public" ? "research" : "public"))}
              className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
            >
              Audience: {audienceMode === "public" ? "Public" : "Research"}
            </button>

            <button
              onClick={() => setSandboxOpen(true)}
              className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
            >
              Model Sandbox
            </button>
            {liveOperatorSurface && (
              <button
                onClick={() => setModelAssistOpen(true)}
                className="rounded-full border border-amber-500/50 px-3 py-1.5 text-xs text-amber-100 hover:border-amber-300"
              >
                Model Assist
              </button>
            )}
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
              <span className={backendStatusTone}>{healthy === null ? "unknown" : backendStatusLabel}</span>
            </div>
            <div>active session: {activeSession ? shortSession(activeSession.session_id) : "none"}</div>
            <div>stage: {activeStage}</div>
            <div>packets: {packets.length}</div>
            <div>frame locked: {frameLocked ? "yes" : "no"}</div>
            <div>report locked: {reportLocked ? "yes" : "no"}</div>
            <div>branch: {activeBranchId}</div>
            <div>lineage: {activeSession?.lineage_version ?? latestSessionFrameEntry?.lineageVersion ?? "n/a"}</div>
            <div>frame gate: {displayFrameGateStatus}</div>
            <div>interpretation gate: {displayInterpretationGateStatus}</div>
            <div>threshold gate: {displayThresholdGateStatus}</div>
            <div>backend audit frame: {lastAudit?.frame.status ?? "n/a"}</div>
            <div>backend audit interpretation: {lastAudit?.interpretation.status ?? "n/a"}</div>
            <div>backend audit threshold: {lastAudit?.threshold.status ?? "n/a"}</div>
            <div>backend audit policy: {lastAudit ? `${lastAudit.policy.name}@${lastAudit.policy.version}` : "n/a"}</div>
            <div>backend audit source: {backendAuditSource}</div>
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
              <div>branch: {activeBranchId}</div>
              <div>backend audit: {lastAudit ? `${lastAudit.frame.status}/${lastAudit.interpretation.status}/${lastAudit.threshold.status}` : "not run"}</div>
              <div>audit policy: {lastAudit ? `${lastAudit.policy.name}@${lastAudit.policy.version}` : "n/a"}</div>
              <div>audit source: {backendAuditSource}</div>
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
              <button
                onClick={() => void requestBackendStageAudit({ mode: "canonical" })}
                disabled={loading || !activeSession}
                className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent disabled:opacity-60"
              >
                Canonical Audit
              </button>
            </div>
          </div>
        )}

        {showConnectedNotice && (
          <div className="mt-3 flex items-center justify-between gap-3 rounded-lg border border-green-500/40 bg-green-500/10 px-3 py-2 text-xs text-green-200">
            <span>LLM connected. Your workspace is ready for live model calls.</span>
            <button
              onClick={() => setShowConnectedNotice(false)}
              className="rounded-full border border-green-500/50 px-2 py-0.5 text-[11px] hover:border-green-400"
            >
              Dismiss
            </button>
          </div>
        )}

        {userMode && (
          <div className="mt-3 grid gap-2 md:grid-cols-3">
            <div className="rounded-lg border border-nepsis-border bg-black/20 px-3 py-2 text-xs">
              <div className="text-nepsis-muted">Engine backend</div>
              <div className="mt-1 text-nepsis-text">{backendStatusLabel}</div>
            </div>
            <div className="rounded-lg border border-nepsis-border bg-black/20 px-3 py-2 text-xs">
              <div className="text-nepsis-muted">Session access</div>
              <div className="mt-1 text-nepsis-text">{engineAccessLabel}</div>
            </div>
            <div className="rounded-lg border border-nepsis-border bg-black/20 px-3 py-2 text-xs">
              <div className="text-nepsis-muted">Model sandbox</div>
              <div className="mt-1 text-nepsis-text">{llmKeyLabel}</div>
            </div>
          </div>
        )}

        {userMode && healthy === false && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-100">
            <span>{backendHelpMessage}</span>
          </div>
        )}

        {userMode && authSession != null && !authSession.engineControlAllowed && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
            <span>Engine session controls are locked until you sign in. Backend health can still be checked without a session.</span>
            <a href="/login" className="rounded-full border border-amber-400/50 px-3 py-1 hover:border-amber-300">
              Sign In
            </a>
          </div>
        )}

        {userMode && hasConnectedKey === false && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
            <span>OpenAI browser keys are local-demo only. Use server-side API key configuration for shared deployments.</span>
            <a href="/settings" className="rounded-full border border-amber-400/50 px-3 py-1 hover:border-amber-300">
              Open Model Settings
            </a>
          </div>
        )}

        {userMode && (
          <>
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              <span
                className={`rounded-full border px-3 py-1 ${
                  currentStageStep === 1
                    ? "border-nepsis-accent bg-nepsis-accent/10 text-nepsis-text"
                    : "border-nepsis-border text-nepsis-muted"
                }`}
              >
                1. {audienceLabels.stage1} · {displayFrameGateStatus}
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
                2. {audienceLabels.stage2} · {displayInterpretationGateStatus}
              </span>
              <span
                className={`rounded-full border px-3 py-1 ${
                  currentStageStep === 3
                    ? "border-nepsis-accent bg-nepsis-accent/10 text-nepsis-text"
                    : "border-nepsis-border text-nepsis-muted"
                }`}
              >
                3. {audienceLabels.stage3} · {displayThresholdGateStatus}
              </span>
            </div>
            <div className="mt-3 rounded-lg border border-nepsis-border bg-black/20 p-2">
              <div className="mb-2 text-[11px] text-nepsis-muted">Process pipeline</div>
              <div className="flex flex-wrap gap-2 text-[11px]">
                {processSteps.map((stepItem) => (
                  <span
                    key={stepItem.label}
                    className={`rounded-full border px-2 py-0.5 ${pipelineStateClass(stepItem.state)}`}
                  >
                    {stepItem.label}
                  </span>
                ))}
              </div>
            </div>
          </>
        )}
      </section>

      {mergedError && (
        <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-200">
          {mergedError}
        </div>
      )}

      {assistReviewPanel()}

      {(unresolvedBlocks.length > 0 || unresolvedWarnings.length > 0) && (
        <section
          className={`rounded-xl border px-3 py-3 text-xs ${
            unresolvedBlocks.length > 0
              ? "border-red-500/40 bg-red-500/10 text-red-100"
              : "border-amber-500/40 bg-amber-500/10 text-amber-100"
          }`}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Not Ready</h3>
            <span className="rounded-full border border-current/40 px-2 py-0.5 text-[11px]">
              blocks: {unresolvedBlocks.length} · warnings: {unresolvedWarnings.length}
            </span>
          </div>
          {unresolvedBlocks.length > 0 && (
            <div className="mt-2 space-y-1">
              <div className="text-red-200">Progression is blocked until these checks pass:</div>
              {unresolvedBlocks.map((item) => (
                <button
                  key={item.key}
                  onClick={() => jumpToUnresolvedCheck(item)}
                  className="w-full rounded border border-red-500/30 bg-red-500/10 px-2 py-1 text-left hover:border-red-300"
                >
                  <div>
                    <span className="font-medium">{item.stage}</span>: {item.label}
                  </div>
                  <div className="text-[11px] text-red-100">{item.detail}</div>
                  <div className="mt-1 text-[10px] text-red-200/90 underline">Jump to check</div>
                </button>
              ))}
            </div>
          )}
          {unresolvedWarnings.length > 0 && (
            <div className={`mt-2 space-y-1 ${unresolvedBlocks.length > 0 ? "text-red-100" : "text-amber-100"}`}>
              <div>Non-blocking warnings:</div>
              {unresolvedWarnings.map((item) => (
                <button
                  key={item.key}
                  onClick={() => jumpToUnresolvedCheck(item)}
                  className="w-full rounded border border-current/20 bg-black/20 px-2 py-1 text-left hover:border-current/50"
                >
                  <div>
                    <span className="font-medium">{item.stage}</span>: {item.label}
                  </div>
                  <div className="text-[11px] opacity-90">{item.detail}</div>
                  <div className="mt-1 text-[10px] underline">Jump to check</div>
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      <div className={`grid gap-4 ${userMode ? "grid-cols-1" : "2xl:grid-cols-3"}`}>
        <section
          id="stage-frame"
          tabIndex={-1}
          className={`flex ${panelHeightClass} flex-col rounded-2xl border border-nepsis-border bg-nepsis-panel p-4`}
        >
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">1) {audienceLabels.stage1}</h2>
              <p className="text-xs text-nepsis-muted">{audienceLabels.stage1Subtitle}</p>
            </div>
            <div className="flex items-center gap-2">
              <span className={`rounded-full border px-2 py-0.5 text-[11px] ${gateBadgeClass(displayFrameGateStatus)}`}>
                Frame Gate: {displayFrameGateStatus}
              </span>
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
          <div className="mb-3 rounded-lg border border-nepsis-border bg-black/20 px-3 py-2 text-[11px]">
            <div className="text-nepsis-muted">Gate requirements</div>
            <div className={`mt-1 ${gateTextClass(displayFrameGateStatus)}`}>{gateMissingText(frameGateView)}</div>
            <div className="mt-2 rounded border border-nepsis-border bg-black/20 p-2">
              <div className="text-nepsis-muted">Nepsis stage coach</div>
                <div className={`mt-1 ${gateTextClass(displayFrameGateStatus)}`}>{displayFrameCoach.summary}</div>
              {displayFrameCoach.prompts.length > 0 && (
                <div className="mt-1 space-y-1 text-nepsis-text">
                  {displayFrameCoach.prompts.map((prompt, idx) => (
                    <div key={`${idx}-${prompt}`}>- {prompt}</div>
                  ))}
                </div>
              )}
            </div>
            {showOperatorControls && (
              <pre className="mt-2 max-h-24 overflow-auto rounded border border-nepsis-border bg-black/30 p-2 text-[10px] text-nepsis-muted">
                {JSON.stringify(frameGateView.packet, null, 2)}
              </pre>
            )}
          </div>

          {userMode && frameLocked && frameCollapsed ? (
            <div className="flex-1 space-y-3">
              <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                <div className="text-nepsis-muted">Frame summary</div>
                <div className="mt-1 text-nepsis-text">{frameDraft.text || "(no frame text yet)"}</div>
                <div className="mt-2 grid grid-cols-2 gap-2 text-nepsis-muted">
                  <div>objective: {frameDraft.objective_type || "n/a"}</div>
                  <div>domain: {frameDraft.domain || "n/a"}</div>
                  <div>hard: {frameHardConstraints.length}</div>
                  <div>soft: {frameSoftConstraints.length}</div>
                  <div>uncertainty: {frameDraft.key_uncertainty || "n/a"}</div>
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
                    {formatMessageTime(message.at) && (
                      <span className="text-nepsis-muted"> · {formatMessageTime(message.at)}</span>
                    )}
                    <div className="mt-0.5 whitespace-pre-wrap text-nepsis-text">{message.text}</div>
                  </div>
                ))}
              </div>

              <div className="flex gap-2">
                <textarea
                  value={frameInput}
                  onChange={(event) => setFrameInput(event.target.value)}
                  rows={2}
                  placeholder={
                    userMode ? "Clarify goal, risks, and constraints before locking..." : "Discuss frame assumptions..."
                  }
                  className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                />
                <button
                  onClick={() => void handleSendFrameMessage()}
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
                  id="frame-problem-statement"
                  value={frameDraft.text}
                  onChange={(event) => setFrameDraft((prev) => ({ ...prev, text: event.target.value }))}
                  rows={3}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-sm"
                />
              </label>
              {liveOperatorSurface ? assistButton("frame.text", "Frame question", frameLocked) : null}

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
                    id="frame-decision-horizon"
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

              <label className="block text-xs text-nepsis-muted">
                Key uncertainty source
                <textarea
                  id="frame-key-uncertainty"
                  value={frameDraft.key_uncertainty}
                  onChange={(event) => setFrameDraft((prev) => ({ ...prev, key_uncertainty: event.target.value }))}
                  rows={2}
                  placeholder="What uncertainty could most change this decision?"
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                />
              </label>
              {liveOperatorSurface ? assistButton("frame.key_uncertainty", "Key uncertainty", frameLocked) : null}

              <div className="grid grid-cols-2 gap-2">
                <div className="block text-xs text-nepsis-muted">
                  <label htmlFor="frame-constraints-hard">Hard constraints (1/line)</label>
                  <textarea
                    id="frame-constraints-hard"
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
                  {liveOperatorSurface ? assistButton("frame.constraints_hard", "Hard constraints", frameLocked) : null}
                </div>
                <div className="block text-xs text-nepsis-muted">
                  <label htmlFor="frame-constraints-soft">Soft constraints (1/line)</label>
                  <textarea
                    id="frame-constraints-soft"
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
                  {liveOperatorSurface ? assistButton("frame.constraints_soft", "Soft constraints", frameLocked) : null}
                </div>
              </div>

              <label className="block text-xs text-nepsis-muted">
                Red channel definition
                <textarea
                  id="frame-catastrophic-outcome"
                  value={frameDraft.red_definition}
                  onChange={(event) => setFrameDraft((prev) => ({ ...prev, red_definition: event.target.value }))}
                  rows={2}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                />
              </label>
              {liveOperatorSurface ? assistButton("frame.red_definition", "RED channel definition", frameLocked) : null}
              <label className="block text-xs text-nepsis-muted">
                Blue channel goals
                <textarea
                  id="frame-optimization-goal"
                  value={frameDraft.blue_goals}
                  onChange={(event) => setFrameDraft((prev) => ({ ...prev, blue_goals: event.target.value }))}
                  rows={2}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                />
              </label>
              {liveOperatorSurface ? assistButton("frame.blue_goals", "BLUE channel goals", frameLocked) : null}

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
            <button
              type="button"
              onClick={() => highlightAndScroll(nextIncompleteFrameTarget(frameDraft))}
              className="rounded-full border border-nepsis-border px-3 py-1.5 text-xs text-nepsis-muted hover:border-nepsis-accent hover:text-nepsis-text"
            >
              Next box
            </button>
            {!frameLocked ? (
              <button
                onClick={() => void handleLockFrame()}
                disabled={loading || displayFrameGateStatus !== "PASS"}
                className="rounded-full bg-nepsis-accent px-4 py-2 text-xs font-semibold text-black disabled:opacity-60"
              >
                Lock Frame →
              </button>
            ) : (
              <button
                onClick={() => void handleUnlockFrame()}
                className="rounded-full border border-nepsis-border px-4 py-2 text-xs hover:border-nepsis-accent"
              >
                Unlock Frame
              </button>
            )}
          </div>
        </section>

        {showReportPanel && (
          <section
            id="stage-interpretation"
            tabIndex={-1}
            className={`flex ${panelHeightClass} flex-col rounded-2xl border border-nepsis-border bg-nepsis-panel p-4 ${
              !frameLocked ? "pointer-events-none opacity-50" : ""
            }`}
          >
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">2) {audienceLabels.stage2}</h2>
                <p className="text-xs text-nepsis-muted">{audienceLabels.stage2Subtitle}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className={`rounded-full border px-2 py-0.5 text-[11px] ${gateBadgeClass(displayInterpretationGateStatus)}`}>
                  Interpretation Gate: {displayInterpretationGateStatus}
                </span>
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
            </div>
            <div className="mb-3 rounded-lg border border-nepsis-border bg-black/20 px-3 py-2 text-[11px]">
              <div className="text-nepsis-muted">Gate requirements</div>
              <div className={`mt-1 ${gateTextClass(displayInterpretationGateStatus)}`}>{gateMissingText(interpretationGateView)}</div>
              <div className="mt-2 rounded border border-nepsis-border bg-black/20 p-2">
                <div className="text-nepsis-muted">Nepsis stage coach</div>
                <div className={`mt-1 ${gateTextClass(displayInterpretationGateStatus)}`}>{displayInterpretationCoach.summary}</div>
                {displayInterpretationCoach.prompts.length > 0 && (
                  <div className="mt-1 space-y-1 text-nepsis-text">
                    {displayInterpretationCoach.prompts.map((prompt, idx) => (
                      <div key={`${idx}-${prompt}`}>- {prompt}</div>
                    ))}
                  </div>
                )}
              </div>
              {showOperatorControls && (
                <pre className="mt-2 max-h-24 overflow-auto rounded border border-nepsis-border bg-black/30 p-2 text-[10px] text-nepsis-muted">
                  {JSON.stringify(interpretationGateView.packet, null, 2)}
                </pre>
              )}
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
                      {formatMessageTime(message.at) && (
                        <span className="text-nepsis-muted"> · {formatMessageTime(message.at)}</span>
                      )}
                      <div className="mt-0.5 whitespace-pre-wrap text-nepsis-text">{message.text}</div>
                    </div>
                  ))}
                </div>

                <div className="flex gap-2">
                  <textarea
                    id="report-input"
                    value={reportInput}
                    onChange={(event) => setReportInput(event.target.value)}
                    rows={3}
                    placeholder={
                      userMode ? "Add observations, tests, and contradictory evidence..." : "Observations, tests, contradictions..."
                    }
                    className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                  />
                  <button
                    onClick={() => void handleSendReportMessage()}
                    className="h-fit rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
                  >
                    Send
                  </button>
                </div>

                <div className="grid gap-2 md:grid-cols-2">
                  <label className="block text-xs text-nepsis-muted">
                    Contradiction status
                    <select
                      id="report-contradictions-status"
                      value={contradictionsStatus}
                      onChange={(event) =>
                        setContradictionsStatus(event.target.value as InterpretationContradictionsStatus)
                      }
                      className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                    >
                      <option value="unreviewed">unreviewed</option>
                      <option value="none_identified">none identified</option>
                      <option value="declared">declared</option>
                    </select>
                  </label>
                  <label className="block text-xs text-nepsis-muted">
                    Contradiction notes
                    <textarea
                      id="report-contradictions-note"
                      value={contradictionsNote}
                      onChange={(event) => setContradictionsNote(event.target.value)}
                      rows={2}
                      placeholder="Required when contradiction status is declared."
                      className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                    />
                  </label>
                </div>

                <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                  <div className="mb-1 text-nepsis-muted">CALL payload preview</div>
                  <pre className="max-h-40 overflow-auto text-[11px] text-nepsis-muted">
                    {JSON.stringify(
                      deriveSignFromNarrative(activeSession?.family ?? family, reportDraftText).sign,
                      null,
                      2,
                    )}
                  </pre>
                  <div className="mt-2 text-[11px] text-nepsis-muted">
                    Override extraction with explicit tags like <code>critical_signal:false</code> or{" "}
                    <code>policy_violation:false</code>.
                  </div>
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
                id="report-run-button"
                onClick={() => void handleRunReport()}
                disabled={loading || reportLocked}
                className="rounded-full bg-nepsis-accent px-4 py-2 text-xs font-semibold text-black disabled:opacity-60"
              >
                Run CALL + REPORT
              </button>
              {!reportLocked ? (
                <button
                  onClick={() => void handleLockReport()}
                  disabled={loading || displayInterpretationGateStatus !== "PASS"}
                  className="rounded-full border border-nepsis-border px-4 py-2 text-xs hover:border-nepsis-accent disabled:opacity-60"
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
            id="stage-threshold"
            tabIndex={-1}
            className={`flex ${panelHeightClass} flex-col rounded-2xl border border-nepsis-border bg-nepsis-panel p-4 ${
              !reportLocked ? "pointer-events-none opacity-50" : ""
            }`}
          >
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">3) {audienceLabels.stage3}</h2>
                <p className="text-xs text-nepsis-muted">{audienceLabels.stage3Subtitle}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className={`rounded-full border px-2 py-0.5 text-[11px] ${gateBadgeClass(displayThresholdGateStatus)}`}>
                  Threshold Gate: {displayThresholdGateStatus}
                </span>
                <span className="rounded-full border border-nepsis-border bg-black/20 px-2 py-0.5 text-[11px] text-nepsis-muted">
                  {reportLocked ? "Ready to commit" : "Locked"}
                </span>
              </div>
            </div>
            <div className="mb-3 rounded-lg border border-nepsis-border bg-black/20 px-3 py-2 text-[11px]">
              <div className="text-nepsis-muted">Gate requirements</div>
              <div className={`mt-1 ${gateTextClass(displayThresholdGateStatus)}`}>{gateMissingText(thresholdGateView)}</div>
              <div className="mt-2 rounded border border-nepsis-border bg-black/20 p-2">
                <div className="text-nepsis-muted">Nepsis stage coach</div>
                <div className={`mt-1 ${gateTextClass(displayThresholdGateStatus)}`}>{displayThresholdCoach.summary}</div>
                {displayThresholdCoach.prompts.length > 0 && (
                  <div className="mt-1 space-y-1 text-nepsis-text">
                    {displayThresholdCoach.prompts.map((prompt, idx) => (
                      <div key={`${idx}-${prompt}`}>- {prompt}</div>
                    ))}
                  </div>
                )}
              </div>
              {showOperatorControls && (
                <pre className="mt-2 max-h-24 overflow-auto rounded border border-nepsis-border bg-black/30 p-2 text-[10px] text-nepsis-muted">
                  {JSON.stringify(thresholdGateView.packet, null, 2)}
                </pre>
              )}
            </div>

            <div className="flex-1 space-y-3">
              <div className="h-24 overflow-auto rounded-lg border border-nepsis-border bg-black/20 p-2 text-xs">
                {posteriorChat.map((message) => (
                  <div key={message.id} className="mb-2">
                    <span className={message.role === "human" ? "text-nepsis-accent" : "text-nepsis-muted"}>
                      {message.role === "human" ? "You" : "Nepsis"}
                    </span>
                    {formatMessageTime(message.at) && (
                      <span className="text-nepsis-muted"> · {formatMessageTime(message.at)}</span>
                    )}
                    <div className="mt-0.5 whitespace-pre-wrap text-nepsis-text">{message.text}</div>
                  </div>
                ))}
              </div>

              <div className="flex gap-2">
                <textarea
                  value={posteriorInput}
                  onChange={(event) => setPosteriorInput(event.target.value)}
                  rows={2}
                  placeholder={userMode ? "Draft what should carry into the next frame..." : "Carry-forward discussion..."}
                  className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
                />
                <button
                  onClick={() => void handleSendPosteriorMessage()}
                  className="h-fit rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent"
                >
                  Send
                </button>
              </div>

              <div id="threshold-gate-metrics" className="grid gap-2 md:grid-cols-3">
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

              <div className="rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                <div className="mb-2 text-nepsis-muted">Threshold decision declaration</div>
                <div className="grid gap-2 md:grid-cols-2">
                  <label className="block text-nepsis-muted">
                    Decision
                    <select
                      id="threshold-decision-select"
                      value={thresholdDecision}
                      onChange={(event) => setThresholdDecision(event.target.value as ThresholdDecision)}
                      className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-nepsis-text"
                    >
                      <option value="undecided">undecided</option>
                      <option value="recommend">recommend action</option>
                      <option value="hold">hold for clarification</option>
                    </select>
                  </label>
                  <label className="block text-nepsis-muted">
                    Hold rationale
                    <textarea
                      id="threshold-hold-reason"
                      value={thresholdHoldReason}
                      onChange={(event) => setThresholdHoldReason(event.target.value)}
                      rows={2}
                      placeholder="Required when decision is hold."
                      className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-nepsis-text"
                    />
                    {liveOperatorSurface
                      ? assistButton("threshold.hold_reason", "Hold rationale", !reportLocked)
                      : null}
                  </label>
                </div>
              </div>

              {finalDecisionBrief && (
                <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-xs">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="font-semibold text-emerald-100">Final decision brief</div>
                    <span className="rounded-full border border-emerald-400/40 px-2 py-0.5 text-[11px] text-emerald-100">
                      PASS/PASS/PASS
                    </span>
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    <div>
                      <div className="text-nepsis-muted">Decision</div>
                      <div className="text-nepsis-text">{finalDecisionBrief.decisionLabel}</div>
                    </div>
                    <div>
                      <div className="text-nepsis-muted">Recommended action</div>
                      <div className="text-nepsis-text">{finalDecisionBrief.recommendedAction}</div>
                    </div>
                    <div>
                      <div className="text-nepsis-muted">Top interpretation</div>
                      <div className="text-nepsis-text">
                        {finalDecisionBrief.topInterpretation} · {finalDecisionBrief.topWeight}
                      </div>
                    </div>
                    <div>
                      <div className="text-nepsis-muted">Warning level</div>
                      <div className="text-nepsis-text">{finalDecisionBrief.warningLevel}</div>
                    </div>
                  </div>
                  <div className="mt-2 text-nepsis-muted">Frame</div>
                  <div className="text-nepsis-text">{finalDecisionBrief.frame}</div>
                  <div className="mt-2 text-nepsis-muted">Red boundary</div>
                  <div className="text-nepsis-text">{finalDecisionBrief.redBoundary}</div>
                  {finalDecisionBrief.evidence.length > 0 && (
                    <>
                      <div className="mt-2 text-nepsis-muted">Evidence used</div>
                      <ul className="list-inside list-disc space-y-0.5 text-nepsis-text">
                        {finalDecisionBrief.evidence.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  <div className="mt-2 text-nepsis-muted">Rationale</div>
                  <div className="text-nepsis-text">{finalDecisionBrief.rationale}</div>
                  <div className="mt-2 text-nepsis-muted">Next discriminator</div>
                  <div className="text-nepsis-text">{finalDecisionBrief.nextDiscriminator}</div>
                </div>
              )}

              <div id="threshold-posterior" className="rounded-lg border border-nepsis-border bg-black/20 p-3">
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
                  id="next-frame-text"
                  value={nextFrameDraft.text}
                  onChange={(event) => setNextFrameDraft((prev) => ({ ...prev, text: event.target.value }))}
                  rows={3}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5"
                />
              </label>
              {liveOperatorSurface ? assistButton("next_frame.text", "Next frame text", !reportLocked) : null}

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
                disabled={loading || displayThresholdGateStatus !== "PASS"}
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
            <h3 className="text-sm font-semibold">{audienceLabels.history}</h3>
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
                  <div className="text-nepsis-muted">Frame lineage detail</div>
                  <div className="font-mono text-nepsis-accent">
                    {selectedTimeline.frame.branchId} · L{selectedTimeline.frame.lineageVersion} · v
                    {selectedTimeline.frame.frameVersion}
                  </div>
                  <div className="grid gap-2 md:grid-cols-2">
                    <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                      parent: {selectedTimeline.frame.parentFrameId ?? "root"}
                    </div>
                    <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                      session: {shortSession(selectedTimeline.frame.sessionId)}
                    </div>
                    <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                      gates: frame={selectedTimeline.frame.gateFrameStatus}
                    </div>
                    <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                      gates: interpretation={selectedTimeline.frame.gateInterpretationStatus} / threshold=
                      {selectedTimeline.frame.gateThresholdStatus}
                    </div>
                  </div>
                  {selectedTimeline.frame.audit ? (
                    <div className="space-y-2">
                      <div className="grid gap-2 md:grid-cols-2">
                        <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                          audit stage: {selectedTimeline.frame.audit.stage}
                        </div>
                        <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                          audit policy: {selectedTimeline.frame.audit.policyName}@{selectedTimeline.frame.audit.policyVersion}
                        </div>
                        <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                          audit packet count: {selectedTimeline.frame.audit.sourcePacketCount}
                        </div>
                        <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                          audit packet id: {selectedTimeline.frame.audit.sourceLatestPacketId ?? "n/a"}
                        </div>
                        <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                          audit iteration: {selectedTimeline.frame.audit.sourceLatestIteration ?? "n/a"}
                        </div>
                        <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted md:col-span-2">
                          context applied: {selectedTimeline.frame.audit.contextApplied ? "yes" : "no"}
                        </div>
                      </div>
                      {showOperatorControls && (
                        <div className="grid gap-2 md:grid-cols-3">
                          <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                            frame coach: {selectedTimeline.frame.audit.frameCoachSummary}
                          </div>
                          <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                            interpretation coach: {selectedTimeline.frame.audit.interpretationCoachSummary}
                          </div>
                          <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                            threshold coach: {selectedTimeline.frame.audit.thresholdCoachSummary}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                      audit snapshot: unavailable (recorded before backend stage-audit integration)
                    </div>
                  )}
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
                  <div className="rounded border border-nepsis-border px-2 py-1.5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="text-nepsis-muted">Packet Provenance</div>
                      <button
                        type="button"
                        onClick={() => activeSession?.session_id && void refreshProvenance(activeSession.session_id)}
                        className="rounded-full border border-nepsis-border px-2 py-0.5 text-[11px] text-nepsis-muted hover:border-nepsis-accent hover:text-nepsis-text"
                      >
                        Refresh
                      </button>
                    </div>
                    {selectedProvenance ? (
                      <div className="mt-2 grid gap-2 md:grid-cols-3">
                        <div>
                          <div className="text-nepsis-muted">Packet</div>
                          <div className="font-mono text-nepsis-text">{selectedProvenance.packet_id}</div>
                        </div>
                        <div>
                          <div className="text-nepsis-muted">Parent</div>
                          <div className="font-mono text-nepsis-text">
                            {selectedProvenance.parent_packet_id ?? "root"}
                          </div>
                        </div>
                        <div>
                          <div className="text-nepsis-muted">Hash</div>
                          <div className="font-mono text-nepsis-text">
                            {shortHash(selectedProvenance.payload_hash)}
                          </div>
                        </div>
                        <div>
                          <div className="text-nepsis-muted">Signature</div>
                          <div className="text-nepsis-text">
                            {selectedProvenance.signature.algorithm}
                            {selectedProvenance.signature.key_id ? `:${selectedProvenance.signature.key_id}` : ""}
                          </div>
                        </div>
                        <div>
                          <div className="text-nepsis-muted">Request</div>
                          <div className="font-mono text-nepsis-text">
                            {selectedProvenance.request.request_id ?? "n/a"}
                          </div>
                        </div>
                        <div>
                          <div className="text-nepsis-muted">Retention</div>
                          <div className="text-nepsis-text">{selectedProvenance.retention.mode}</div>
                        </div>
                        <div className="md:col-span-3">
                          <div className="text-nepsis-muted">Source</div>
                          <div className="text-nepsis-text">{selectedProvenance.source}</div>
                        </div>
                      </div>
                    ) : (
                      <div className="mt-2 text-nepsis-muted">
                        No provenance record loaded for this packet.
                      </div>
                    )}
                    {auditExport && (
                      <div className="mt-2 text-nepsis-muted">
                        audit export: {auditExport.verification.record_count} records,{" "}
                        {auditExport.verification.hash_failures.length} hash failures
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => activeSession?.session_id && void exportSessionAudit(activeSession.session_id)}
                      className="mt-2 rounded-full border border-nepsis-border px-2 py-0.5 text-[11px] text-nepsis-muted hover:border-nepsis-accent hover:text-nepsis-text"
                    >
                      Verify Export
                    </button>
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
                OpenAI model
                <select
                  value={detachedModel}
                  onChange={(event) => setDetachedModel(event.target.value as DetachedModel)}
                  className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-nepsis-text"
                >
                  <option value="gpt-4.1">gpt-4.1</option>
                  <option value="gpt-4.1-mini">gpt-4.1-mini</option>
                  <option value="o3">o3</option>
                  <option value="o4-mini">o4-mini</option>
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
              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => captureModelSnapshot(null)}
                  disabled={!detachedCompare}
                  className="rounded-full border border-nepsis-border px-3 py-1 text-[11px] hover:border-nepsis-accent disabled:opacity-60"
                >
                  Capture Snapshot
                </button>
                <button
                  onClick={clearModelSnapshots}
                  disabled={modelSnapshots.length === 0}
                  className="rounded-full border border-nepsis-border px-3 py-1 text-[11px] hover:border-nepsis-accent disabled:opacity-60"
                >
                  Clear Deltas
                </button>
              </div>
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
                    {formatMessageTime(message.at)}
                    {message.source ? ` · src: ${message.source}` : ""}
                  </div>
                  <div className="mt-0.5 whitespace-pre-wrap text-nepsis-text">{message.text}</div>
                </div>
              ))}
            </div>

            {detachedCompare && (
              <div className="mt-3 rounded-lg border border-nepsis-border bg-black/20 p-3 text-xs">
                <div className="mb-1 text-nepsis-muted">Structured model deltas</div>
                {!baselineSnapshot && (
                  <div className="text-nepsis-muted">Capture a snapshot to establish baseline comparison.</div>
                )}
                {baselineSnapshot && (
                  <div className="space-y-2">
                    <div className="rounded border border-nepsis-border px-2 py-1.5 text-nepsis-muted">
                      baseline: {baselineSnapshot.model}
                      {baselineSnapshot.source ? ` · src: ${baselineSnapshot.source}` : ""}
                    </div>
                    {modelDeltaRows.length === 0 && (
                      <div className="text-nepsis-muted">Capture at least one additional model snapshot for deltas.</div>
                    )}
                    {modelDeltaRows.map((row) => (
                      <div key={row.snapshot.id} className="rounded border border-nepsis-border px-2 py-1.5">
                        <div className="font-medium text-nepsis-text">{row.snapshot.model}</div>
                        <div className="mt-1 grid gap-1 md:grid-cols-2 text-nepsis-muted">
                          <div>frame deltas: {row.frameDeltaCount}</div>
                          <div>interpretation deltas: {row.interpretationDeltaCount}</div>
                          <div>threshold deltas: {row.thresholdDeltaCount}</div>
                          <div>gate status: {deltaMarker(row.gateStatusDelta)}</div>
                          <div>
                            recommendation: {row.snapshot.recommendation ?? "n/a"}
                          </div>
                          <div>warning: {row.snapshot.warningLevel ?? "n/a"}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="mt-3 flex gap-2">
              <textarea
                value={detachedInput}
                onChange={(event) => setDetachedInput(event.target.value)}
                rows={3}
                placeholder="Sandbox prompt..."
                disabled={detachedBusy}
                className="w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs"
              />
              <button
                onClick={() => void handleSendDetachedMessage()}
                disabled={detachedBusy}
                className="h-fit rounded-full border border-nepsis-border px-3 py-1.5 text-xs hover:border-nepsis-accent disabled:opacity-60"
              >
                {detachedBusy ? "Running..." : "Send"}
              </button>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
