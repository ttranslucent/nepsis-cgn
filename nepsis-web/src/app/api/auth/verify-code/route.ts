import { NextResponse } from "next/server";
import { requireSameOriginRequest } from "@/lib/requestSecurity";

import {
  NEPSIS_CSRF_COOKIE,
  LOGIN_SESSION_TTL_SECONDS,
  NEPSIS_LOGIN_CHALLENGE_COOKIE,
  NEPSIS_USER_COOKIE,
  checkLoginRateLimit,
  cookieOptions,
  createCsrfToken,
  createLoginSession,
  csrfCookieOptions,
  normalizeLoginCode,
  normalizeEmail,
  operatorEmailAllowed,
  readCookieFromHeader,
  supabaseOtpConfigured,
  verifySupabaseLoginCode,
  verifyLoginChallenge,
} from "@/lib/nepsisAuth";

export const runtime = "nodejs";

export async function POST(req: Request) {
  const sameOriginFailure = requireSameOriginRequest(req);
  if (sameOriginFailure) {
    return sameOriginFailure;
  }

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid request payload" }, { status: 400 });
  }

  const email = normalizeEmail((body as { email?: unknown } | null)?.email);
  const rawCode = (body as { code?: unknown } | null)?.code;
  const code = normalizeLoginCode(rawCode);
  const rememberDevice = (body as { rememberDevice?: unknown } | null)?.rememberDevice !== false;
  if (!email || !code) {
    return NextResponse.json({ error: "Email and 6-digit code required" }, { status: 400 });
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

  if (supabaseOtpConfigured()) {
    const verification = await verifySupabaseLoginCode(email, code);
    if (!verification.ok) {
      return NextResponse.json({ error: verification.error }, { status: verification.status });
    }
  } else {
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
  response.cookies.set(
    NEPSIS_CSRF_COOKIE,
    createCsrfToken(sessionToken),
    csrfCookieOptions(rememberDevice ? LOGIN_SESSION_TTL_SECONDS : undefined),
  );
  response.cookies.set(NEPSIS_LOGIN_CHALLENGE_COOKIE, "", cookieOptions(0));
  return response;
}
