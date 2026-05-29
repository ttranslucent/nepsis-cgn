import crypto from "crypto";
import { expect, test, type BrowserContext, type Page } from "@playwright/test";

const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;
const AUTH_SECRET = "playwright-preview-auth-secret";
const SESSION_REVOKE_BEFORE_MS = Date.parse("2001-01-01T00:00:00.000Z");
const OPERATOR_EMAIL = "operator@example.com";
const LOGOUT_OPERATOR_EMAIL = "operator+logout@example.com";
const SESSION_COOKIE_OPERATOR_EMAIL = "operator+session-cookie@example.com";
const REVOKED_OPERATOR_EMAIL = "operator+revoked@example.com";
const INVALID_CODE_OPERATOR_EMAIL = "operator+invalid-code@example.com";
const EXPIRED_CODE_OPERATOR_EMAIL = "operator+expired-code@example.com";

async function useIsolatedRateLimitBucket(page: Page, label: string) {
  await page.context().setExtraHTTPHeaders({
    "x-forwarded-for": `auth-flow-${test.info().workerIndex}-${label}`,
  });
}

function signAuthPayload(payload: object): string {
  const encoded = Buffer.from(JSON.stringify(payload), "utf-8").toString("base64url");
  const signature = crypto.createHmac("sha256", AUTH_SECRET).update(encoded).digest("base64url");
  return `${encoded}.${signature}`;
}

function hashLoginCode(email: string, code: string): string {
  return crypto.createHmac("sha256", AUTH_SECRET).update(`${email}\0${code.trim()}`).digest("base64url");
}

function createSignedSession(email: string, issuedAt: number, expiresAt: number): string {
  return signAuthPayload({ email, issuedAt, expiresAt });
}

function createSignedChallenge(email: string, code: string, expiresAt: number): string {
  return signAuthPayload({
    email,
    hash: hashLoginCode(email, code),
    expiresAt,
  });
}

async function readAuthSession(page: Page) {
  return page.evaluate(async () => {
    const response = await fetch("/api/auth/session", { cache: "no-store" });
    return response.json();
  });
}

async function expectLoggedOutSession(page: Page) {
  await expect.poll(() => readAuthSession(page)).toMatchObject({
    authenticated: false,
    engineControlAllowed: false,
    user: null,
  });
}

async function expectEngineAccessLocked(page: Page) {
  await page.goto("/engine");
  await expect(page.getByText("Engine session controls are locked until you sign in.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Sign In" })).toBeVisible();
}

async function addAuthCookie(
  context: BrowserContext,
  baseURL: string | undefined,
  name: string,
  value: string,
  expires: number,
) {
  expect(baseURL).toBeTruthy();
  await context.addCookies([
    {
      name,
      value,
      url: baseURL ?? "http://127.0.0.1:3101",
      httpOnly: true,
      sameSite: "Lax",
      secure: false,
      expires,
    },
  ]);
}

async function requestPreviewCode(page: import("@playwright/test").Page, email: string) {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /Login to NepsisCGN/i })).toBeVisible();

  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send code" }).click();

  const status = page.getByRole("status");
  await expect(status).toContainText("Use this one-time code");
  const statusText = await status.textContent();
  const previewCode = statusText?.match(/\b\d{6}\b/)?.[0];
  expect(previewCode).toBeTruthy();
  await expect(page.getByLabel("Code")).toHaveValue(previewCode ?? "");
  return previewCode ?? "";
}

test("allowed operator OTP verifies and creates a 30-day remembered session", async ({ page, context }) => {
  await useIsolatedRateLimitBucket(page, "remembered-session");
  await requestPreviewCode(page, OPERATOR_EMAIL);
  await expect(page.getByLabel("Remember this device for 30 days")).toBeChecked();

  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page).toHaveURL(/\/engine$/);

  const session = await readAuthSession(page);
  expect(session).toMatchObject({
    authenticated: true,
    engineControlAllowed: true,
    user: OPERATOR_EMAIL,
  });

  const sessionCookie = (await context.cookies()).find((cookie) => cookie.name === "nepsis_user");
  expect(sessionCookie).toBeTruthy();
  expect(sessionCookie?.httpOnly).toBe(true);
  expect(sessionCookie?.sameSite).toBe("Lax");
  expect(sessionCookie?.expires).toBeGreaterThan(Math.floor(Date.now() / 1000) + THIRTY_DAYS_SECONDS - 120);
  expect(sessionCookie?.expires).toBeLessThan(Math.floor(Date.now() / 1000) + THIRTY_DAYS_SECONDS + 120);
});

test("signed-in operator can open live operator route", async ({ page }) => {
  await useIsolatedRateLimitBucket(page, "live-operator-route");
  await requestPreviewCode(page, OPERATOR_EMAIL);
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page).toHaveURL(/\/engine$/);

  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: /Live Operator Workspace/i })).toBeVisible();
  await expect(page.getByText(/Live mode/i)).toBeVisible();
});

