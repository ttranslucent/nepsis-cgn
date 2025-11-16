import { NextResponse } from "next/server";

export async function POST(req: Request) {
  try {
    const { prompt, apiKey } = await req.json();

    if (!prompt || typeof prompt !== "string") {
      return NextResponse.json({ error: "Prompt is required." }, { status: 400 });
    }

    if (!apiKey || typeof apiKey !== "string") {
      return NextResponse.json({ error: "API key is required." }, { status: 400 });
    }

    const llmRes = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "OpenAI-Beta": "responses-2024-12-01=v1",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: "gpt-4.1-mini",
        input: [
          {
            role: "user",
            content: [
              {
                type: "input_text",
                text: prompt,
              },
            ],
          },
        ],
      }),
    });

    if (!llmRes.ok) {
      const errText = await llmRes.text();
      console.error("OpenAI error:", errText);
      return NextResponse.json(
        { error: "OpenAI API error", detail: errText },
        { status: 500 },
      );
    }

    const data = await llmRes.json();
    const rawAnswer = data.output_text ?? "[No model output returned]";

    return NextResponse.json({
      rawAnswer,
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
