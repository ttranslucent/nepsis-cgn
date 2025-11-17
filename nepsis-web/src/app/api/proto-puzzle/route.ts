import { NextResponse } from "next/server";
import { evaluateProtoPuzzleTs, isSupportedProtoPack } from "@/lib/protoPuzzle";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const body = await req.json().catch(() => null);
  if (!body) {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const { packId, state } = body as { packId?: string; state?: unknown };

  if (!packId || !isSupportedProtoPack(packId)) {
    return NextResponse.json({ error: "Unknown packId" }, { status: 400 });
  }

  if (!state || typeof state !== "object") {
    return NextResponse.json({ error: "state must be an object" }, { status: 400 });
  }

  try {
    const report = await evaluateProtoPuzzleTs(packId, state as Record<string, unknown>);
    return NextResponse.json(report);
  } catch (error) {
    console.error("Proto puzzle evaluation failed", error);
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}
