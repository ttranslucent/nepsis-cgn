import { NextResponse } from "next/server";

export async function POST(req: Request) {
  const { prompt, apiKey } = await req.json();

  if (!prompt || !apiKey) {
    return NextResponse.json({ error: "prompt and apiKey required" }, { status: 400 });
  }

  const rawAnswer = `Echo: ${prompt}`;
  const cgnResult = {
    valid: true,
    distance: 0,
    violations: [] as unknown[],
  };

  return NextResponse.json({ rawAnswer, cgn: cgnResult });
}