test("non-allowlisted email does not receive a preview OTP", async ({ page }) => {
  await useIsolatedRateLimitBucket(page, "non-allowlisted");
  await page.goto("/login");
  await page.getByLabel("Email").fill("visitor@example.com");
  await page.getByRole("button", { name: "Send code" }).click();

  const status = page.getByRole("status");
  await expect(status).toContainText("If this address is authorized");
  await expect(status).not.toContainText("Use this one-time code");
  await expect(page.getByLabel("Code")).toHaveValue("");
});

test("logout clears session and challenge cookies and locks engine access again", async ({ page, context }) => {
  await useIsolatedRateLimitBucket(page, "logout");
  await requestPreviewCode(page, LOGOUT_OPERATOR_EMAIL);
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page).toHaveURL(/\/engine$/);

  await page.evaluate(async (email) => {
    const response = await fetch("/api/auth/request-code", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    if (!response.ok) {
      throw new Error(`request-code failed with ${response.status}`);
    }
  }, LOGOUT_OPERATOR_EMAIL);

  let cookieNames = (await context.cookies()).map((cookie) => cookie.name);
  expect(cookieNames).toContain("nepsis_user");
  expect(cookieNames).toContain("nepsis_login_challenge");

  await page.getByRole("button", { name: "Logout" }).click();
  await expect(page).toHaveURL(/\/login$/);

  cookieNames = (await context.cookies()).map((cookie) => cookie.name);
  expect(cookieNames).not.toContain("nepsis_user");
  expect(cookieNames).not.toContain("nepsis_login_challenge");
  await expectLoggedOutSession(page);
  await expectEngineAccessLocked(page);
});

test("rememberDevice=false creates a browser-session auth cookie", async ({ page, context }) => {
  await useIsolatedRateLimitBucket(page, "session-cookie");
  await requestPreviewCode(page, SESSION_COOKIE_OPERATOR_EMAIL);
  await page.getByLabel("Remember this device for 30 days").uncheck();
  await expect(page.getByLabel("Remember this device for 30 days")).not.toBeChecked();

  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page).toHaveURL(/\/engine$/);

  const sessionCookie = (await context.cookies()).find((cookie) => cookie.name === "nepsis_user");
  expect(sessionCookie).toBeTruthy();
  expect(sessionCookie?.httpOnly).toBe(true);
  expect(sessionCookie?.sameSite).toBe("Lax");
  expect(sessionCookie?.expires).toBe(-1);
});

test("session revoke cutoff invalidates older remembered sessions", async ({ page, context, baseURL }) => {
  await page.goto("/login");
  const expiresAt = Date.now() + THIRTY_DAYS_SECONDS * 1000;
  const oldSession = createSignedSession(
    REVOKED_OPERATOR_EMAIL,
    SESSION_REVOKE_BEFORE_MS - 1000,
    expiresAt,
  );
  await addAuthCookie(
    context,
    baseURL,
    "nepsis_user",
    oldSession,
    Math.floor(expiresAt / 1000),
  );

  await expectLoggedOutSession(page);
  await expectEngineAccessLocked(page);
});

test("invalid OTP code fails closed without granting engine access", async ({ page, context }) => {
  await useIsolatedRateLimitBucket(page, "invalid-code");
  await requestPreviewCode(page, INVALID_CODE_OPERATOR_EMAIL);
  await page.getByLabel("Code").fill("000000");
  await page.getByRole("button", { name: "Verify & continue" }).click();

  await expect(page.getByRole("status")).toContainText("Invalid code");
  const cookieNames = (await context.cookies()).map((cookie) => cookie.name);
  expect(cookieNames).not.toContain("nepsis_user");
  await expectLoggedOutSession(page);
  await expectEngineAccessLocked(page);
});

test("expired OTP challenge fails closed without granting engine access", async ({ page, context, baseURL }) => {
  await useIsolatedRateLimitBucket(page, "expired-code");
  await page.goto("/login");
  const code = "123456";
  const expiredChallenge = createSignedChallenge(
    EXPIRED_CODE_OPERATOR_EMAIL,
    code,
    Date.now() - 1000,
  );
  await addAuthCookie(
    context,
    baseURL,
    "nepsis_login_challenge",
    expiredChallenge,
    Math.floor(Date.now() / 1000) + 60,
  );

  const result = await page.evaluate(
    async ({ email, code }) => {
      const response = await fetch("/api/auth/verify-code", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code, rememberDevice: true }),
      });
      return { status: response.status, body: await response.json() };
    },
    { email: EXPIRED_CODE_OPERATOR_EMAIL, code },
  );

  expect(result.status).toBe(400);
  expect(result.body).toMatchObject({ error: "Code expired or not found" });
  const cookieNames = (await context.cookies()).map((cookie) => cookie.name);
  expect(cookieNames).not.toContain("nepsis_user");
  expect(cookieNames).not.toContain("nepsis_login_challenge");
  await expectLoggedOutSession(page);
  await expectEngineAccessLocked(page);
});
