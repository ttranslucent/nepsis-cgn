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

test("public responses include baseline browser security headers", async ({ request }) => {
  const response = await request.get("/mvp");

  expect(response.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(response.headers()["x-frame-options"]).toBe("DENY");
  expect(response.headers()["x-content-type-options"]).toBe("nosniff");
  expect(response.headers()["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(response.headers()["permissions-policy"]).toContain("camera=()");
});

test("public MVP can run without login or model key", async ({ page }) => {
  await page.goto("/mvp");
  await expect(
    page.getByRole("heading", { name: "Detect constraint violations before an AI answer commits." }),
  ).toBeVisible();
  await expect(
    page.getByText("RED \u2192 STILL \u2192 BLUE \u2192 STILL \u2192 commitment \u2192 state feedback \u2192 audit"),
  ).toBeVisible();
  await expect(page.getByLabel(/Visitor query/i)).toHaveCount(0);
  await page.getByRole("button", { name: "Run Demo" }).click();

  await expect(page.getByRole("region", { name: "Provenance topology" })).toBeVisible();
  await page.getByRole("button", { name: "Audit", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("nepsis.mvp_packet", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Evaluation axes", { exact: true })).toBeVisible();
  await expect(page.locator("main")).toContainText("action_priority");
  await expect(
    page.locator("p").filter({ hasText: "Canonical Jailing/Jingall case" }),
  ).toBeVisible();
  await expect(page.locator("p").filter({ hasText: "Do not accept JAILING." })).toBeVisible();
  await expect(page.getByText("Engine backend request failed", { exact: false })).toHaveCount(0);
});

test("public MVP toggles between provenance tabs", async ({ page }) => {
  await page.goto("/mvp");
  await expect(page.getByLabel(/Visitor query/i)).toHaveCount(0);
  await page.getByRole("button", { name: "Run Demo" }).click();

  await expect(page.getByRole("region", { name: "Provenance topology" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Topology" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("RED Channel", { exact: true })).toBeVisible();
  await expect(page.getByText("STILL Checkpoint", { exact: true })).toBeVisible();
  await expect(page.getByText("BLUE Channel", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /collapse Collapse/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /zeroback Validation/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /final Output/ })).toBeVisible();
  await expect(page.getByText("+ 3 hidden steps", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "Audit", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Audit", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Evaluation axes", { exact: true })).toBeVisible();
  await expect(page.getByText("Audit Trace", { exact: true })).toBeVisible();
  await expect(page.getByText("Raw JSON", { exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Provenance topology" })).toHaveCount(0);

  await page.getByRole("button", { name: "Lineage", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Lineage", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Replay hook not attached on public MVP.")).toBeVisible();

  await page.getByRole("button", { name: "Topology" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Topology" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("region", { name: "Provenance topology" })).toBeVisible();
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
  expect(payload.auth.allowedEmailsConfigured).toBe(false);
  expect(payload.auth.emailConfigured).toBe(false);
  expect(payload.auth.previewCodesEnabled).toBe(false);
  expect(payload.auth.operatorLoginReady).toBe(false);
  expect(payload.auth.persistentSessionDays).toBe(30);
  expect(payload.auth.sessionRevokeBeforeConfigured).toBe(false);
  expect(payload.models.enabled).toBe(false);
  expect(payload.models.hasServerOpenAiKey).toBe(false);
  expect(payload.mcp.local.available).toBe(true);
  expect(payload.mcp.local.command).toBe("nepsiscgn-mcp");
  expect(payload.mcp.local.transport).toBe("stdio");
  expect(payload.mcp.local.lifecycle).toContain("stateless packet-in/packet-out");
  expect(payload.mcp.hosted.available).toBe(false);
  expect(payload.mcp.hosted.deferred).toBe(true);
  expect(payload.mcp.hosted.requiresCapabilityToken).toBe(true);
  expect(payload.mcp.hosted.modelKeysRequired).toBe(false);
  expect(payload.setup.publicSite.ready).toBe(true);
  expect(payload.setup.publicSite.envExample).toBe("nepsis-web/.env.public.example");
  expect(payload.setup.publicSite.docs[0].href).toBe("docs/public-api.md#public-site-setup");
  expect(payload.setup.operatorMode.ready).toBe(false);
  expect(payload.setup.operatorMode.envExample).toBe("nepsis-web/.env.operator.example");
  expect(payload.setup.operatorMode.docs[0].href).toBe(
    "docs/operator-runbook.md#private-operator-deployment",
  );

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
        auth: {
          loginConfigured: false,
          allowedEmailsConfigured: false,
          emailConfigured: false,
          previewCodesEnabled: false,
          persistentSessionDays: 30,
          sessionRevokeBeforeConfigured: false,
        },
        models: { enabled: false, hasServerOpenAiKey: false },
        setup: {
          publicSite: {
            ready: true,
            envExample: "nepsis-web/.env.public.example",
            docs: [{ label: "Public site setup", href: "docs/public-api.md#public-site-setup" }],
            assertions: [
              {
                id: "public-site-mode",
                ok: true,
                label: "Public site mode active",
                detail: "The web deployment is rendering the frozen public /mvp posture.",
                env: ["NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true"],
              },
            ],
          },
          operatorMode: {
            ready: false,
            envExample: "nepsis-web/.env.operator.example",
            docs: [
              {
                label: "Private operator deployment",
                href: "docs/operator-runbook.md#private-operator-deployment",
              },
            ],
            assertions: [
              {
                id: "operator-mode",
                ok: false,
                label: "Private operator mode active",
                detail: "The deployment is explicitly configured as a live operator surface.",
                env: ["NEPSIS_DEPLOYMENT_MODE=operator"],
              },
            ],
          },
        },
        mcp: {
          discoverableMethods: ["initialize", "tools/list"],
          publicTools: [],
          protectedTools: [
            "run_mvp",
            "get_mvp_schema",
            "health",
            "get_routes",
            "start_operator_packet",
          ],
          operatorTools: ["start_operator_packet", "get_session_state", "lock_frame", "run_report"],
          local: {
            available: true,
            command: "nepsiscgn-mcp",
            transport: "stdio",
            modelKeysRequired: false,
            lifecycle: "stateless packet-in/packet-out; the model host stores the packet",
          },
          hosted: {
            available: false,
            endpoint: null,
            deferred: true,
            requiresCapabilityToken: true,
            capabilityTokenConfigured: false,
            modelKeysRequired: false,
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
  await expect(page.getByRole("heading", { name: "Public Site Setup" })).toBeVisible();
  await expect(page.getByText("Env example: nepsis-web/.env.public.example")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Private Operator Setup" })).toBeVisible();
  await expect(page.getByText("Env example: nepsis-web/.env.operator.example")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live Operator" })).toBeVisible();
  await expect(page.getByText("Live operator route is disabled.")).toBeVisible();
  await expect(page.getByText("Local MCP Bridge")).toBeVisible();
  await expect(page.getByText("Command: nepsiscgn-mcp")).toBeVisible();
  await expect(page.getByText("Hosted MCP Endpoint")).toBeVisible();
  await expect(page.getByText("Deferred until the backend endpoint is configured.")).toBeVisible();
  await expect(page.getByText("Tool calls require a Nepsis capability token.")).toBeVisible();
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
