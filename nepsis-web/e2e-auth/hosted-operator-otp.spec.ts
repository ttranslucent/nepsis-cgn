import { expect, test, type Page } from "@playwright/test";

const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;
const OPERATOR_EMAIL = "operator+hosted@example.com";
const LOGIN_CHALLENGE_COOKIE = "nepsis_login_challenge";
const SUPABASE_OTP_COOKIE = "nepsis_supabase_otp_sent";
const USER_COOKIE = "nepsis_user";
const CSRF_COOKIE = "nepsis_csrf";
const OTP_STUB_PORT = Number(process.env.PLAYWRIGHT_SUPABASE_OTP_PORT ?? 3102);
const OTP_STUB_URL = process.env.PLAYWRIGHT_SUPABASE_OTP_URL ?? `http://127.0.0.1:${OTP_STUB_PORT}`;

type OtpStubState = {
  email: string;
  newestCode: string | null;
  sendCount: number;
  verifyCount: number;
  sends: Array<{ code: string; body: Record<string, unknown> }>;
};

async function resetOtpStub() {
  const response = await fetch(`${OTP_STUB_URL}/_test/reset`, { method: "POST" });
  expect(response.ok).toBe(true);
}

async function otpState(email: string): Promise<OtpStubState> {
  const response = await fetch(`${OTP_STUB_URL}/_test/otp?email=${encodeURIComponent(email)}`);
  expect(response.ok).toBe(true);
  return response.json() as Promise<OtpStubState>;
}

async function readAuthSession(page: Page) {
  return page.evaluate(async () => {
    const response = await fetch("/api/auth/session", { cache: "no-store" });
    return response.json();
  });
}

async function expectNoCookie(page: Page, name: string) {
  const cookies = await page.context().cookies();
  expect(cookies.some((cookie) => cookie.name === name), name).toBe(false);
}

async function expectOtpSendCount(email: string, expectedCount: number) {
  await expect.poll(async () => (await otpState(email)).sendCount).toBe(expectedCount);
  return otpState(email);
}

async function requestCodeFromLogin(page: Page, email: string, expectedStatus: string) {
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByRole("status")).toContainText(expectedStatus);
}

// Regression for the July 7, 2026 hosted operator OTP fixes bbc2555 and 6de1f27.
test("hosted operator OTP reuses pending email unless a new email is explicitly requested", async ({
  page,
}) => {
  await resetOtpStub();

  await page.goto("/engine");
  await expect(page.getByText("Engine session controls are locked until you sign in.")).toBeVisible();
  await page.getByRole("link", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: /Login to NepsisCGN/i })).toBeVisible();

  await requestCodeFromLogin(
    page,
    OPERATOR_EMAIL,
    "If this address is authorized, check your inbox for the newest one-time code.",
  );
  const firstSend = await expectOtpSendCount(OPERATOR_EMAIL, 1);
  const firstCode = firstSend.newestCode;
  expect(firstCode).toMatch(/^\d{6}$/);
  expect(firstSend.sends[0]?.body).toMatchObject({ email: OPERATOR_EMAIL, create_user: false });
  await expectNoCookie(page, LOGIN_CHALLENGE_COOKIE);

  await page.getByRole("button", { name: "Use a different email" }).click();
  await requestCodeFromLogin(page, OPERATOR_EMAIL, "No new email was sent.");
  const reusedSend = await expectOtpSendCount(OPERATOR_EMAIL, 1);
  expect(reusedSend.newestCode).toBe(firstCode);

  await page.getByRole("button", { name: "Send a new email" }).click();
  await expect(page.getByRole("status")).toContainText(
    "If this address is authorized, check your inbox for the newest one-time code.",
  );
  const secondSend = await expectOtpSendCount(OPERATOR_EMAIL, 2);
  const newestCode = secondSend.newestCode;
  expect(newestCode).toMatch(/^\d{6}$/);
  expect(newestCode).not.toBe(firstCode);

  await page.getByLabel("Code").fill(firstCode ?? "");
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page.getByRole("status")).toContainText(
    "That code is invalid or was replaced by a newer email.",
  );
  await expectNoCookie(page, USER_COOKIE);

  await page.getByLabel("Code").fill(newestCode ?? "");
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page).toHaveURL(/\/engine$/);
  await expect(page.getByText(`signed in as ${OPERATOR_EMAIL}`)).toBeVisible();
  await expect(page.getByText("Engine session controls are locked until you sign in.")).not.toBeVisible();

  await expect.poll(() => readAuthSession(page)).toMatchObject({
    authenticated: true,
    engineControlAllowed: true,
    user: OPERATOR_EMAIL,
  });

  const cookies = await page.context().cookies();
  const sessionCookie = cookies.find((cookie) => cookie.name === USER_COOKIE);
  const csrfCookie = cookies.find((cookie) => cookie.name === CSRF_COOKIE);
  expect(sessionCookie).toBeTruthy();
  expect(sessionCookie?.httpOnly).toBe(true);
  expect(sessionCookie?.sameSite).toBe("Lax");
  expect(sessionCookie?.expires).toBeGreaterThan(
    Math.floor(Date.now() / 1000) + THIRTY_DAYS_SECONDS - 120,
  );
  expect(csrfCookie).toBeTruthy();
  expect(csrfCookie?.httpOnly).toBe(false);
  await expectNoCookie(page, LOGIN_CHALLENGE_COOKIE);
  await expectNoCookie(page, SUPABASE_OTP_COOKIE);

  await page.reload();
  await expect(page.getByText(`signed in as ${OPERATOR_EMAIL}`)).toBeVisible();
  await expect(page.getByText("Engine session controls are locked until you sign in.")).not.toBeVisible();

  const finalState = await otpState(OPERATOR_EMAIL);
  expect(finalState.sendCount).toBe(2);
  expect(finalState.verifyCount).toBe(2);
});
