import { NextResponse } from "next/server";

import {
  LOGIN_CODE_TTL_SECONDS,
  NEPSIS_LOGIN_CHALLENGE_COOKIE,
  cookieOptions,
  createLoginChallenge,
  deliverLoginCode,
  generateLoginCode,
  normalizeEmail,
} from "@/lib/nepsisAuth";

export const runtime = "nodejs";

export async function POST(req: Request) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid request payload" }, { status: 400 });
  }

  const email = normalizeEmail((body as { email?: unknown } | null)?.email);
  if (!email) {
    return NextResponse.json({ error: "Valid email required" }, { status: 400 });
  }

  const code = generateLoginCode();
  let challenge: string;
  try {
    challenge = createLoginChallenge(email, code);
  } catch (error) {
    return NextResponse.json(
      { error: (error as Error)?.message ?? "Login is unavailable in this environment." },
      { status: 503 },
    );
  }
  const delivery = await deliverLoginCode(email, code);

  if (delivery.delivery === "unavailable") {
    return NextResponse.json({ error: delivery.error }, { status: 503 });
  }

  const response = NextResponse.json({
    ok: true,
    delivery: delivery.delivery,
    previewCode: delivery.delivery === "preview" ? delivery.previewCode : null,
    expiresInSeconds: LOGIN_CODE_TTL_SECONDS,
  });
  response.cookies.set(
    NEPSIS_LOGIN_CHALLENGE_COOKIE,
    challenge,
    cookieOptions(LOGIN_CODE_TTL_SECONDS),
  );
  return response;
}
