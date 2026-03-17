import crypto from "crypto";

export const NEPSIS_USER_COOKIE = "nepsis_user";
export const NEPSIS_LOGIN_CHALLENGE_COOKIE = "nepsis_login_challenge";
export const LOGIN_CODE_TTL_SECONDS = 10 * 60;
export const LOGIN_SESSION_TTL_SECONDS = 60 * 60 * 24 * 7;

type LoginChallengePayload = {
  email: string;
  hash: string;
  expiresAt: number;
};

type LoginCodeDelivery =
  | { delivery: "email" }
  | { delivery: "preview"; previewCode: string }
  | { delivery: "unavailable"; error: string };

function authSecret(): string {
  const configured = process.env.NEPSIS_AUTH_SECRET?.trim();
  if (configured) {
    return configured;
  }
  if (process.env.NODE_ENV !== "production") {
    return "nepsis-dev-auth-secret";
  }
  throw new Error("NEPSIS_AUTH_SECRET must be configured in production.");
}

function signValue(payload: string): string {
  return crypto.createHmac("sha256", authSecret()).update(payload).digest("base64url");
}

function encodeChallenge(payload: LoginChallengePayload): string {
  const encoded = Buffer.from(JSON.stringify(payload), "utf-8").toString("base64url");
  const signature = signValue(encoded);
  return `${encoded}.${signature}`;
}

function decodeChallenge(token: string): LoginChallengePayload | null {
  const [encoded, signature] = token.split(".", 2);
  if (!encoded || !signature) {
    return null;
  }
  if (signValue(encoded) !== signature) {
    return null;
  }
  try {
    const parsed = JSON.parse(Buffer.from(encoded, "base64url").toString("utf-8"));
    if (
      typeof parsed?.email !== "string" ||
      typeof parsed?.hash !== "string" ||
      typeof parsed?.expiresAt !== "number" ||
      !Number.isFinite(parsed.expiresAt)
    ) {
      return null;
    }
    return {
      email: parsed.email,
      hash: parsed.hash,
      expiresAt: parsed.expiresAt,
    };
  } catch {
    return null;
  }
}

export function normalizeEmail(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.toLowerCase().trim();
  if (!normalized || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalized)) {
    return null;
  }
  return normalized;
}

export function generateLoginCode(): string {
  return Math.floor(100000 + Math.random() * 900000).toString();
}

export function hashLoginCode(code: string): string {
  return crypto.createHash("sha256").update(code).digest("hex");
}

export function createLoginChallenge(email: string, code: string): string {
  return encodeChallenge({
    email,
    hash: hashLoginCode(code),
    expiresAt: Date.now() + LOGIN_CODE_TTL_SECONDS * 1000,
  });
}

export function verifyLoginChallenge(
  token: string | null | undefined,
  email: string,
  code: string,
): { ok: true } | { ok: false; error: string } {
  if (!token) {
    return { ok: false, error: "Code expired or not found" };
  }
  const challenge = decodeChallenge(token);
  if (!challenge) {
    return { ok: false, error: "Code expired or not found" };
  }
  if (challenge.email !== email) {
    return { ok: false, error: "Code expired or not found" };
  }
  if (Date.now() > challenge.expiresAt) {
    return { ok: false, error: "Code expired or not found" };
  }
  if (challenge.hash !== hashLoginCode(code.trim())) {
    return { ok: false, error: "Invalid code" };
  }
  return { ok: true };
}

export function readCookieFromHeader(cookieHeader: string, cookieName: string): string | null {
  if (!cookieHeader) {
    return null;
  }
  const prefix = `${cookieName}=`;
  for (const segment of cookieHeader.split(";")) {
    const trimmed = segment.trim();
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length));
    }
  }
  return null;
}

export function readNepsisUserFromRequest(request: Request): string | null {
  const cookieHeader = request.headers.get("cookie") ?? "";
  return readCookieFromHeader(cookieHeader, NEPSIS_USER_COOKIE);
}

export function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
    maxAge,
  };
}

async function sendWithResend(email: string, code: string): Promise<boolean> {
  const resendApiKey = process.env.RESEND_API_KEY?.trim();
  const from = process.env.NEPSIS_AUTH_FROM_EMAIL?.trim();
  if (!resendApiKey || !from) {
    return false;
  }

  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${resendApiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: [email],
      subject: "Your NepsisCGN login code",
      text: `Your NepsisCGN login code is ${code}. It expires in 10 minutes.`,
      html: `<p>Your NepsisCGN login code is <strong>${code}</strong>.</p><p>This code expires in 10 minutes.</p>`,
    }),
  });

  if (!response.ok) {
    throw new Error(`Email provider rejected request (${response.status}).`);
  }
  return true;
}

export async function deliverLoginCode(email: string, code: string): Promise<LoginCodeDelivery> {
  try {
    if (await sendWithResend(email, code)) {
      return { delivery: "email" };
    }
  } catch (error) {
    if (process.env.NODE_ENV === "production") {
      return {
        delivery: "unavailable",
        error: (error as Error)?.message ?? "Login email delivery failed.",
      };
    }
  }

  const allowPreview =
    process.env.NODE_ENV !== "production" || process.env.NEPSIS_AUTH_ALLOW_CODE_PREVIEW === "true";
  if (allowPreview) {
    console.log(`Nepsis login code for ${email}: ${code}`);
    return { delivery: "preview", previewCode: code };
  }

  return {
    delivery: "unavailable",
    error:
      "Login email delivery is not configured. Set RESEND_API_KEY and NEPSIS_AUTH_FROM_EMAIL, or enable NEPSIS_AUTH_ALLOW_CODE_PREVIEW for preview-only testing.",
  };
}
