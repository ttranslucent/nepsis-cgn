import { NextResponse } from "next/server";

import {
  LOGIN_SESSION_TTL_SECONDS,
  NEPSIS_LOGIN_CHALLENGE_COOKIE,
  NEPSIS_USER_COOKIE,
  checkLoginRateLimit,
  cookieOptions,
  createLoginSession,
  normalizeEmail,
  operatorEmailAllowed,
  readCookieFromHeader,
  verifyLoginChallenge,
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
  const rawCode = (body as { code?: unknown } | null)?.code;
  const code = typeof rawCode === "string" ? rawCode.trim() : "";
  const rememberDevice = (body as { rememberDevice?: unknown } | null)?.rememberDevice !== false;
  if (!email || !code) {
    return NextResponse.json({ error: "Email and code required" }, { status: 400 });
  }

  const rateLimit = checkLoginRateLimit("verify-code", req, email);
  if (!rateLimit.ok) {
    return NextResponse.json(
      { error: rateLimit.error, retryAfterSeconds: rateLimit.retryAfterSeconds },
      { status: 429 },
    );
  }

  if (!operatorEmailAllowed(email)) {
    return NextResponse.json({ error: "Code expired or not found" }, { status: 400 });
  }

  const challenge = readCookieFromHeader(
    req.headers.get("cookie") ?? "",
    NEPSIS_LOGIN_CHALLENGE_COOKIE,
  );
  let verification: ReturnType<typeof verifyLoginChallenge>;
  try {
    verification = verifyLoginChallenge(challenge, email, code);
  } catch (error) {
    return NextResponse.json(
      { error: (error as Error)?.message ?? "Login is unavailable in this environment." },
      { status: 503 },
    );
  }
  if (!verification.ok) {
    const response = NextResponse.json({ error: verification.error }, { status: 400 });
    if (verification.error !== "Invalid code") {
      response.cookies.set(NEPSIS_LOGIN_CHALLENGE_COOKIE, "", cookieOptions(0));
    }
    return response;
  }

  let sessionToken: string;
  try {
    sessionToken = createLoginSession(email);
  } catch (error) {
    return NextResponse.json(
      { error: (error as Error)?.message ?? "Login is unavailable in this environment." },
      { status: 503 },
    );
  }

  const response = NextResponse.json({ ok: true, user: email });
  response.cookies.set(
    NEPSIS_USER_COOKIE,
    sessionToken,
    cookieOptions(rememberDevice ? LOGIN_SESSION_TTL_SECONDS : undefined),
  );
  response.cookies.set(NEPSIS_LOGIN_CHALLENGE_COOKIE, "", cookieOptions(0));
  return response;
}
