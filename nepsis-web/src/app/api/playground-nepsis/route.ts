import { NextResponse } from "next/server";
import { openai } from "@/lib/openaiClient";
import { buildProtoStateFromOutput, extractJingallCandidate, letterDelta } from "@/lib/protoPuzzleFromLlm";
import { evaluateProtoPuzzleTs, type ProtoEvaluation } from "@/lib/protoPuzzle";

export const runtime = "nodejs";

const PLAYGROUND_PACKS = new Set(["jailing_jingall", "utf8_clean"]);

type PlaygroundRequest = {
  prompt?: string;
  packId?: string;
};

function extractText(payload: Record<string, unknown> | null | undefined): string {
  if (!payload) {
    return "";
  }

  const outputText = payload["output_text"];
  if (typeof outputText === "string") {
    return outputText;
  }
  if (Array.isArray(outputText)) {
    return outputText.join("\n\n");
  }

  const output = payload["output"];
  if (Array.isArray(output) && output.length > 0) {
    const first = output[0] as Record<string, unknown>;
    const content = first?.["content"];
    if (Array.isArray(content)) {
      const textChunk = content.find((chunk) => typeof (chunk as { text?: string }).text === "string") as
        | { text: string }
        | undefined;
      if (textChunk?.text) {
        return textChunk.text;
      }
    }
  }

  if (typeof payload["text"] === "string") {
    return payload["text"] as string;
  }

  return "";
}

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body) {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { prompt, packId } = body as PlaygroundRequest;

  if (!prompt || typeof prompt !== "string") {
    return NextResponse.json({ error: "Missing prompt" }, { status: 400 });
  }

  if (!packId || typeof packId !== "string" || !PLAYGROUND_PACKS.has(packId)) {
    return NextResponse.json({ error: "Pack is not available in Playground" }, { status: 400 });
  }

  try {
    const completion = await openai.responses.create({
      model: process.env.OPENAI_MODEL ?? "gpt-4.1-mini",
      input: prompt,
    });

    const rawOutput = extractText(completion) || "";
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
