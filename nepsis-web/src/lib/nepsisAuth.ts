import crypto from "crypto";
import { envFlag, operatorSiteMode, publicSiteMode } from "@/lib/publicMode";

export const NEPSIS_USER_COOKIE = "nepsis_user";
export const NEPSIS_LOGIN_CHALLENGE_COOKIE = "nepsis_login_challenge";
export const LOGIN_CODE_TTL_SECONDS = 10 * 60;
export const LOGIN_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;
export const LOGIN_SESSION_DAYS = 30;
const RESEND_REQUEST_TIMEOUT_MS = 8000;
const LOGIN_REQUEST_WINDOW_SECONDS = 15 * 60;
const LOGIN_REQUEST_MAX_ATTEMPTS = 5;
const LOGIN_VERIFY_WINDOW_SECONDS = 10 * 60;
const LOGIN_VERIFY_MAX_ATTEMPTS = 10;
const RATE_LIMIT_STATE = new Map<string, number[]>();

type LoginChallengePayload = {
  email: string;
  hash: string;
  expiresAt: number;
};

type LoginSessionPayload = {
  email: string;
  issuedAt: number;
  expiresAt: number;
};

type LoginCodeDelivery =
  | { delivery: "email" }
  | { delivery: "preview"; previewCode: string }
  | { delivery: "unavailable"; error: string };

type AuthSecretStatus = {
  configured: boolean;
  ready: boolean;
  mode: "configured" | "development-fallback" | "missing";
};

type LoginRateLimitScope = "request-code" | "verify-code";
type LoginRateLimitResult =
  | { ok: true }
  | { ok: false; retryAfterSeconds: number; error: string };

export function previewCodesAllowed(): boolean {
  if (process.env.NODE_ENV === "production" || publicSiteMode() || operatorSiteMode()) {
    return false;
  }
  return envFlag("NEPSIS_AUTH_ALLOW_CODE_PREVIEW");
}

function isPlaceholderResendConfig(apiKey: string, from: string): boolean {
  const normalizedKey = apiKey.trim().toLowerCase();
  const normalizedFrom = from.trim().toLowerCase();
  return (
    normalizedKey === "re_xxxxxxxxxxxxx" ||
    normalizedKey === "your_resend_api_key_here" ||
    normalizedKey.startsWith("replace-with-") ||
    normalizedFrom.includes("auth@example.com") ||
    normalizedFrom.includes("example.com") ||
    normalizedFrom.includes("your-domain.")
  );
}

export function loginEmailConfigured(): boolean {
  const resendApiKey = process.env.RESEND_API_KEY?.trim();
  const from = process.env.NEPSIS_AUTH_FROM_EMAIL?.trim();
  return Boolean(resendApiKey && from && !isPlaceholderResendConfig(resendApiKey, from));
}

function allowedOperatorEmailSet(): Set<string> {
  const raw = process.env.NEPSIS_AUTH_ALLOWED_EMAILS?.trim() ?? "";
  const emails = raw
    .split(/[\s,]+/)
    .map((value) => normalizeEmail(value))
    .filter((value): value is string => Boolean(value));
  return new Set(emails);
}

export function operatorEmailAllowlistConfigured(): boolean {
  return allowedOperatorEmailSet().size > 0;
}

export function operatorEmailAllowed(email: string): boolean {
  const normalized = normalizeEmail(email);
  return Boolean(normalized && allowedOperatorEmailSet().has(normalized));
}

export function sessionRevokeBeforeConfigured(): boolean {
  return Boolean(process.env.NEPSIS_AUTH_SESSION_REVOKE_BEFORE?.trim());
}

export function authSecretStatus(): AuthSecretStatus {
  const configured = process.env.NEPSIS_AUTH_SECRET?.trim();
  if (configured) {
    return { configured: true, ready: true, mode: "configured" };
  }
  if (process.env.NODE_ENV !== "production" && !publicSiteMode()) {
    return { configured: false, ready: true, mode: "development-fallback" };
  }
  return { configured: false, ready: false, mode: "missing" };
}

export function operatorLoginReady(): boolean {
  return authSecretStatus().ready && operatorEmailAllowlistConfigured() && (loginEmailConfigured() || previewCodesAllowed());
}

