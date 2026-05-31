import { NextResponse } from "next/server";
import { publicSiteMode } from "@/lib/publicMode";
import { requireSameOriginRequest } from "@/lib/requestSecurity";

import {
  LOGIN_CODE_TTL_SECONDS,
  NEPSIS_LOGIN_CHALLENGE_COOKIE,
  checkLoginRateLimit,
  cookieOptions,
  createLoginChallenge,
  deliverLoginCode,
  generateLoginCode,
  normalizeEmail,
  operatorEmailAllowlistConfigured,
  operatorEmailAllowed,
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
  if (!email) {
    return NextResponse.json({ error: "Valid email required" }, { status: 400 });
  }

  const rateLimit = checkLoginRateLimit("request-code", req, email);
  if (!rateLimit.ok) {
    return NextResponse.json(
      { error: rateLimit.error, retryAfterSeconds: rateLimit.retryAfterSeconds },
      { status: 429 },
    );
  }

  if (!operatorEmailAllowlistConfigured()) {
    const allowlistError = "Operator OTP login is not configured. Set NEPSIS_AUTH_ALLOWED_EMAILS.";
    const publicDeliveryError =
      "Login email delivery is required in public-site mode. Set RESEND_API_KEY and NEPSIS_AUTH_FROM_EMAIL.";
    return NextResponse.json(
      { error: publicSiteMode() ? `${allowlistError} ${publicDeliveryError}` : allowlistError },
      { status: 503 },
    );
  }

  if (!operatorEmailAllowed(email)) {
    return NextResponse.json({
      ok: true,
      delivery: "email",
      previewCode: null,
      expiresInSeconds: LOGIN_CODE_TTL_SECONDS,
    });
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
