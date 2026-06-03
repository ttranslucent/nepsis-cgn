import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: false, engineControlAllowed: false, user: null }),
    });
  });
});

async function runMvp(page: Page) {
  await page.goto("/mvp");
  await expect(page.getByLabel(/Visitor query/i)).toHaveCount(0);
  await page.getByRole("button", { name: "Run Demo" }).click();
}

test("public MVP exposes deterministic provenance topology, audit drawer, and replay stub", async ({ page }) => {
  await runMvp(page);

  await expect(page.getByRole("button", { name: "Topology" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("button", { name: "Audit", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Lineage" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Provenance topology" })).toBeVisible();

  await page.getByRole("button", { name: "Focus RED" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /RED Channel/ })).toBeFocused();

  await expect(page.getByText("det_call_red_001", { exact: true }).nth(1)).toBeVisible();
  await expect(page.getByRole("button", { name: "Open audit trail" }).first()).toBeVisible();

  await page.getByRole("button", { name: /RED Channel/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("complementary", { name: "Audit trail drawer" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Summary" })).toHaveAttribute("aria-selected", "true");

  await page.getByRole("tab", { name: "Raw Trace" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("nepsis.mvp_packet", { exact: true }).first()).toBeVisible();
  await expect(
    page.getByRole("complementary", { name: "Audit trail drawer" }).getByText("det_call_red_001", { exact: true }),
  ).toBeVisible();

  await page.getByRole("tab", { name: "Diff" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("No prior packet available for deterministic diff.")).toBeVisible();

  await page.getByRole("tab", { name: "Replay" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Replay hook not attached on public MVP.")).toBeVisible();
});

test("public MVP tracks previous deterministic packet for provenance diff", async ({ page }) => {
  await runMvp(page);
  await page.getByRole("button", { name: /Clinical/ }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "Run Demo" }).focus();
  await page.keyboard.press("Enter");

  await page.getByRole("button", { name: "Audit", exact: true }).focus();
  await page.keyboard.press("Enter");
  await page.getByRole("tab", { name: "Diff" }).focus();
  await page.keyboard.press("Enter");

  await expect(page.getByText("Changed fields")).toBeVisible();
  await expect(page.getByText("input_text", { exact: true })).toBeVisible();
  await expect(page.getByText("contradiction_density", { exact: true })).toBeVisible();
});
