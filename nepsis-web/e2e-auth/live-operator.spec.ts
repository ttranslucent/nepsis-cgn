import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill("operator@example.com");
  await page.getByRole("button", { name: "Send code" }).click();
  const statusText = await page.getByRole("status").textContent();
  const previewCode = statusText?.match(/\b\d{6}\b/)?.[0] ?? "";
  await page.getByLabel("Code").fill(previewCode);
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await expect(page).toHaveURL(/\/engine$/);
}

function packetStub(
  phase: string,
  lastEvent: string,
  frame: Record<string, unknown> = {},
) {
  return {
    schema_id: "nepsis.operator_packet",
    schema_version: "2.1.0",
    packet_id: `packet-${phase}`,
    loop_id: "loop-1",
    created_at: new Date().toISOString(),
    phase,
    family: "safety",
    frame,
    governance_costs: { c_fp: 1, c_fn: 9 },
    governance_calibration: null,
    manifest_path: null,
    audit_trace: [{ event: lastEvent, arguments: {} }],
    legal_next_tools: ["run_report", "abandon_packet"],
    latest_audit: {},
    latest_step: null,
    last_commit_packet: null,
    last_abandoned_packet: null,
    previous_trace: [],
    policy: {},
    integrity: {
      seal_version: "hmac-sha256:v1",
      counter: 1,
      sealed_fields: [],
      seal: "test",
    },
  };
}

test("field assist requires explicit acceptance, supports editing, and sends verified dispositions", async ({
  page,
}) => {
  const packetCalls: Array<Record<string, unknown>> = [];

  await page.route("**/api/engine/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ok: true }),
    });
  });
  await page.route("**/api/engine/sessions", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ sessions: [] }),
    });
  });
  await page.route("**/api/operator/model", async (route) => {
    const request = route.request();
    expect(request.method()).toBe("POST");
    const payload = await request.postDataJSON();
    expect(payload.mode).toBe("suggest_field");
    expect(payload.target).toBe("frame.constraints_hard");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        mode: "suggest_field",
        model: "gpt-4.1-mini",
        outputText: "Candidate hard constraint ready for review.",
        suggestions: [
          {
            id: "test-hard-constraint",
            target: "frame.constraints_hard",
            title: "Preserve RED gate",
            proposedValue: ["Maintain RED before BLUE sequencing."],
            rationale: "Hard safety gates must stay before optimization.",
            riskNote: "Operator must confirm this applies to the current frame.",
          },
        ],
      }),
    });
  });
  await page.route("**/api/engine/operator-packet/start", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(packetStub("frame_draft", "START")),
    });
  });
  await page.route("**/api/engine/operator-packet/frame", async (route) => {
    const payload = await route.request().postDataJSON();
    packetCalls.push(payload);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(packetStub("frame_locked", "LOCK_FRAME", payload.frame)),
    });
  });

  await login(page);
  await page.goto("/operator");

  await page.getByRole("textbox", { name: /Frame question/i }).fill("Decide whether to escalate a safety incident.");
  await page
    .getByRole("textbox", { name: /Key uncertainty/i })
    .fill("Whether the first report reflects a real critical signal.");
  await page.getByRole("textbox", { name: /Red channel definition/i }).fill("Missing a catastrophic incident.");
  await page.getByRole("textbox", { name: /Blue channel goals/i }).fill(
    "Protect users while avoiding unnecessary escalation.",
  );

  await page.getByRole("button", { name: /Assist Hard constraints/i }).click();
  await expect(page.getByText("Preserve RED gate")).toBeVisible();
  await expect(page.getByRole("textbox", { name: /Hard constraints/i })).not.toHaveValue(
    /Maintain RED before BLUE/,
  );

  await page.getByRole("button", { name: /Edit before accepting/i }).click();
  await page
    .getByRole("textbox", { name: /Edit suggestion/i })
    .fill("Maintain RED before BLUE sequencing.\nNo silent gate bypass.");
  await page.getByRole("button", { name: /Accept suggestion/i }).click();
  await expect(page.getByRole("textbox", { name: /Hard constraints/i })).toHaveValue(/No silent gate bypass/);

  const lockButton = page.getByRole("button", { name: /Lock Frame/i });
  await expect(lockButton).toBeEnabled();
  await lockButton.click();

  await expect.poll(() => packetCalls.length).toBe(1);
  const dispositions = packetCalls[0].assist_acceptances as Array<Record<string, unknown>>;
  expect(dispositions).toEqual(
    expect.arrayContaining([
      expect.objectContaining({
        target: "frame.constraints_hard",
        disposition: "edited",
        proposed_value_hash: expect.stringMatching(/^[0-9a-f]{64}$/),
        final_value_hash: expect.stringMatching(/^[0-9a-f]{64}$/),
      }),
    ]),
  );
});
