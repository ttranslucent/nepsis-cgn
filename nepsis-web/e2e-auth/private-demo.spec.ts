import { expect, test } from "@playwright/test";

function privateDemoPacket() {
  return {
    schema_id: "nepsis.private_demo_runtime_packet",
    schema_version: "0.1.0",
    runtime: "nepsis-cgn.operator_packet",
    mode: "external-private-runtime",
    generated_at: "2026-06-21T12:00:00.000+00:00",
    case_id: "jailing",
    thread_id: "private-demo-playwright",
    user_id: "operator@example.com",
    no_phi_acknowledged: true,
    prompt_hash: "sha256:playwright",
    prompt_excerpt: "No PHI prompt",
    summary: "NepsisCGN private runtime completed a RED before BLUE operator-packet pass.",
    case_reasoning_compiler: {
      schema_id: "nepsis.case_reasoning_compiler",
      compiler_valid: true,
      compiler_source: "deterministic",
      input_frame_id: "frame-playwright",
      input_prompt_hash: "sha256:playwright",
      recommended_threshold_action: "escalate_red",
      validation_errors: [],
      validation_warnings: [],
      domain_red_hazard: { hazard: "token mismatch" },
    },
    operator_packet: {
      schema_id: "nepsis.operator_packet",
      schema_version: "0.1.0",
      packet_id: "operator-playwright",
      loop_id: "loop-playwright",
      created_at: "2026-06-21T12:00:00.000+00:00",
      phase: "threshold_set",
      family: "safety",
      frame: {},
      governance_costs: {},
      governance_calibration: {},
      audit_trace: [],
      legal_next_tools: ["commit_iteration", "abandon_packet"],
      latest_audit: {},
      latest_step: null,
      last_commit_packet: null,
      last_abandoned_packet: null,
      previous_trace: [],
    },
    audit_trace: [
      { event: "LOCK_FRAME", arguments: {} },
      { event: "RUN_REPORT", arguments: {} },
      { event: "LOCK_REPORT", arguments: {} },
      {
        event: "SET_THRESHOLD_DECISION",
        arguments: { decision: "hold", hold_reason: "RED remains open." },
      },
    ],
    latest_audit: {
      threshold: {
        status: "PASS",
        packet: {
          gate_crossed: true,
          warning_level: "red",
          recommendation: "escalate_red",
          recommended_threshold_action: "escalate_red",
        },
      },
    },
  };
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        authenticated: true,
        engineControlAllowed: true,
        user: "operator@example.com",
      }),
    });
  });

  await page.route("**/api/engine/private-demo", async (route) => {
    const request = route.request();
    const body = request.postDataJSON();
    expect(body.prompt).toContain("No PHI");
    expect(body.no_phi_acknowledged).toBe(true);
    expect(body.case_id).toBe("jailing");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(privateDemoPacket()),
    });
  });
});

test("authenticated operator can run private demo and inspect packet views", async ({ page }) => {
  await page.goto("/private-demo");

  await expect(page.getByRole("heading", { name: /Private Demo Runtime/i })).toBeVisible();
  await page.getByLabel(/No-PHI prompt/i).fill("No PHI. JINGALL must not collapse into JAILING without packet audit.");
  await page.getByLabel(/Case ID/i).fill("jailing");
  await page.getByLabel(/I confirm this prompt contains no PHI/i).check();
  await page.getByRole("button", { name: /Run Private Demo/i }).click();

  await expect(page.getByText("nepsis.private_demo_runtime_packet")).toBeVisible();
  await expect(page.getByText("LOCK_FRAME")).toBeVisible();
  await expect(page.getByText("SET_THRESHOLD_DECISION")).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Private demo topology" }).getByText("escalate_red").first(),
  ).toBeVisible();

  await page.getByRole("button", { name: "Audit" }).click();
  await expect(page.getByRole("region", { name: "Private demo audit" })).toBeVisible();

  await page.getByRole("button", { name: "Lineage" }).click();
  await expect(page.getByText("operator-playwright")).toBeVisible();

  await page.getByRole("button", { name: "Compiler" }).click();
  await expect(page.getByRole("region", { name: "Case reasoning compiler" })).toBeVisible();

  await page.getByRole("button", { name: "Raw" }).click();
  await expect(page.getByText('"schema_id": "nepsis.private_demo_runtime_packet"')).toBeVisible();
});

test("anonymous engine-control sessions cannot run private demo", async ({ page }) => {
  let privateDemoCalled = false;

  await page.route("**/api/auth/session", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ authenticated: false, engineControlAllowed: true, user: null }),
    });
  });
  await page.route("**/api/engine/private-demo", async (route) => {
    privateDemoCalled = true;
    await route.fulfill({ status: 500, body: "private demo should not be called" });
  });

  await page.goto("/private-demo");

  await expect(page.getByRole("heading", { name: /Private demo access required/i })).toBeVisible();
  await expect(page.getByRole("textbox", { name: /No-PHI prompt/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Run Private Demo/i })).toHaveCount(0);
  expect(privateDemoCalled).toBe(false);
});
