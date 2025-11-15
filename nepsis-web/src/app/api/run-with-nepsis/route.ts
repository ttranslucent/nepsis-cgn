import { NextResponse } from "next/server";

export async function POST(req: Request) {
  try {
    const { prompt, apiKey } = await req.json();

    if (!prompt || typeof prompt !== "string") {
      return NextResponse.json({ error: "prompt is required" }, { status: 400 });
    }

    if (!apiKey || typeof apiKey !== "string") {
      return NextResponse.json({ error: "apiKey is required" }, { status: 400 });
    }

    const completionRes = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model: "gpt-4.1-mini",
        messages: [
          {
            role: "system",
            content:
              "You are a helpful assistant used for testing NepsisCGN. Answer clearly and concisely.",
          },
          { role: "user", content: prompt },
        ],
        temperature: 0.2,
      }),
    });

    if (!completionRes.ok) {
      const errText = await completionRes.text();
      console.error("OpenAI error:", errText);
      return NextResponse.json(
        { error: "OpenAI API error", detail: errText },
        { status: 500 },
      );
    }

    const completionData = await completionRes.json();
    const rawAnswer =
      completionData?.choices?.[0]?.message?.content ?? "[No content returned from model]";

    const cgnResult = {
      valid: true,
      distance: 0,
      violations: [] as unknown[],
    };

    return NextResponse.json({ rawAnswer, cgn: cgnResult });
  } catch (err) {
    console.error("run-with-nepsis error:", err);
    return NextResponse.json({ error: "Internal error", detail: String(err) }, { status: 500 });
  }
}