function authSecret(): string {
  const status = authSecretStatus();
  if (status.mode === "development-fallback") {
    return "nepsis-dev-auth-secret";
  }
  const configured = process.env.NEPSIS_AUTH_SECRET?.trim();
  if (configured) {
    return configured;
  }
  throw new Error("NEPSIS_AUTH_SECRET must be configured in production or public-site mode.");
}

function signValue(payload: string): string {
  return crypto.createHmac("sha256", authSecret()).update(payload).digest("base64url");
}

function encodeSignedPayload(payload: object): string {
  const encoded = Buffer.from(JSON.stringify(payload), "utf-8").toString("base64url");
  const signature = signValue(encoded);
  return `${encoded}.${signature}`;
}

function signatureMatches(encoded: string, signature: string): boolean {
  const expected = signValue(encoded);
  const actualBuffer = Buffer.from(signature, "base64url");
  const expectedBuffer = Buffer.from(expected, "base64url");
  if (actualBuffer.length !== expectedBuffer.length) {
    return false;
  }
  return crypto.timingSafeEqual(actualBuffer, expectedBuffer);
}

function decodeSignedPayload(token: string): unknown | null {
  const [encoded, signature] = token.split(".", 2);
  if (!encoded || !signature) {
    return null;
  }
  if (!signatureMatches(encoded, signature)) {
    return null;
  }
  try {
    return JSON.parse(Buffer.from(encoded, "base64url").toString("utf-8"));
  } catch {
    return null;
  }
}

function decodeChallenge(token: string): LoginChallengePayload | null {
  const parsed = decodeSignedPayload(token);
  if (
    typeof parsed === "object" &&
    parsed !== null &&
    typeof (parsed as LoginChallengePayload).email === "string" &&
    typeof (parsed as LoginChallengePayload).hash === "string" &&
    typeof (parsed as LoginChallengePayload).expiresAt === "number" &&
    Number.isFinite((parsed as LoginChallengePayload).expiresAt)
  ) {
    return {
      email: (parsed as LoginChallengePayload).email,
      hash: (parsed as LoginChallengePayload).hash,
      expiresAt: (parsed as LoginChallengePayload).expiresAt,
    };
  }
  return null;
}

function decodeSession(token: string): LoginSessionPayload | null {
  const parsed = decodeSignedPayload(token);
  if (
    typeof parsed === "object" &&
    parsed !== null &&
    typeof (parsed as LoginSessionPayload).email === "string" &&
    typeof (parsed as LoginSessionPayload).issuedAt === "number" &&
    typeof (parsed as LoginSessionPayload).expiresAt === "number" &&
    Number.isFinite((parsed as LoginSessionPayload).issuedAt) &&
    Number.isFinite((parsed as LoginSessionPayload).expiresAt)
  ) {
    return {
      email: (parsed as LoginSessionPayload).email,
      issuedAt: (parsed as LoginSessionPayload).issuedAt,
      expiresAt: (parsed as LoginSessionPayload).expiresAt,
    };
  }
  return null;
}

function loginRateLimitPolicy(scope: LoginRateLimitScope): { windowSeconds: number; maxAttempts: number } {
  if (scope === "request-code") {
    return {
      windowSeconds: LOGIN_REQUEST_WINDOW_SECONDS,
      maxAttempts: LOGIN_REQUEST_MAX_ATTEMPTS,
    };
  }
  return {
    windowSeconds: LOGIN_VERIFY_WINDOW_SECONDS,
    maxAttempts: LOGIN_VERIFY_MAX_ATTEMPTS,
  };
}

function rateLimitBucket(key: string, now: number, windowMs: number): number[] {
  const cutoff = now - windowMs;
  return (RATE_LIMIT_STATE.get(key) ?? []).filter((timestamp) => timestamp >= cutoff);
}

function clientIpFromRequest(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded?.trim()) {
    return forwarded.split(",")[0].trim();
  }
  return request.headers.get("x-real-ip")?.trim() || "unknown";
}

export function checkLoginRateLimit(
  scope: LoginRateLimitScope,
  request: Request,
  email: string,
): LoginRateLimitResult {
  const { windowSeconds, maxAttempts } = loginRateLimitPolicy(scope);
  const windowMs = windowSeconds * 1000;
  const now = Date.now();
  const clientIp = clientIpFromRequest(request);
  const keys = [`${scope}:ip:${clientIp}`, `${scope}:email:${email}`];

  for (const key of keys) {
    const bucket = rateLimitBucket(key, now, windowMs);
    if (bucket.length >= maxAttempts) {
      RATE_LIMIT_STATE.set(key, bucket);
      return {
        ok: false,
        retryAfterSeconds: Math.max(Math.ceil((windowMs - (now - bucket[0])) / 1000), 1),
        error: "Too many login attempts. Try again later.",
      };
    }
  }

  for (const key of keys) {
    const bucket = rateLimitBucket(key, now, windowMs);
    bucket.push(now);
    RATE_LIMIT_STATE.set(key, bucket);
  }

  return { ok: true };
}

