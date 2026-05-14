import { NextResponse } from "next/server";
import {
  DEFAULT_OPENAI_MODEL,
  createOpenAiClient,
  extractOpenAiText,
} from "@/lib/openaiClient";

export async function POST(req: Request) {
  try {
    const { prompt, apiKey, model } = await req.json();

    if (!prompt || typeof prompt !== "string") {
      return NextResponse.json({ error: "Prompt is required." }, { status: 400 });
    }

    const completion = await createOpenAiClient(apiKey).responses.create({
      model: typeof model === "string" && model.trim().length > 0 ? model.trim() : DEFAULT_OPENAI_MODEL,
      input: prompt,
    });

    const outputText = extractOpenAiText(completion) || "[No model output returned]";
    const resolvedModel =
      typeof model === "string" && model.trim().length > 0 ? model.trim() : DEFAULT_OPENAI_MODEL;

    return NextResponse.json({
      model: resolvedModel,
      outputText,
      rawAnswer: outputText,
      cgn: {
        valid: true,
        distance: 0,
        violations: [],
      },
    });
  } catch (err) {
    console.error("run-with-nepsis error:", err);
    return NextResponse.json({ error: "Internal error", detail: String(err) }, { status: 500 });
  }
}
