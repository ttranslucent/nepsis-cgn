import { expect, test } from "@playwright/test";

test("preview-code login verifies and unlocks operator session controls", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /Login to NepsisCGN/i })).toBeVisible();

  await page.getByLabel("Email").fill("operator@example.com");
  await page.getByRole("button", { name: "Send code" }).click();

  const status = page.getByRole("status");
  await expect(status).toContainText("Use this one-time code");
  const statusText = await status.textContent();
  const previewCode = statusText?.match(/\b\d{6}\b/)?.[0];
  expect(previewCode).toBeTruthy();
  await expect(page.getByLabel("Code")).toHaveValue(previewCode ?? "");

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
});

test("signed-in operator can open live operator route", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("operator@example.com");
  await page.getByRole("button", { name: "Send code" }).click();
  const statusText = await page.getByRole("status").textContent();
  const previewCode = statusText?.match(/\b\d{6}\b/)?.[0];
  expect(previewCode).toBeTruthy();
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page).toHaveURL(/\/engine$/);

  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: /Live Operator Workspace/i })).toBeVisible();
  await expect(page.getByText(/Live mode/i)).toBeVisible();
});
