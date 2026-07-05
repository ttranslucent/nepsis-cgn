import { expect, test } from "@playwright/test";
import { createHash } from "node:crypto";

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

async function useIsolatedRateLimitBucket(page: import("@playwright/test").Page, label: string) {
  await page.context().setExtraHTTPHeaders({
    "x-forwarded-for": `live-operator-${test.info().workerIndex}-${label}`,
  });
}

function sha256Hex(text: string) {
  return createHash("sha256").update(text, "utf8").digest("hex");
}

function proposalReceipt(target: string, model: string, proposedValueHash: string) {
  const issuedAt = "2026-06-22T00:00:00.000Z";
  return {
    schema_id: "nepsis.operator_model_proposal_receipt",
    schema_version: "1.0.0",
    receipt_id: `receipt-${target}`,
    issued_at: issuedAt,
    route: "/api/operator/model",
    mode: "suggest_field",
    target,
    model,
    loop_id: "loop-1",
    proposed_value_hash: proposedValueHash,
    signature: {
      algorithm: "hmac-sha256",
      key_id: "test",
      signature: "test-signature",
      signed_at: issuedAt,
    },
  };
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

function v3Field(
  state = "present",
  items: string[] = ["captured"],
  rationale = "Reviewed.",
) {
  return { status: state, items, rationale };
}

function v3IntakeArtifact() {
  return {
    layer: "intake",
    summary: "intake layer artifact.",
    goal_scope: v3Field("present", ["goal", "scope"]),
    red_triggers: v3Field(),
    blue_opportunity_space: v3Field(),
    constraints: v3Field(),
    manifold_match_mismatch: v3Field(),
    still_blockers: v3Field("none_found", [], "No blocker found at this layer."),
    unresolved_questions: v3Field("none_found", [], "No unresolved question found at this layer."),
    audit_notes: v3Field("present", ["packet visible"]),
    proposed_status: v3Field("present", ["ready"]),
    lock_eligibility: v3Field("present", ["eligible"]),
    layer_findings: { risk: [], ruin: [], win: [], recommendations: [] },
    intake: {
      goal: "Prototype V3 layer locks.",
      scope: "Operator packet layer loop.",
      assumptions: ["Frame is locked."],
      unresolved_questions: ["None for the prototype slice."],
    },
  };
}

function withV3LayerLoop(
  packet: ReturnType<typeof packetStub>,
  currentLayer: string,
  draftLayers: Record<string, Record<string, unknown>> = {},
  event = "START_V3_LAYER_LOOP",
) {
  return {
    ...packet,
    audit_trace: [...packet.audit_trace, { event, arguments: { layer: currentLayer } }],
    legal_next_tools: ["set_v3_layer_field", "propose_v3_operator_layer", "lock_v3_operator_layer", "run_report"],
    v3_layer_loop: {
      schema_id: "nepsis.operator_v3_layer_loop",
      schema_version: "0.1.0",
      packet: {
        schema: "nepsis.v3_orchestration_packet@0.1.0",
        run_id: "v3-run-1",
        packet_seq: Object.keys(draftLayers).length,
        created_at: "2026-06-22T00:00:00.000Z",
        expires_at: "2026-06-22T06:00:00.000Z",
        status: "active",
        goal: "Prototype V3 layer locks.",
        scope: "Operator packet layer loop.",
        initial_context: "Use the locked frame.",
        current_layer: currentLayer,
        layer_order: ["intake", "red", "manifold", "blue", "still", "synthesis", "audit"],
        locked_layers: currentLayer === "red" ? { intake: { artifact_hash: "sha256:intake", artifact: v3IntakeArtifact() } } : {},
        current_proposal:
          event === "PROPOSE_V3_LAYER_LOCK"
            ? {
                layer: "intake",
                artifact: draftLayers.intake ?? v3IntakeArtifact(),
                artifact_hash: "sha256:intake",
                validation: { schema_valid: true, lock_eligible: true, errors: [], warnings: [] },
              }
            : null,
        final_response_packet: null,
        abandon_reason: "",
        lineage: [{ event: "start", at: "2026-06-22T00:00:00.000Z", layer: null }],
      },
      draft_layers: draftLayers,
      navigation_shortcuts: {
        next_layer: "Meta+ArrowRight",
        previous_layer: "Meta+ArrowLeft",
      },
    },
  };
}

const CASE_REASONING_COMPILER = {
  schema_id: "nepsis.case_reasoning_compiler",
  schema_version: "0.1.0",
  compiler_source: "deterministic_v1",
  compiler_valid: true,
  validation_errors: [],
  validation_warnings: [],
  current_red_status: "open",
  domain_red_hazard: {
    hazard: "missed NSTI",
    mechanism_of_harm: "delayed operative source control",
    time_sensitivity: "hours",
    closure_requirement: "operative exploration or definitive alternative explaining the full trajectory",
  },
  authority_pushback: [
    {
      source: "radiology",
      claim: "gas is traumatic from rib fracture",
      what_it_does_not_close: ["secondary worsening", "severe progressive pain"],
      closure_status: "non_closing",
    },
  ],
  false_reassurance_tokens: [
    {
      token: "normal vitals",
      why_reassuring: "stable vitals lower immediate shock concern",
      why_non_closing: "normal vitals do not close a deep infection trajectory",
    },
  ],
  closure_condition: {
    required_to_close:
      "Operative exploration or a definitive alternative explaining the full trajectory, exam, labs, and imaging.",
    current_closure_status: "not_satisfied",
  },
  recommended_threshold_action: "escalate_red",
  decision_reason:
    "The red channel remains open because authority reassurance and normal vitals do not close the worsening trajectory.",
};

function stageAuditWithCompiler() {
  const interpretationPacket = {
    report_text: "critical severe worsening trajectory",
    evidence_count: 2,
    report_synced: true,
    contradictions_status: "declared",
    contradictions_note: "Authority reassurance does not close the red frame.",
    case_reasoning: CASE_REASONING_COMPILER,
    case_reasoning_validation: { status: "PASS", errors: [], warnings: [] },
  };
  const thresholdPacket = {
    hypothesis_count: 2,
    loss_treat: 1,
    loss_not_treat: 200,
    warning_level: "red",
    gate_crossed: true,
    recommendation: "escalate_red",
    recommended_threshold_action: "escalate_red",
    decision: "undecided",
    hold_reason: "",
    closure_basis: "",
    case_reasoning: CASE_REASONING_COMPILER,
    case_reasoning_validation: { status: "PASS", errors: [], warnings: [] },
  };
  return {
    session_id: "loop-1",
    stage: "report",
    policy: { name: "nepsis.stage_audit", version: "2026-06-20" },
    frame: {
      status: "PASS",
      checks: [],
      missing: [],
      warnings: [],
      packet: {},
      coach: { status: "PASS", summary: "Frame locked.", prompts: [] },
    },
    interpretation: {
      status: "PASS",
      checks: [],
      missing: [],
      warnings: [],
      packet: interpretationPacket,
      coach: { status: "PASS", summary: "Compiler packet validated.", prompts: [] },
      case_reasoning_validation: { status: "PASS", errors: [], warnings: [] },
    },
    threshold: {
      status: "BLOCK",
      checks: [],
      missing: ["Threshold decision"],
      warnings: [],
      packet: thresholdPacket,
      coach: { status: "BLOCK", summary: "Declare threshold decision.", prompts: [] },
      case_reasoning_validation: { status: "PASS", errors: [], warnings: [] },
    },
    source: {
      packet_count: 3,
      latest_packet_id: "packet-report_evaluated",
      latest_iteration: null,
      context_applied: true,
    },
  };
}

function reportStepStub(frame: Record<string, unknown>) {
  const session = sessionSummary(frame, "report_evaluated");
  return {
    manifold: "safety",
    family: "safety",
    decision: "hold",
    cause: "critical_signal",
    tension: 0.8,
    velocity: 0,
    accel: 0,
    posterior: { "open red hazard": 0.7, "benign closure": 0.3 },
    ruin_hits: ["missed NSTI"],
    active_transforms: [],
    is_ruin: true,
    violation_count: 1,
    stage: "REPORT",
    stage_events: ["RUN_REPORT"],
    frame_id: "frame-1",
    frame_version: 1,
    governance: {
      posture: "red_first",
      warning_level: "red",
      recommended_action: "escalate_red",
      trigger_codes: ["case_reasoning_compiler"],
      theta: 0.1,
      loss_treat: 1,
      loss_notreat: 200,
      p_bad: 0.7,
      ruin_mass: 0.7,
      contradiction_density: 0.2,
      posterior_entropy_norm: 0.4,
      top_margin: 0.4,
      top_p: 0.7,
      user_decision: null,
      override_reason: null,
    },
    session,
  };
}

function sessionSummary(frame: Record<string, unknown> = {}, operatorPhase = "frame_locked") {
  return {
    session_id: "loop-1",
    family: "safety",
    created_at: new Date().toISOString(),
    stage: "operator",
    steps: operatorPhase === "report_evaluated" ? 1 : 0,
    packet_count: operatorPhase === "report_evaluated" ? 2 : 1,
    frame: {
      frame_id: "frame-1",
      frame_version: 1,
      text: typeof frame.text === "string" ? frame.text : "Operator frame.",
      objective_type: typeof frame.objective_type === "string" ? frame.objective_type : "sensemake",
      domain: typeof frame.domain === "string" ? frame.domain : "safety",
      time_horizon: typeof frame.time_horizon === "string" ? frame.time_horizon : "short",
      rationale_for_change:
        typeof frame.rationale_for_change === "string" ? frame.rationale_for_change : null,
      constraints_hard: Array.isArray(frame.constraints_hard) ? frame.constraints_hard : [],
      constraints_soft: Array.isArray(frame.constraints_soft) ? frame.constraints_soft : [],
      costs: { c_fp: null, c_fn: null, c_delay: null },
    },
    branch_id: null,
    lineage_version: null,
    parent_frame_id: null,
    operator_phase: operatorPhase,
    operator_ambient: false,
  };
}

test("field assist requires explicit acceptance, supports editing, and sends verified dispositions", async ({
  page,
}) => {
  await useIsolatedRateLimitBucket(page, "field-assist");
  const packetCalls: Array<Record<string, unknown>> = [];
  const proposedValue = ["Maintain RED before BLUE sequencing."];
  const proposedValueHash = sha256Hex(proposedValue.join("\n"));
  const model = "gpt-4.1-mini";

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
            proposedValue,
            proposedValueHash,
            proposalReceipt: proposalReceipt("frame.constraints_hard", model, proposedValueHash),
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
  await expect(page.getByText("Hard constraints · edited")).toBeVisible();
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

test("operator V3 layer loop advances with shortcuts and visible audit state", async ({ page }) => {
  await useIsolatedRateLimitBucket(page, "v3-layer-loop");
  let currentPacket = packetStub("frame_draft", "START");
  let draftLayers: Record<string, Record<string, unknown>> = {};
  const seenFields: string[] = [];

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
  await page.route("**/api/engine/operator-packet/start", async (route) => {
    currentPacket = packetStub("frame_draft", "START");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentPacket),
    });
  });
  await page.route("**/api/engine/operator-packet/frame", async (route) => {
    const payload = await route.request().postDataJSON();
    currentPacket = packetStub("frame_locked", "LOCK_FRAME", payload.frame);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentPacket),
    });
  });
  await page.route("**/api/engine/operator-packet/v3/capability", async (route) => {
    const requiredRoutes = [
      "/v1/operator-packet/v3/start",
      "/v1/operator-packet/v3/field",
      "/v1/operator-packet/v3/propose",
      "/v1/operator-packet/v3/lock",
    ];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_id: "nepsis.operator_v3_backend_capability",
        schema_version: "1.0.0",
        available: true,
        source: "backend_route_manifest",
        required_routes: requiredRoutes,
        present_routes: requiredRoutes,
        missing_routes: [],
        checked_at: "2026-07-04T00:00:00.000Z",
      }),
    });
  });
  await page.route("**/api/engine/operator-packet/v3/start", async (route) => {
    const payload = await route.request().postDataJSON();
    expect(payload.goal).toBe("Prototype V3 layer locks.");
    currentPacket = withV3LayerLoop(currentPacket, "intake");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentPacket),
    });
  });
  await page.route("**/api/engine/operator-packet/v3/field", async (route) => {
    const payload = await route.request().postDataJSON();
    seenFields.push(payload.field);
    draftLayers = {
      ...draftLayers,
      [payload.layer]: {
        ...(draftLayers[payload.layer] ?? {}),
        [payload.field]: payload.value,
      },
    };
    currentPacket = withV3LayerLoop(currentPacket, "intake", draftLayers, "SET_V3_LAYER_FIELD");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentPacket),
    });
  });
  await page.route("**/api/engine/operator-packet/v3/propose", async (route) => {
    const payload = await route.request().postDataJSON();
    expect(payload.layer).toBe("intake");
    currentPacket = withV3LayerLoop(currentPacket, "intake", draftLayers, "PROPOSE_V3_LAYER_LOCK");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentPacket),
    });
  });
  await page.route("**/api/engine/operator-packet/v3/lock", async (route) => {
    const payload = await route.request().postDataJSON();
    expect(payload.layer).toBe("intake");
    expect(payload.lock_assertion.proposal_hash).toBe("sha256:intake");
    currentPacket = withV3LayerLoop(currentPacket, "red", draftLayers, "LOCK_V3_LAYER");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentPacket),
    });
  });

  await login(page);
  await page.goto("/operator");

  await page.getByRole("textbox", { name: /Frame question/i }).fill("Decide whether to escalate a safety incident.");
  await page
    .getByRole("textbox", { name: /Key uncertainty/i })
    .fill("Whether the first report reflects a real critical signal.");
  await page.getByRole("textbox", { name: /Hard constraints/i }).fill("Preserve RED before BLUE sequencing.");
  await page.getByRole("textbox", { name: /Soft constraints/i }).fill("Keep operator review concise.");
  await page.getByRole("textbox", { name: /Red channel definition/i }).fill("Missing a catastrophic incident.");
  await page.getByRole("textbox", { name: /Blue channel goals/i }).fill("Avoid unnecessary escalation after RED is closed.");
  await page.getByRole("button", { name: /Lock Frame/i }).click();

  await page.getByRole("button", { name: /Start V3 Layer Loop/i }).click();
  const v3Panel = page.getByRole("region", { name: /V3 operator layer loop/i });
  await expect(v3Panel).toContainText("Current layer: intake");
  await expect(v3Panel).toContainText("Meta+ArrowRight");
  await expect(v3Panel).toContainText("set_v3_layer_field");
  await expect(v3Panel).toContainText("START_V3_LAYER_LOOP");

  await page.getByRole("textbox", { name: /V3 intake artifact JSON/i }).fill(
    JSON.stringify(v3IntakeArtifact(), null, 2),
  );
  await page.getByRole("button", { name: /Save Draft Layer/i }).click();
  await expect.poll(() => seenFields).toContain("intake");
  await expect(v3Panel).toContainText("SET_V3_LAYER_FIELD");

  await page.getByRole("button", { name: /Propose Layer Lock/i }).click();
  await expect(v3Panel).toContainText("proposal hash");
  await page.getByRole("button", { name: /Lock Current Layer/i }).click();
  await expect(v3Panel).toContainText("Current layer: red");
  await expect(v3Panel).toContainText("LOCK_V3_LAYER");
});

