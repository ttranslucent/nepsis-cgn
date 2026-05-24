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
  await expect(
    page.getByRole("heading", { name: "Detect constraint violations before an AI answer commits." }),
  ).toBeVisible();
  await expect(page.getByText("RED → STILL → BLUE → STILL → commitment → state feedback → audit")).toBeVisible();
  await page.getByLabel(/Visitor query/i).fill("Source says JINGALL, but a model answered JAILING.");
  await page.getByRole("button", { name: "Run Query" }).click();

  await expect(page.getByRole("region", { name: "Visual topology" })).toBeVisible();
  await page.getByRole("button", { name: "Full View" }).click();
  await expect(page.getByText("nepsis.mvp_packet", { exact: true })).toBeVisible();
  await expect(page.getByText("Evaluation axes", { exact: true })).toBeVisible();
  await expect(page.locator("main")).toContainText("action_priority");
  await expect(
    page.locator("p").filter({ hasText: "Source says JINGALL, but a model answered JAILING." }),
  ).toBeVisible();
  await expect(page.locator("p").filter({ hasText: "Do not accept JAILING." })).toBeVisible();
  await expect(page.getByText("Engine backend request failed", { exact: false })).toHaveCount(0);
});

test("public MVP toggles between visual topology and full view", async ({ page }) => {
  await page.goto("/mvp");
  await page.getByLabel(/Visitor query/i).fill("Source says JINGALL, but a model answered JAILING.");
  await page.getByRole("button", { name: "Run Query" }).click();

  await expect(page.getByRole("region", { name: "Visual topology" })).toBeVisible();
  await expect(page.getByText("What it checked", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("What it found", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("What changed", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Visual Topology" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("RED Channel", { exact: true })).toBeVisible();
  await expect(page.getByText("STILL 1", { exact: true })).toBeVisible();
  await expect(page.getByText("BLUE Channel", { exact: true })).toBeVisible();
  await expect(page.getByText("STILL 2", { exact: true })).toBeVisible();
  await expect(page.getByText("Commitment", { exact: true })).toBeVisible();
  await expect(page.getByText("State feedback", { exact: true })).toBeVisible();
  await expect(page.getByText("Audit", { exact: true })).toBeVisible();
  const topologyText = await page.getByRole("region", { name: "Visual topology" }).innerText();
  expect(topologyText.indexOf("Packet lineage")).toBeLessThan(topologyText.indexOf("RED Channel"));
  await expect(page.getByText("Constraint conflict detected", { exact: true })).toBeVisible();
  await expect(page.getByText("Retessellation required", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Full View" }).click();
  await expect(page.getByRole("button", { name: "Full View" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Evaluation axes", { exact: true })).toBeVisible();
  await expect(page.getByText("Audit Trace", { exact: true })).toBeVisible();
  await expect(page.getByText("Raw JSON", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Visual topology" })).toHaveCount(0);

  await page.getByRole("button", { name: "Visual Topology" }).click();
  await expect(page.getByRole("button", { name: "Visual Topology" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("region", { name: "Visual topology" })).toBeVisible();
});

test("public MVP visitor query changes packet details in bundled fallback", async ({ page }) => {
  await page.goto("/mvp");
  await page.getByLabel(/Visitor query/i).fill("Compare source VIREN against candidate VIRAL before accepting.");
  await page.getByRole("button", { name: "Run Query" }).click();

  await expect(page.getByRole("region", { name: "Visual topology" })).toBeVisible();
  await expect(page.locator("main")).toContainText("Reject VIRAL");
  await expect(page.locator("main")).toContainText("preserve VIREN");

  await page.getByRole("button", { name: "Full View" }).click();
  await expect(page.locator("main")).toContainText("source_token=VIREN");
  await expect(page.locator("main")).toContainText("candidate_token=VIRAL");
  await expect(page.locator("main")).toContainText("Do not accept VIRAL. Return or preserve VIREN");
  await expect(page.locator("main")).not.toContainText("source_token=JINGALL");
  await expect(page.locator("main")).not.toContainText("candidate_token=JAILING");
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

test("public live operator route is labeled and gated", async ({ page }) => {
  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: /Operator access required/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Run MVP Demo/i })).toBeVisible();
  await expect(page.getByLabel(/OpenAI API Key/i)).toHaveCount(0);
  await expect(page.getByText(/deterministic MVP demo remains available/i)).toBeVisible();
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
  expect(payload.auth.loginConfigured).toBe(true);
  expect(payload.auth.emailConfigured).toBe(false);
  expect(payload.auth.previewCodesEnabled).toBe(false);
  expect(payload.auth.operatorLoginReady).toBe(false);
  expect(payload.models.enabled).toBe(false);
  expect(payload.models.hasServerOpenAiKey).toBe(false);
  expect(payload.mcp.local.available).toBe(true);
  expect(payload.mcp.local.command).toBe("nepsiscgn-mcp");
  expect(payload.mcp.local.transport).toBe("stdio");
  expect(payload.mcp.hosted.available).toBe(false);
  expect(payload.mcp.hosted.deferred).toBe(true);

  const engineHealth = await request.get("/api/engine/health");
  expect(engineHealth.ok()).toBeTruthy();
  const engineHealthPayload = await engineHealth.json();
  expect(engineHealthPayload.ok).toBe(false);
  expect(engineHealthPayload.configured).toBe(false);
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
        operator: {
          enabled: false,
          operatorSiteMode: false,
          path: "/operator",
          backendReady: false,
          authReady: false,
          modelReady: false,
        },
        auth: { loginConfigured: false, emailConfigured: false, previewCodesEnabled: false },
        models: { enabled: false, hasServerOpenAiKey: false },
        mcp: {
          publicTools: ["run_mvp", "health", "get_mvp_schema"],
          operatorTools: ["get_session_state", "lock_frame", "run_report"],
          local: {
            available: true,
            command: "nepsiscgn-mcp",
            transport: "stdio",
            modelKeysRequired: false,
          },
          hosted: {
            available: false,
            endpoint: null,
            deferred: true,
          },
        },
      }),
    });
  });

  await page.goto("/status");
  await expect(page.getByRole("heading", { name: /System Status/i })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Public MVP" })).toBeVisible();
  await expect(page.getByText("nepsis.mvp_packet")).toBeVisible();
  await expect(page.getByText("No login required")).toBeVisible();
  await expect(page.getByText("Backend API")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live Operator" })).toBeVisible();
  await expect(page.getByText("Live operator route is disabled.")).toBeVisible();
  await expect(page.getByText("Local MCP Bridge")).toBeVisible();
  await expect(page.getByText("Command: nepsiscgn-mcp")).toBeVisible();
  await expect(page.getByText("Hosted MCP Endpoint")).toBeVisible();
  await expect(page.getByText("Deferred until backend auth and deployment are configured.")).toBeVisible();
  await expect(page.getByText("No server OpenAI key configured")).toBeVisible();

  const operatorLogin = page.locator("section").filter({
    has: page.getByRole("heading", { name: "Operator Login" }),
  });
  await expect(operatorLogin).toContainText("needs setup");
  await expect(operatorLogin).toContainText("Auth secret missing.");
  await expect(operatorLogin).toContainText("Email login not configured.");
});

test("public login fails closed without email delivery config", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: /Login to NepsisCGN/i })).toBeVisible();

  await page.getByLabel("Email").fill("operator@example.com");
  await page.getByRole("button", { name: "Send code" }).click();

  await expect(page.getByRole("status")).toContainText("Login email delivery is required in public-site mode");
  await expect(page.getByRole("status")).not.toContainText("one-time code");
});
