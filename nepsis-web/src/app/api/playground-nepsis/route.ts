import { NextResponse } from "next/server";
import {
  DEFAULT_OPENAI_MODEL,
  createOpenAiClient,
  extractOpenAiText,
} from "@/lib/openaiClient";
import { buildProtoStateFromOutput, extractJingallCandidate, letterDelta } from "@/lib/protoPuzzleFromLlm";
import { evaluateProtoPuzzleTs, type ProtoEvaluation } from "@/lib/protoPuzzle";

export const runtime = "nodejs";

const PLAYGROUND_PACKS = new Set(["jailing_jingall", "utf8_clean"]);

type PlaygroundRequest = {
  prompt?: string;
  packId?: string;
  apiKey?: string;
  model?: string;
};

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body) {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { prompt, packId, apiKey, model } = body as PlaygroundRequest;

  if (!prompt || typeof prompt !== "string") {
    return NextResponse.json({ error: "Missing prompt" }, { status: 400 });
  }

  if (!packId || typeof packId !== "string" || !PLAYGROUND_PACKS.has(packId)) {
    return NextResponse.json({ error: "Pack is not available in Playground" }, { status: 400 });
  }

  try {
    const completion = await createOpenAiClient(apiKey).responses.create({
      model: typeof model === "string" && model.trim().length > 0 ? model.trim() : DEFAULT_OPENAI_MODEL,
      input: prompt,
    });

    const rawOutput = extractOpenAiText(completion) || "";
    const state = buildProtoStateFromOutput(packId, rawOutput);
    const evaluation = await evaluateProtoPuzzleTs(packId, state);
    const enrichedEvaluation =
      packId === "jailing_jingall" ? withJingallViolationExplanation(evaluation, rawOutput) : evaluation;

    return NextResponse.json({
      rawOutput,
      evaluation: enrichedEvaluation,
    });
  } catch (error) {
    console.error("playground-nepsis failure", error);
    return NextResponse.json(
      {
        error: "Playground request failed",
        detail: (error as Error)?.message ?? "Unknown error",
      },
      { status: 500 },
    );
  }
}

function withJingallViolationExplanation(evaluation: ProtoEvaluation, output: string): ProtoEvaluation {
  const candidate = extractJingallCandidate(output);
  if (!candidate) {
    return evaluation;
  }
  const stateNameCorrect = evaluation.state?.name_correct;
  if (stateNameCorrect || stateNameCorrect === undefined) {
    return evaluation;
  }
  const delta = letterDelta(candidate);
  const extra = delta.extra.length > 0 ? delta.extra.join(", ") : "none";
  const missing = delta.missing.length > 0 ? delta.missing.join(", ") : "none";
  const detail = ` Candidate "${candidate}" has extra: ${extra}; missing: ${missing}.`;

  const violations = evaluation.violations.map((violation) => {
    if (violation.code !== "C1") {
      return violation;
    }
    const metadata = {
      ...(violation.metadata ?? {}),
      candidate,
      letterDelta: delta,
    };
    return {
      ...violation,
      message: `${violation.message}${detail}`,
      metadata,
    };
  });

  return { ...evaluation, violations };
}