test("operator does not advertise V3 controls when backend V3 routes are unavailable", async ({
  page,
}) => {
  await useIsolatedRateLimitBucket(page, "v3-unavailable");
  let currentPacket = packetStub("frame_draft", "START");
  let v3ActionCalls = 0;

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
  await page.route("**/api/engine/operator-packet/v3/capability", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        schema_id: "nepsis.operator_v3_backend_capability",
        schema_version: "1.0.0",
        available: false,
        source: "backend_route_manifest",
        required_routes: [
          "/v1/operator-packet/v3/start",
          "/v1/operator-packet/v3/field",
          "/v1/operator-packet/v3/propose",
          "/v1/operator-packet/v3/lock",
        ],
        present_routes: [],
        missing_routes: [
          "/v1/operator-packet/v3/start",
          "/v1/operator-packet/v3/field",
          "/v1/operator-packet/v3/propose",
          "/v1/operator-packet/v3/lock",
        ],
        checked_at: "2026-07-04T00:00:00.000Z",
      }),
    });
  });
  await page.route("**/api/engine/operator-packet/start", async (route) => {
    currentPacket = packetStub("frame_draft", "START");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentPacket),
    });
  });
  await page.route("**/api/engine/operator-packet/frame", async (route) => {
    const payload = await route.request().postDataJSON();
    currentPacket = packetStub("frame_locked", "LOCK_FRAME", payload.frame);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(currentPacket),
    });
  });
  await page.route(/\/api\/engine\/operator-packet\/v3\/(start|field|propose|lock)$/, async (route) => {
    v3ActionCalls += 1;
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ error: "V3 action route should not be called" }),
    });
  });

  await login(page);
  await page.goto("/operator");

  await page.getByRole("textbox", { name: /Frame question/i }).fill("Decide whether to escalate a safety incident.");
  await page
    .getByRole("textbox", { name: /Key uncertainty/i })
    .fill("Whether the first report reflects a real critical signal.");
  await page.getByRole("textbox", { name: /Hard constraints/i }).fill("Preserve RED before BLUE sequencing.");
  await page.getByRole("textbox", { name: /Soft constraints/i }).fill("Keep operator review concise.");
  await page.getByRole("textbox", { name: /Red channel definition/i }).fill("Missing a catastrophic incident.");
  await page.getByRole("textbox", { name: /Blue channel goals/i }).fill("Avoid unnecessary escalation after RED is closed.");
  await page.getByRole("button", { name: /Lock Frame/i }).click();

  const v3Panel = page.getByRole("region", { name: /V3 operator layer loop/i });
  await expect(v3Panel).toContainText("unavailable");
  await expect(page.getByRole("button", { name: /Start V3 Layer Loop/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Save Draft Layer/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Propose Layer Lock/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Lock Current Layer/i })).toHaveCount(0);
  expect(v3ActionCalls).toBe(0);
});

