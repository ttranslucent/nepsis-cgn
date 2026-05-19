import { expect, test } from "@playwright/test";

const mvpPacket = {
  schema_id: "nepsis.mvp_packet",
  schema_version: "0.1.3",
  packet_id: "test-packet",
  created_at: "2026-05-19T00:00:00Z",
  case_id: "jailing",
  input_text: "The source says JINGALL but candidate says JAILING.",
  observations: ["source token JINGALL", "candidate token JAILING"],
  constraints: ["preserve source-token spelling"],
  red_channel: {
    active_hazards: [{ id: "source-token-drift", label: "Source-token drift" }],
    ruled_out_hazards: [],
    missing_discriminators: ["confirm source spelling"],
    escalation_required: true,
    rationale: "RED preserves the source-token constraint before BLUE.",
  },
  still: {
    name: "STILL",
    definition: "Metacognitive checkpoint before progression.",
    checkpoints: [
      {
        name: "after_red_before_blue",
        position: "after_red_before_blue",
        trigger_status: "hold",
        reason: "Check RED boundary before BLUE.",
        required_before_commitment: ["preserve source spelling"],
      },
      {
        name: "after_blue_before_commitment",
        position: "after_blue_before_commitment",
        trigger_status: "retessellate",
        reason: "Contradiction requires retessellation.",
        required_before_commitment: ["resolve spelling conflict"],
      },
    ],
    commitment_readiness: {
      status: "retessellate",
      rationale: "Do not commit while source-token conflict remains.",
    },
    learning_notes: ["Do not normalize away source constraints."],
    audit_events: [{ order: 1, stage: "STILL", summary: "Checkpoint held." }],
  },
  blue_channel: {
    hypotheses: [
      {
        id: "h1",
        label: "Candidate drift",
        likelihood: "high",
        supporting_features: ["candidate differs"],
        contradicting_features: ["source is fixed"],
        needed_discriminators: ["source check"],
        action_threshold: "do not commit",
      },
    ],
    weights: { red: "dominant", blue: "bounded" },
    supporting_features: ["candidate differs"],
    contradicting_features: ["source is fixed"],
    needed_discriminators: ["source check"],
  },
  contradiction_monitor: {
    contradictions: [{ id: "c1", description: "JINGALL conflicts with JAILING." }],
    contradiction_density: 1,
    stability_status: "unstable",
  },
  denominator_collapse: {
    detected: true,
    missing_hypothesis_classes: ["source-token-preservation"],
    retessellation_required: true,
  },
  non_quiescence: {
    wrong_manifold_possible: true,
    reason: "Candidate normalization may be wrong.",
    next_required_move: "retessellate",
  },
  zeroback: {
    triggered: true,
    reason: "Reset to source token.",
    reset_scope: "candidate",
  },
  voronoi_commitment: {
    recommended_action: "hold",
    threshold_basis: "source-token risk",
    consequence_weighting: "RED dominates BLUE",
  },
  state_feedback: {
    current_state: {
      timestamp_or_phase: "mvp",
      active_frame: "source token preservation",
      active_constraints: ["preserve source-token spelling"],
      active_hazards: ["source-token drift"],
      current_commitment: "hold",
      uncertainty_level: "high",
    },
    predicted_next_state: {
      expected_time_window: "next observation",
      expected_changes: ["source spelling remains JINGALL"],
      expected_discriminators: ["source spelling"],
      expected_resolution_signs: ["JINGALL preserved"],
      failure_conditions: ["JAILING substituted"],
    },
    observed_next_state: {
      status: "not_observed_in_mvp",
      placeholder_reason: "No live feedback loop.",
    },
    delta_analysis: {
      matches_prediction: "pending",
      contradiction_delta: "pending",
      confidence_delta: "pending",
      reason: "No observation yet.",
    },
    loop_decision: {
      status: "hold",
      rationale: "Wait for source check.",
      next_observation_required: "source spelling",
    },
    audit_events: ["state_feedback_declared"],
  },
  audit_trace: [{ order: 1, stage: "RED", summary: "RED ran before BLUE." }],
  final_output: {
    concise_recommendation: "Hold and preserve JINGALL.",
    caveats: ["Deterministic MVP packet."],
    required_next_discriminators: ["source spelling"],
  },
};

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
  await page.route("**/api/engine/mvp", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mvpPacket),
    });
  });

  await page.goto("/mvp");
  await expect(page.getByRole("heading", { name: /RED/i })).toBeVisible();
  await page.getByRole("button", { name: "Run Demo" }).click();

  await expect(page.getByText("nepsis.mvp_packet", { exact: true })).toBeVisible();
  await expect(page.getByText("Hold and preserve JINGALL.", { exact: true })).toBeVisible();
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

test("status page exposes safe public system posture", async ({ page }) => {
  await page.route("**/api/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        backend: { configured: false, reachable: false },
        auth: { loginConfigured: false, previewCodesEnabled: false },
        models: { enabled: false, hasServerOpenAiKey: false },
        mcp: { available: true, publicTools: ["run_mvp", "health", "get_mvp_schema"] },
      }),
    });
  });

  await page.goto("/status");
  await expect(page.getByRole("heading", { name: /System Status/i })).toBeVisible();
  await expect(page.getByText("Backend API")).toBeVisible();
  await expect(page.getByText("MCP Tools")).toBeVisible();
  await expect(page.getByText("No server OpenAI key configured")).toBeVisible();
});
