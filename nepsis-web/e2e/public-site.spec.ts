import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: false, engineControlAllowed: false, user: null }),
    });
  });
});

test("public MVP can run without login or model key", async ({ page }) => {
  await page.goto("/mvp");
  await expect(page.getByRole("heading", { name: /RED/i })).toBeVisible();
  await page.getByLabel(/Visitor query/i).fill("Source says JINGALL, but a model answered JAILING.");
  await page.getByRole("button", { name: "Run Query" }).click();

  await expect(page.getByRole("region", { name: "Visual topology mode" })).toBeVisible();
  await page.getByRole("button", { name: "Telemetry" }).click();
  await expect(page.getByText("nepsis.mvp_packet", { exact: true })).toBeVisible();
  await expect(page.getByText("Evaluation axes", { exact: true })).toBeVisible();
  await expect(page.locator("main")).toContainText("action_priority");
  await expect(
    page.locator("p").filter({ hasText: "Source says JINGALL, but a model answered JAILING." }),
  ).toBeVisible();
  await expect(page.locator("p").filter({ hasText: "Do not accept JAILING." })).toBeVisible();
  await expect(page.getByText("Engine backend request failed", { exact: false })).toHaveCount(0);
});

test("public MVP exposes topology mode before raw telemetry", async ({ page }) => {
  await page.goto("/mvp");
  await page.getByLabel(/Visitor query/i).fill("Source says JINGALL, but a model answered JAILING.");
  await page.getByRole("button", { name: "Run Query" }).click();

  await expect(page.getByRole("region", { name: "Visual topology mode" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Topology" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("RED Channel", { exact: true })).toBeVisible();
  await expect(page.getByText("STILL 1", { exact: true })).toBeVisible();
  await expect(page.getByText("BLUE Channel", { exact: true })).toBeVisible();
  await expect(page.getByText("STILL 2", { exact: true })).toBeVisible();
  await expect(page.getByText("Commitment", { exact: true })).toBeVisible();
  await expect(page.getByText("State feedback", { exact: true })).toBeVisible();
  await expect(page.getByText("Audit", { exact: true })).toBeVisible();
  await expect(page.getByText("Constraint conflict detected", { exact: true })).toBeVisible();
  await expect(page.getByText("Retessellation required", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Telemetry" }).click();
  await expect(page.getByRole("button", { name: "Telemetry" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Evaluation axes", { exact: true })).toBeVisible();
  await expect(page.getByText("Raw JSON", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Visual topology mode" })).toHaveCount(0);

  await page.getByRole("button", { name: "Topology" }).click();
  await expect(page.getByRole("region", { name: "Visual topology mode" })).toBeVisible();
});

test("public operator routes are gated and do not ask for browser API keys", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: /Operator settings/i })).toBeVisible();
  await expect(page.getByText(/API keys are disabled/i)).toBeVisible();
  await expect(page.getByLabel(/OpenAI API Key/i)).toHaveCount(0);

  await page.goto("/playground");
  await expect(page.getByRole("heading", { name: /Playground locked/i })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);

  await page.goto("/engine");
  await expect(page.getByRole("heading", { name: /Operator access required/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Run MVP Demo/i })).toBeVisible();
});

test("public model API routes are disabled without provider keys", async ({ request }) => {
  const playgroundStatus = await request.get("/api/playground-nepsis");
  expect(playgroundStatus.ok()).toBeTruthy();
  const playgroundPayload = await playgroundStatus.json();
  expect(playgroundPayload.modelRoutesEnabled).toBe(false);
  expect(playgroundPayload.hasServerKey).toBe(false);
  expect(typeof playgroundPayload.defaultModel).toBe("string");

  const playgroundRun = await request.post("/api/playground-nepsis", {
    data: { prompt: "smoke", packId: "jailing_jingall" },
  });
  expect(playgroundRun.status()).toBe(403);

  const detachedRun = await request.post("/api/run-with-nepsis", {
    data: { prompt: "smoke" },
  });
  expect(detachedRun.status()).toBe(403);
});

test("status API reports bundled MVP available without backend env", async ({ request }) => {
  const response = await request.get("/api/status");
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();

  expect(payload.backend.configured).toBe(false);
  expect(payload.mvp.available).toBe(true);
  expect(payload.mvp.schemaId).toBe("nepsis.mvp_packet");
  expect(payload.mvp.noLoginRequired).toBe(true);
  expect(payload.models.enabled).toBe(false);
  expect(payload.models.hasServerOpenAiKey).toBe(false);
});

test("status page exposes safe public system posture", async ({ page }) => {
  await page.route("**/api/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        backend: { configured: false, reachable: false },
        mvp: {
          available: true,
          status: 200,
          schemaId: "nepsis.mvp_packet",
          noLoginRequired: true,
        },
        auth: { loginConfigured: false, previewCodesEnabled: false },
        models: { enabled: false, hasServerOpenAiKey: false },
        mcp: { available: true, publicTools: ["run_mvp", "health", "get_mvp_schema"] },
      }),
    });
  });

  await page.goto("/status");
  await expect(page.getByRole("heading", { name: /System Status/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Public MVP" })).toBeVisible();
  await expect(page.getByText("nepsis.mvp_packet")).toBeVisible();
  await expect(page.getByText("No login required")).toBeVisible();
  await expect(page.getByText("Backend API")).toBeVisible();
  await expect(page.getByText("MCP Tools")).toBeVisible();
  await expect(page.getByText("No server OpenAI key configured")).toBeVisible();
});
