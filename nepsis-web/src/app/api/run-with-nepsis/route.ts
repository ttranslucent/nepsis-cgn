import { NextResponse } from "next/server";
import {
  DEFAULT_OPENAI_MODEL,
  createOpenAiClient,
  extractOpenAiText,
} from "@/lib/openaiClient";
import { requireEngineControlAuth } from "@/lib/engineApi";
import { modelRoutesEnabled } from "@/lib/publicMode";

export async function POST(req: Request) {
  try {
    if (!modelRoutesEnabled()) {
      return NextResponse.json(
        {
          error: "Model routes disabled",
          detail: "Public deployments do not run model calls or accept browser API keys.",
        },
        { status: 403 },
      );
    }

    const authFailure = requireEngineControlAuth(req);
    if (authFailure) {
      return authFailure;
    }

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
