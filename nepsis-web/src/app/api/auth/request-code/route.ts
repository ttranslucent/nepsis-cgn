import { NextResponse } from "next/server";
import { publicSiteMode } from "@/lib/publicMode";
import { requireSameOriginRequest } from "@/lib/requestSecurity";

import {
  LOGIN_CODE_TTL_SECONDS,
  NEPSIS_LOGIN_CHALLENGE_COOKIE,
  NEPSIS_SUPABASE_OTP_SENT_COOKIE,
  checkLoginRateLimit,
  cookieOptions,
  createLoginChallenge,
  createSupabaseOtpPending,
  deliverLoginCode,
  generateLoginCode,
  loginEmailConfigured,
  normalizeEmail,
  operatorEmailAllowlistConfigured,
  operatorEmailAllowed,
  readCookieFromHeader,
  readSupabaseOtpPendingFromCookieValue,
  requestSupabaseLoginCode,
  supabaseOtpConfigured,
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
  const forceNewCode = (body as { forceNewCode?: unknown } | null)?.forceNewCode === true;
  if (!email) {
    return NextResponse.json({ error: "Valid email required" }, { status: 400 });
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
      provider: loginEmailConfigured() ? "nepsis" : supabaseOtpConfigured() ? "supabase" : "nepsis",
      previewCode: null,
      expiresInSeconds: LOGIN_CODE_TTL_SECONDS,
    });
  }

  const pendingSupabaseOtp = supabaseOtpConfigured()
    ? readSupabaseOtpPendingFromCookieValue(
        readCookieFromHeader(req.headers.get("cookie") ?? "", NEPSIS_SUPABASE_OTP_SENT_COOKIE),
        email,
      )
    : null;
  if (pendingSupabaseOtp && !forceNewCode) {
    return NextResponse.json({
      ok: true,
      delivery: "email",
      provider: "supabase",
      reusedExistingCode: true,
      previewCode: null,
      expiresInSeconds: pendingSupabaseOtp.remainingSeconds,
    });
  }

  const rateLimit = checkLoginRateLimit("request-code", req, email);
  if (!rateLimit.ok) {
    return NextResponse.json(
      { error: rateLimit.error, retryAfterSeconds: rateLimit.retryAfterSeconds },
      { status: 429 },
    );
  }

  const sendLocalSignedCode = async () => {
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
      provider: "nepsis",
      previewCode: delivery.delivery === "preview" ? delivery.previewCode : null,
      expiresInSeconds: LOGIN_CODE_TTL_SECONDS,
    });
    response.cookies.set(
      NEPSIS_LOGIN_CHALLENGE_COOKIE,
      challenge,
      cookieOptions(LOGIN_CODE_TTL_SECONDS),
    );
    response.cookies.set(NEPSIS_SUPABASE_OTP_SENT_COOKIE, "", cookieOptions(0));
    return response;
  };

  if (loginEmailConfigured()) {
    return sendLocalSignedCode();
  }

  if (supabaseOtpConfigured()) {
    const delivery = await requestSupabaseLoginCode(email);
    if (!delivery.ok) {
      if (pendingSupabaseOtp && delivery.status === 429) {
        return NextResponse.json({
          ok: true,
          delivery: "email",
          provider: "supabase",
          reusedExistingCode: true,
          warning: delivery.error,
          previewCode: null,
          expiresInSeconds: pendingSupabaseOtp.remainingSeconds,
        });
      }
      return NextResponse.json(
        {
          error: delivery.error,
          allowCodeEntry: delivery.status === 429,
        },
        { status: delivery.status },
      );
    }

    const response = NextResponse.json({
      ok: true,
      delivery: "email",
      provider: "supabase",
      reusedExistingCode: false,
      previewCode: null,
      expiresInSeconds: LOGIN_CODE_TTL_SECONDS,
    });
    response.cookies.set(NEPSIS_LOGIN_CHALLENGE_COOKIE, "", cookieOptions(0));
    response.cookies.set(
      NEPSIS_SUPABASE_OTP_SENT_COOKIE,
      createSupabaseOtpPending(email),
      cookieOptions(LOGIN_CODE_TTL_SECONDS),
    );
    return response;
  }

  return sendLocalSignedCode();
}
