import { randomUUID } from "node:crypto";
import { NextResponse } from "next/server";

import {
  DEFAULT_OPENAI_MODEL,
  createOpenAiClient,
  extractOpenAiText,
  hasConfiguredOpenAiKey,
} from "@/lib/openaiClient";
import { requireEngineControlAuth } from "@/lib/engineApi";
import { modelRoutesEnabled } from "@/lib/publicMode";
import { requireCsrfToken } from "@/lib/requestSecurity";

export const runtime = "nodejs";

const MODES = new Set(["suggest_field", "review_completion"]);
const TARGETS = new Set([
  "frame.text",
  "frame.key_uncertainty",
  "frame.constraints_hard",
  "frame.constraints_soft",
  "frame.red_definition",
  "frame.blue_goals",
  "threshold.hold_reason",
  "next_frame.text",
]);

function systemPrompt(mode: string, target: string): string {
  const base =
    "You are assisting a NepsisCGN operator. Preserve RED before BLUE. " +
    "Do not make final commitments. Suggest only the requested field. Return compact JSON only.";
  return `${base} Mode: ${mode}. Requested field: ${target}. JSON shape: {"suggestions":[{"title":"","proposedValue":"","rationale":"","riskNote":""}],"outputText":""}`;
}

function parseObject(text: string): Record<string, unknown> {
  const cleaned = text.trim().replace(/^```(?:json)?/i, "").replace(/```$/i, "").trim();
  const parsed = JSON.parse(cleaned);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Model response was not a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function canonicalNonEmpty(value: string | string[]): boolean {
  return Array.isArray(value) ? value.some((item) => item.trim()) : Boolean(value.trim());
}

function normalizeSuggestions(value: unknown, requestedTarget: string) {
  const rows = Array.isArray(value) ? value : [];
  return rows
    .filter((row): row is Record<string, unknown> =>
      typeof row === "object" && row !== null && !Array.isArray(row),
    )
    .map((row) => ({
      id: randomUUID(),
      target: requestedTarget,
      title: typeof row.title === "string" ? row.title : "Suggestion",
      proposedValue: Array.isArray(row.proposedValue)
        ? row.proposedValue.filter((item): item is string => typeof item === "string")
        : typeof row.proposedValue === "string"
          ? row.proposedValue
          : "",
      rationale: typeof row.rationale === "string" ? row.rationale : "",
      riskNote: typeof row.riskNote === "string" ? row.riskNote : "",
    }))
    .filter((row) => canonicalNonEmpty(row.proposedValue));
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
  const csrfFailure = requireCsrfToken(req);
  if (csrfFailure) {
    return csrfFailure;
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
  const target = typeof body?.target === "string" ? body.target : "";
  const input = typeof body?.input === "string" ? body.input.trim() : "";
  const model =
    typeof body?.model === "string" && body.model.trim().length > 0
      ? body.model.trim()
      : DEFAULT_OPENAI_MODEL;
  const context = typeof body?.context === "object" && body.context !== null ? body.context : {};

  if (!MODES.has(mode)) {
    return NextResponse.json({ error: "Invalid mode" }, { status: 400 });
  }
  if (mode === "suggest_field" && !TARGETS.has(target)) {
    return NextResponse.json({ error: "Invalid assist target" }, { status: 400 });
  }
  if (!input) {
    return NextResponse.json({ error: "Input is required" }, { status: 400 });
  }

  try {
    const requestedTarget = TARGETS.has(target) ? target : "frame.text";
    const prompt = [
      `System:\n${systemPrompt(mode, requestedTarget)}`,
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
      suggestions: normalizeSuggestions(parsed.suggestions, requestedTarget),
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