export function createLoginSession(email: string): string {
  const now = Date.now();
  return encodeSignedPayload({
    email,
    issuedAt: now,
    expiresAt: now + LOGIN_SESSION_TTL_SECONDS * 1000,
  });
}

function sessionRevokeBeforeMs(): number | null {
  const raw = process.env.NEPSIS_AUTH_SESSION_REVOKE_BEFORE?.trim();
  if (!raw) {
    return null;
  }
  const parsed = Date.parse(raw);
  if (!Number.isFinite(parsed)) {
    return Number.POSITIVE_INFINITY;
  }
  return parsed;
}

export function readNepsisUserFromCookieValue(token: string | null | undefined): string | null {
  if (!token) {
    return null;
  }
  let session: LoginSessionPayload | null;
  try {
    session = decodeSession(token);
  } catch {
    return null;
  }
  if (!session) {
    return null;
  }
  const email = normalizeEmail(session.email);
  if (!email) {
    return null;
  }
  if (Date.now() > session.expiresAt) {
    return null;
  }
  const revokeBefore = sessionRevokeBeforeMs();
  if (revokeBefore !== null && session.issuedAt < revokeBefore) {
    return null;
  }
  return email;
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
  return crypto.randomInt(100000, 1000000).toString();
}

export function hashLoginCode(email: string, code: string): string {
  return crypto.createHmac("sha256", authSecret()).update(`${email}\0${code.trim()}`).digest("base64url");
}

export function createLoginChallenge(email: string, code: string): string {
  return encodeSignedPayload({
    email,
    hash: hashLoginCode(email, code),
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
  if (challenge.hash !== hashLoginCode(email, code)) {
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
  return readNepsisUserFromCookieValue(readCookieFromHeader(cookieHeader, NEPSIS_USER_COOKIE));
}

export function cookieOptions(maxAge?: number) {
  const options = {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/",
  };
  if (typeof maxAge === "number") {
    return { ...options, maxAge };
  }
  return options;
}

async function sendWithResend(email: string, code: string): Promise<boolean> {
  const resendApiKey = process.env.RESEND_API_KEY?.trim();
  const from = process.env.NEPSIS_AUTH_FROM_EMAIL?.trim();
  if (!resendApiKey || !from || !loginEmailConfigured()) {
    return false;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), RESEND_REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch("https://api.resend.com/emails", {
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
      signal: controller.signal,
    });
  } catch (error) {
    if ((error as Error)?.name === "AbortError") {
      throw new Error("Email provider request timed out.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    throw new Error(`Email provider rejected request (${response.status}).`);
  }
  return true;
}

export async function deliverLoginCode(email: string, code: string): Promise<LoginCodeDelivery> {
  let deliveryError: string | null = null;
  try {
    if (await sendWithResend(email, code)) {
      return { delivery: "email" };
    }
  } catch (error) {
    deliveryError = (error as Error)?.message ?? "Login email delivery failed.";
  }

  if (previewCodesAllowed()) {
    if (deliveryError) {
      console.warn(`Nepsis login email unavailable for ${email}: ${deliveryError}`);
    }
    console.log(`Nepsis login code for ${email}: ${code}`);
    return { delivery: "preview", previewCode: code };
  }

  if (publicSiteMode()) {
    const publicMessage =
      "Login email delivery is required in public-site mode. Set RESEND_API_KEY and NEPSIS_AUTH_FROM_EMAIL.";
    return {
      delivery: "unavailable",
      error: deliveryError ? `${deliveryError} ${publicMessage}` : publicMessage,
    };
  }

  return {
    delivery: "unavailable",
    error: deliveryError
      ? `${deliveryError} Enable NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true for local-only testing without email delivery.`
      : "Login email delivery is not configured. Set RESEND_API_KEY and NEPSIS_AUTH_FROM_EMAIL, or enable NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true for local-only testing.",
  };
}
