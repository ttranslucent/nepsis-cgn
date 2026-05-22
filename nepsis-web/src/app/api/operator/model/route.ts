import { NextResponse } from "next/server";

import {
  DEFAULT_OPENAI_MODEL,
  createOpenAiClient,
  extractOpenAiText,
  hasConfiguredOpenAiKey,
} from "@/lib/openaiClient";
import { requireEngineControlAuth } from "@/lib/engineApi";
import { modelRoutesEnabled } from "@/lib/publicMode";

export const runtime = "nodejs";

const MODES = new Set(["draft_frame", "interpret_report", "threshold_review"]);

function systemPrompt(mode: string): string {
  const base =
    "You are assisting a NepsisCGN operator. Preserve RED before BLUE. " +
    "Do not make final commitments. Return compact JSON only.";
  if (mode === "draft_frame") {
    return `${base} JSON shape: {"frameDraft":{"text":"","objective_type":"decide","domain":"","time_horizon":"short","key_uncertainty":"","constraints_hard":[],"constraints_soft":[],"red_definition":"","blue_goals":""},"outputText":""}`;
  }
  if (mode === "interpret_report") {
    return `${base} JSON shape: {"reportNotes":"","outputText":""}`;
  }
  return `${base} JSON shape: {"thresholdNote":"","outputText":""}`;
}

function parseObject(text: string): Record<string, unknown> {
  const cleaned = text.trim().replace(/^```(?:json)?/i, "").replace(/```$/i, "").trim();
  const parsed = JSON.parse(cleaned);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Model response was not a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function frameDraft(value: unknown) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  return {
    text: typeof record.text === "string" ? record.text : "",
    objective_type: typeof record.objective_type === "string" ? record.objective_type : "decide",
    domain: typeof record.domain === "string" ? record.domain : "general",
    time_horizon: typeof record.time_horizon === "string" ? record.time_horizon : "short",
    key_uncertainty: typeof record.key_uncertainty === "string" ? record.key_uncertainty : "",
    constraints_hard: stringArray(record.constraints_hard),
    constraints_soft: stringArray(record.constraints_soft),
    red_definition: typeof record.red_definition === "string" ? record.red_definition : "",
    blue_goals: typeof record.blue_goals === "string" ? record.blue_goals : "",
  };
}

export async function POST(req: Request) {
  if (!modelRoutesEnabled()) {
    return NextResponse.json(
      {
        error: "Model routes disabled",
        detail: "Live operator model routes are not enabled for this deployment.",
      },
      { status: 403 },
    );
  }

  const authFailure = requireEngineControlAuth(req);
  if (authFailure) {
    return authFailure;
  }

  if (!hasConfiguredOpenAiKey()) {
    return NextResponse.json(
      {
        error: "Server model key required",
        detail: "Configure OPENAI_API_KEY or NEPSIS_OPENAI_API_KEY server-side.",
      },
      { status: 428 },
    );
  }

  const body = await req.json().catch(() => null);
  const mode = typeof body?.mode === "string" ? body.mode : "";
  const input = typeof body?.input === "string" ? body.input.trim() : "";
  const model =
    typeof body?.model === "string" && body.model.trim().length > 0
      ? body.model.trim()
      : DEFAULT_OPENAI_MODEL;
  const context = typeof body?.context === "object" && body.context !== null ? body.context : {};

  if (!MODES.has(mode)) {
    return NextResponse.json({ error: "Invalid mode" }, { status: 400 });
  }
  if (!input) {
    return NextResponse.json({ error: "Input is required" }, { status: 400 });
  }

  try {
    const prompt = [
      `System:\n${systemPrompt(mode)}`,
      `Operator input:\n${input}`,
      `Context JSON:\n${JSON.stringify(context)}`,
    ].join("\n\n");
    const completion = await createOpenAiClient().responses.create({
      model,
      input: prompt,
    });
    const raw = extractOpenAiText(completion) || "{}";
    const parsed = parseObject(raw);
    const outputText = typeof parsed.outputText === "string" ? parsed.outputText : raw;

    return NextResponse.json({
      mode,
      model,
      outputText,
      frameDraft: mode === "draft_frame" ? frameDraft(parsed.frameDraft) : undefined,
      reportNotes: typeof parsed.reportNotes === "string" ? parsed.reportNotes : undefined,
      thresholdNote: typeof parsed.thresholdNote === "string" ? parsed.thresholdNote : undefined,
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: "Operator model request failed",
        detail: (error as Error)?.message ?? "Unknown error",
      },
      { status: 502 },
    );
  }
}