test("operator report exposes the Case Reasoning Compiler packet summary", async ({ page }) => {
  await useIsolatedRateLimitBucket(page, "compiler-packet");
  let currentFrame: Record<string, unknown> = {};
  let currentSession = sessionSummary(currentFrame, "frame_locked");

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
      body: JSON.stringify({ sessions: [currentSession] }),
    });
  });
  await page.route("**/api/engine/sessions/*/packets", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ session_id: "loop-1", count: 0, packets: [] }),
    });
  });
  await page.route("**/api/engine/sessions/*/stage-audit", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(stageAuditWithCompiler()),
    });
  });
  await page.route("**/api/engine/sessions/*/workspace", async (route) => {
    const payload = await route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...currentSession,
        workspace_state: payload.workspace_state,
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
    currentFrame = payload.frame;
    currentSession = sessionSummary(currentFrame, "frame_locked");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(packetStub("frame_locked", "LOCK_FRAME", payload.frame)),
    });
  });
  await page.route("**/api/engine/operator-packet/report", async (route) => {
    const payload = await route.request().postDataJSON();
    const packet = {
      ...packetStub("report_evaluated", "RUN_REPORT", payload.packet.frame),
      latest_audit: stageAuditWithCompiler(),
      latest_step: reportStepStub(payload.packet.frame),
      legal_next_tools: ["run_report", "lock_report", "abandon_packet"],
    };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(packet),
    });
  });

  await page.goto("/operator");

  await page.getByRole("textbox", { name: /Frame question/i }).fill("Decide whether to escalate a safety incident.");
  await page
    .getByRole("textbox", { name: /Key uncertainty/i })
    .fill("Whether normal vitals and radiology reassurance close the red frame.");
  await page.getByRole("textbox", { name: /Hard constraints/i }).fill("Preserve RED before BLUE sequencing.");
  await page.getByRole("textbox", { name: /Soft constraints/i }).fill("Keep operator review concise.");
  await page.getByRole("textbox", { name: /Red channel definition/i }).fill("Missing a necrotizing infection.");
  await page.getByRole("textbox", { name: /Blue channel goals/i }).fill("Avoid over-escalation after RED is closed.");
  await page.getByRole("button", { name: /Lock Frame/i }).click();

  await page.locator("#report-input").fill("critical severe worsening despite normal vitals and authority reassurance");
  await page.locator("#report-run-button").click();

  const compilerPanel = page.getByRole("region", { name: /Case Reasoning Compiler packet/i });
  await expect(compilerPanel).toBeVisible();
  await expect(compilerPanel).toContainText("Domain RED hazard");
  await expect(compilerPanel).toContainText("missed NSTI");
  await expect(compilerPanel).toContainText("Authority pushback");
  await expect(compilerPanel).toContainText("gas is traumatic from rib fracture");
  await expect(compilerPanel).toContainText("False reassurance");
  await expect(compilerPanel).toContainText("normal vitals");
  await expect(compilerPanel).toContainText("Closure condition");
  await expect(compilerPanel).toContainText("not_satisfied");
  await expect(compilerPanel).toContainText("Threshold recommendation");
  await expect(compilerPanel).toContainText("escalate_red");
});
