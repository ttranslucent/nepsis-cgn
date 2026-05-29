import { expect, test } from "@playwright/test";

const THIRTY_DAYS_SECONDS = 60 * 60 * 24 * 30;

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
  await requestPreviewCode(page, "operator@example.com");
  await expect(page.getByLabel("Remember this device for 30 days")).toBeChecked();

  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page).toHaveURL(/\/engine$/);

  const session = await page.evaluate(async () => {
    const response = await fetch("/api/auth/session", { cache: "no-store" });
    return response.json();
  });
  expect(session).toMatchObject({
    authenticated: true,
    engineControlAllowed: true,
    user: "operator@example.com",
  });

  const sessionCookie = (await context.cookies()).find((cookie) => cookie.name === "nepsis_user");
  expect(sessionCookie).toBeTruthy();
  expect(sessionCookie?.httpOnly).toBe(true);
  expect(sessionCookie?.sameSite).toBe("Lax");
  expect(sessionCookie?.expires).toBeGreaterThan(Math.floor(Date.now() / 1000) + THIRTY_DAYS_SECONDS - 120);
  expect(sessionCookie?.expires).toBeLessThan(Math.floor(Date.now() / 1000) + THIRTY_DAYS_SECONDS + 120);
});

test("signed-in operator can open live operator route", async ({ page }) => {
  await requestPreviewCode(page, "operator@example.com");
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page).toHaveURL(/\/engine$/);

  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: /Live Operator Workspace/i })).toBeVisible();
  await expect(page.getByText(/Live mode/i)).toBeVisible();
});

test("non-allowlisted email does not receive a preview OTP", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("visitor@example.com");
  await page.getByRole("button", { name: "Send code" }).click();

  const status = page.getByRole("status");
  await expect(status).toContainText("If this address is authorized");
  await expect(status).not.toContainText("Use this one-time code");
  await expect(page.getByLabel("Code")).toHaveValue("");
});
