# Live Operator Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clearly labeled authenticated live/operator path with real backend and model behavior while keeping `/mvp` frozen as the public deterministic demo and baseline.

**Architecture:** Preserve the existing FastAPI engine service, manifest/navigation runtime, RED-before-BLUE gating, and packet lineage. Add `/operator` as a live surface that reuses the current `/engine` operator workspace and only enables model calls when auth, backend, and server-side model configuration are ready. Model output must propose drafts or interpretations; the existing engine service remains the source of session state, stage gates, iteration packets, and operator audit packets.

**Tech Stack:** CPython 3.11, existing `nepsis_cgn.api` HTTP service, Next.js App Router, React 19, TypeScript, Tailwind CSS, Playwright e2e, pytest.

---

## Evaluation

The proposed product shape is correct for this repo.

- `/mvp` is already the frozen public demo: `nepsis-web/src/app/mvp/page.tsx` calls `engineClient.runMvp()`, `POST /api/engine/mvp` falls back to bundled frozen packets in public mode, and canonical output is owned by `src/nepsis_cgn/core/mvp.py`.
- The live/operator backend already exists: `EngineApiService` owns sessions, operator phases, stage audit gates, workspace state, packet replay, and commit/abandon flows.
- The current operator UI already exists at `/engine`, but public production hides or gates it.
- The current model connection is not yet the real operator connection. `/api/run-with-nepsis` is a detached sandbox and `/api/playground-nepsis` is puzzle/playground-specific. Neither is integrated as a stage-aware operator model assistant.
- The current `publicSiteMode()` treats all production builds as public, which intentionally disables model routes. That is good for the public demo, but it means a production live/operator deployment needs an explicit operator deployment mode before model routes can work.

Conclusion: do not wait to build the route and controls, but do keep live behavior behind explicit readiness gates. A tab alone is insufficient; the minimum safe slice is tab + route + deployment mode + auth/backend readiness + protected model endpoint.

## Branch

Use this branch for implementation:

```bash
git checkout -b codex/live-operator-path
```

If the branch already exists:

```bash
git checkout codex/live-operator-path
```

## File Structure

- Modify: `nepsis-web/src/lib/publicMode.ts`
  - Add an explicit operator deployment mode and make model routes possible for authenticated operator deployments without changing public-site defaults.
- Modify: `nepsis-web/src/app/layout.tsx`
  - Add a labeled `Live Operator` nav tab only when the deployment mode allows it.
- Create: `nepsis-web/src/app/operator/page.tsx`
  - Route alias for the live/operator surface.
- Modify: `nepsis-web/src/app/engine/page.tsx`
  - Label `/operator` as live mode and wire model-assist calls to a protected operator model endpoint.
- Create: `nepsis-web/src/lib/operatorModelClient.ts`
  - Typed browser client for the operator model-assist route.
- Create: `nepsis-web/src/app/api/operator/model/route.ts`
  - Protected server-side model route for operator stage assistance.
- Modify: `nepsis-web/src/app/api/status/route.ts`
  - Report live operator readiness separately from public MVP readiness.
- Modify: `nepsis-web/src/app/status/page.tsx`
  - Display live/operator readiness and explain blocked states.
- Modify: `nepsis-web/e2e/public-site.spec.ts`
  - Prove public `/mvp` remains frozen and `/operator` is gated.
- Modify: `nepsis-web/e2e-auth/auth-flow.spec.ts`
  - Prove signed-in operators can open `/operator`.
- Create: `nepsis-web/e2e-auth/live-operator.spec.ts`
  - Prove the live model UI uses the protected operator model route without calling a real provider in tests.
- Modify: `scripts/site-smoke.sh`
  - Keep public production checks strict: `/mvp` public, `/operator` gated, public model routes disabled.
- Modify: `README.md`, `docs/operator-runbook.md`, `docs/public-api.md`, `nepsis-web/README.md`
  - Document the split between public demo and live operator deployment.

## Design Rules

- Do not modify `src/nepsis_cgn/core/mvp.py` or `nepsis-web/src/data/mvpPackets.json` for this feature.
- Do not make `/mvp`, `POST /v1/mvp`, or `POST /api/engine/mvp` depend on auth, sessions, or provider models.
- Do not replace the manifold/navigation runtime with a generic chatbot flow.
- Model calls must be labeled as live, authenticated, latency/error-prone, and stateful.
- Shared production must not collect browser OpenAI keys. Browser-local keys remain local-demo only.
- Server-side model output is advisory input to the operator flow. Existing backend gates decide whether a frame, report, threshold, or commit can proceed.

---

### Task 1: Add Boundary Tests First

**Files:**
- Modify: `nepsis-web/e2e/public-site.spec.ts`
- Modify: `nepsis-web/e2e-auth/auth-flow.spec.ts`
- Create: `nepsis-web/e2e-auth/live-operator.spec.ts`

- [ ] **Step 1: Extend public-site e2e coverage**

Add this test to `nepsis-web/e2e/public-site.spec.ts` after `public operator routes are gated and do not ask for browser API keys`:

```ts
test("public live operator route is labeled and gated", async ({ page }) => {
  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: /Operator access required/i })).toBeVisible();
  await expect(page.getByRole("link", { name: /Run MVP Demo/i })).toBeVisible();
  await expect(page.getByLabel(/OpenAI API Key/i)).toHaveCount(0);
  await expect(page.getByText(/deterministic MVP demo remains available/i)).toBeVisible();
});
```

- [ ] **Step 2: Extend signed-in auth coverage**

Append this to `nepsis-web/e2e-auth/auth-flow.spec.ts`:

```ts
test("signed-in operator can open live operator route", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("operator@example.com");
  await page.getByRole("button", { name: "Send code" }).click();
  const statusText = await page.getByRole("status").textContent();
  const previewCode = statusText?.match(/\b\d{6}\b/)?.[0];
  expect(previewCode).toBeTruthy();
  await page.getByRole("button", { name: "Verify & continue" }).click();

  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: /Live Operator Workspace/i })).toBeVisible();
  await expect(page.getByText(/Live mode/i)).toBeVisible();
});
```

- [ ] **Step 3: Add model-assist UI coverage with network mocking**

Create `nepsis-web/e2e-auth/live-operator.spec.ts`:

```ts
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

test("live operator model assist applies a frame draft", async ({ page }) => {
  await page.route("**/api/operator/model", async (route) => {
    const request = route.request();
    expect(request.method()).toBe("POST");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        mode: "draft_frame",
        model: "gpt-4.1-mini",
        outputText: "Structured frame draft generated by test route.",
        frameDraft: {
          text: "Decide whether to escalate a safety incident.",
          objective_type: "decide",
          domain: "safety",
          time_horizon: "short",
          key_uncertainty: "Whether the first report reflects a real critical signal.",
          constraints_hard: ["Maintain RED before BLUE sequencing."],
          constraints_soft: ["Minimize unnecessary disruption."],
          red_definition: "Missing a catastrophic incident.",
          blue_goals: "Protect users while avoiding unnecessary escalation."
        }
      })
    });
  });

  await login(page);
  await page.goto("/operator");
  await page.getByRole("button", { name: /Model Assist/i }).click();
  await page.getByLabel(/Model prompt/i).fill("Frame a safety escalation decision.");
  await page.getByRole("button", { name: /Draft Frame/i }).click();

  await expect(page.getByLabel(/Frame question/i)).toHaveValue(/Decide whether to escalate/);
  await expect(page.getByLabel(/Red channel definition/i)).toHaveValue(/catastrophic/);
});
```

- [ ] **Step 4: Run the failing e2e tests**

Run:

```bash
cd nepsis-web
npm run test:e2e -- --project=chrome-desktop -g "public live operator route is labeled and gated"
npm run test:e2e:auth -- --project=chrome-desktop -g "signed-in operator can open live operator route"
npm run test:e2e:auth -- --project=chrome-desktop -g "live operator model assist applies a frame draft"
```

Expected: fail because `/operator`, live labeling, and model assist controls do not exist yet.

- [ ] **Step 5: Commit the failing tests**

```bash
git add nepsis-web/e2e/public-site.spec.ts nepsis-web/e2e-auth/auth-flow.spec.ts nepsis-web/e2e-auth/live-operator.spec.ts
git commit -m "test: cover live operator boundary"
```

---

### Task 2: Add Explicit Deployment Modes

**Files:**
- Modify: `nepsis-web/src/lib/publicMode.ts`
- Modify: `nepsis-web/src/app/api/status/route.ts`
- Modify: `nepsis-web/src/app/status/page.tsx`

- [ ] **Step 1: Update deployment-mode helpers**

Replace `nepsis-web/src/lib/publicMode.ts` with:

```ts
function envValue(name: string): string {
  return process.env[name]?.trim().toLowerCase() ?? "";
}

export function envFlag(name: string): boolean {
  const value = envValue(name);
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

function envFalse(name: string): boolean {
  const value = envValue(name);
  return value === "0" || value === "false" || value === "no" || value === "off";
}

export function operatorSiteMode(): boolean {
  return envValue("NEPSIS_DEPLOYMENT_MODE") === "operator" || envFlag("NEXT_PUBLIC_NEPSIS_OPERATOR_SITE");
}

export function publicSiteMode(): boolean {
  if (operatorSiteMode()) {
    return false;
  }
  if (envFlag("NEXT_PUBLIC_NEPSIS_PUBLIC_SITE")) {
    return true;
  }
  if (envFalse("NEXT_PUBLIC_NEPSIS_PUBLIC_SITE")) {
    return false;
  }
  return process.env.NODE_ENV === "production";
}

export function liveOperatorEnabled(): boolean {
  return operatorSiteMode() || envFlag("NEPSIS_LIVE_OPERATOR_ENABLED");
}

export function browserModelKeysAllowed(): boolean {
  return process.env.NODE_ENV !== "production" && !publicSiteMode() && envFlag("NEPSIS_BROWSER_MODEL_KEYS_ALLOWED");
}

export function modelRoutesEnabled(): boolean {
  if (publicSiteMode()) {
    return false;
  }
  return liveOperatorEnabled() && envFlag("NEPSIS_MODEL_ROUTES_ENABLED");
}
```

- [ ] **Step 2: Run existing public e2e to confirm defaults are unchanged**

Run:

```bash
cd nepsis-web
npm run test:e2e -- --project=chrome-desktop -g "public model API routes are disabled without provider keys"
```

Expected: PASS. Public mode still disables model routes.

- [ ] **Step 3: Add operator readiness to `/api/status`**

In `nepsis-web/src/app/api/status/route.ts`, import the new helpers:

```ts
import {
  liveOperatorEnabled,
  modelRoutesEnabled,
  operatorSiteMode,
} from "@/lib/publicMode";
```

Add this object to the JSON response:

```ts
operator: {
  enabled: liveOperatorEnabled(),
  operatorSiteMode: operatorSiteMode(),
  path: "/operator",
  backendReady: backend.configured && backend.reachable,
  authReady: operatorLoginReady(),
  modelReady: modelRoutesEnabled() && hasConfiguredOpenAiKey(),
},
```

- [ ] **Step 4: Show operator readiness on the status page**

In `nepsis-web/src/app/status/page.tsx`, extend `StatusPayload`:

```ts
operator: {
  enabled: boolean;
  operatorSiteMode: boolean;
  path: string;
  backendReady: boolean;
  authReady: boolean;
  modelReady: boolean;
};
```

Add a `StatusCard` after `Backend API`:

```tsx
<StatusCard title="Live Operator" ok={status.operator.enabled && status.operator.backendReady && status.operator.authReady}>
  <p>{status.operator.enabled ? "Live operator route is enabled." : "Live operator route is disabled."}</p>
  <p>Path: {status.operator.path}</p>
  <p>{status.operator.backendReady ? "Backend is reachable." : "Backend is not ready."}</p>
  <p>{status.operator.authReady ? "Operator auth is ready." : "Operator auth is not ready."}</p>
  <p>{status.operator.modelReady ? "Server model key is ready." : "Server model key is not ready."}</p>
</StatusCard>
```

- [ ] **Step 5: Run focused checks**

Run:

```bash
cd nepsis-web
npm run lint
npm run test:e2e -- --project=chrome-desktop -g "status API reports bundled MVP available without backend env"
```

Expected: PASS.

- [ ] **Step 6: Commit deployment mode helpers**

```bash
git add nepsis-web/src/lib/publicMode.ts nepsis-web/src/app/api/status/route.ts nepsis-web/src/app/status/page.tsx
git commit -m "feat: add live operator deployment mode"
```

---

### Task 3: Add the `/operator` Route and Nav Tab

**Files:**
- Create: `nepsis-web/src/app/operator/page.tsx`
- Modify: `nepsis-web/src/app/layout.tsx`
- Modify: `nepsis-web/src/app/engine/page.tsx`

- [ ] **Step 1: Create the route alias**

Create `nepsis-web/src/app/operator/page.tsx`:

```tsx
export { default } from "@/app/engine/page";
```

- [ ] **Step 2: Add the nav tab only for live/operator mode**

In `nepsis-web/src/app/layout.tsx`, import:

```ts
import { liveOperatorEnabled, publicSiteMode } from "@/lib/publicMode";
```

Replace `const visibleNavLinks = publicSiteMode() ? publicNavLinks : navLinks;` with:

```ts
const isPublicSite = publicSiteMode();
const liveOperatorLinks = liveOperatorEnabled()
  ? [{ href: "/operator", label: "Live Operator" }]
  : [];
const visibleNavLinks = isPublicSite
  ? publicNavLinks
  : [...navLinks, ...liveOperatorLinks];
```

Change the banner copy from:

```tsx
<span>Operator tools require sign-in and deployment configuration.</span>
```

to:

```tsx
<span>Live operator tools require sign-in, backend configuration, and server model configuration.</span>
```

- [ ] **Step 3: Label `/operator` as live mode**

In `nepsis-web/src/app/engine/page.tsx`, change the Next import:

```ts
import { usePathname, useRouter } from "next/navigation";
```

Inside `EnginePage`, after `const router = useRouter();`, add:

```ts
const pathname = usePathname();
const liveOperatorSurface = pathname.startsWith("/operator");
```

Change the heading:

```tsx
<h1 className="text-xl font-semibold">
  {liveOperatorSurface ? "Live Operator Workspace" : "Nepsis Engine Workspace"}
</h1>
```

Add a live-mode badge beside the heading:

```tsx
{liveOperatorSurface && (
  <span className="mt-2 inline-flex rounded-full border border-amber-500/40 bg-amber-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-amber-100">
    Live mode
  </span>
)}
```

- [ ] **Step 4: Run the route tests**

Run:

```bash
cd nepsis-web
npm run test:e2e -- --project=chrome-desktop -g "public live operator route is labeled and gated"
npm run test:e2e:auth -- --project=chrome-desktop -g "signed-in operator can open live operator route"
```

Expected: PASS.

- [ ] **Step 5: Commit the route and nav**

```bash
git add nepsis-web/src/app/operator/page.tsx nepsis-web/src/app/layout.tsx nepsis-web/src/app/engine/page.tsx
git commit -m "feat: add live operator route"
```

---

### Task 4: Add a Protected Operator Model Endpoint

**Files:**
- Create: `nepsis-web/src/app/api/operator/model/route.ts`
- Create: `nepsis-web/src/lib/operatorModelClient.ts`
- Modify: `nepsis-web/src/app/api/run-with-nepsis/route.ts`
- Modify: `nepsis-web/src/app/api/playground-nepsis/route.ts`

- [ ] **Step 1: Create the typed client**

Create `nepsis-web/src/lib/operatorModelClient.ts`:

```ts
export type OperatorModelMode = "draft_frame" | "interpret_report" | "threshold_review";

export type OperatorFrameDraft = {
  text: string;
  objective_type: string;
  domain: string;
  time_horizon: string;
  key_uncertainty: string;
  constraints_hard: string[];
  constraints_soft: string[];
  red_definition: string;
  blue_goals: string;
};

export type OperatorModelResponse = {
  mode: OperatorModelMode;
  model: string;
  outputText: string;
  frameDraft?: OperatorFrameDraft;
  reportNotes?: string;
  thresholdNote?: string;
};

export async function requestOperatorModel(payload: {
  mode: OperatorModelMode;
  input: string;
  context?: Record<string, unknown>;
  model?: string;
}): Promise<OperatorModelResponse> {
  const response = await fetch("/api/operator/model", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    const message =
      typeof data?.detail === "string"
        ? data.detail
        : typeof data?.error === "string"
          ? data.error
          : "Operator model request failed.";
    throw new Error(message);
  }
  return data as OperatorModelResponse;
}
```

- [ ] **Step 2: Create the protected route**

Create `nepsis-web/src/app/api/operator/model/route.ts`:

```ts
import { NextResponse } from "next/server";

import {
  DEFAULT_OPENAI_MODEL,
  createOpenAiClient,
  extractOpenAiText,
  hasConfiguredOpenAiKey,
} from "@/lib/openaiClient";
import { requireEngineControlAuth } from "@/lib/engineApi";
import { modelRoutesEnabled } from "@/lib/publicMode";

export const runtime = "nodejs";

const MODES = new Set(["draft_frame", "interpret_report", "threshold_review"]);

function systemPrompt(mode: string): string {
  const base =
    "You are assisting a NepsisCGN operator. Preserve RED before BLUE. " +
    "Do not make final commitments. Return compact JSON only.";
  if (mode === "draft_frame") {
    return `${base} JSON shape: {"frameDraft":{"text":"","objective_type":"decide","domain":"","time_horizon":"short","key_uncertainty":"","constraints_hard":[],"constraints_soft":[],"red_definition":"","blue_goals":""},"outputText":""}`;
  }
  if (mode === "interpret_report") {
    return `${base} JSON shape: {"reportNotes":"","outputText":""}`;
  }
  return `${base} JSON shape: {"thresholdNote":"","outputText":""}`;
}

function parseObject(text: string): Record<string, unknown> {
  const cleaned = text.trim().replace(/^```(?:json)?/i, "").replace(/```$/i, "").trim();
  const parsed = JSON.parse(cleaned);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Model response was not a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function frameDraft(value: unknown) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return undefined;
  }
  const record = value as Record<string, unknown>;
  const text = typeof record.text === "string" ? record.text : "";
  return {
    text,
    objective_type: typeof record.objective_type === "string" ? record.objective_type : "decide",
    domain: typeof record.domain === "string" ? record.domain : "general",
    time_horizon: typeof record.time_horizon === "string" ? record.time_horizon : "short",
    key_uncertainty: typeof record.key_uncertainty === "string" ? record.key_uncertainty : "",
    constraints_hard: stringArray(record.constraints_hard),
    constraints_soft: stringArray(record.constraints_soft),
    red_definition: typeof record.red_definition === "string" ? record.red_definition : "",
    blue_goals: typeof record.blue_goals === "string" ? record.blue_goals : "",
  };
}

export async function POST(req: Request) {
  if (!modelRoutesEnabled()) {
    return NextResponse.json(
      { error: "Model routes disabled", detail: "Live operator model routes are not enabled for this deployment." },
      { status: 403 },
    );
  }

  const authFailure = requireEngineControlAuth(req);
  if (authFailure) {
    return authFailure;
  }

  if (!hasConfiguredOpenAiKey()) {
    return NextResponse.json(
      { error: "Server model key required", detail: "Configure OPENAI_API_KEY or NEPSIS_OPENAI_API_KEY server-side." },
      { status: 428 },
    );
  }

  const body = await req.json().catch(() => null);
  const mode = typeof body?.mode === "string" ? body.mode : "";
  const input = typeof body?.input === "string" ? body.input.trim() : "";
  const model = typeof body?.model === "string" && body.model.trim() ? body.model.trim() : DEFAULT_OPENAI_MODEL;
  const context = typeof body?.context === "object" && body.context !== null ? body.context : {};

  if (!MODES.has(mode)) {
    return NextResponse.json({ error: "Invalid mode" }, { status: 400 });
  }
  if (!input) {
    return NextResponse.json({ error: "Input is required" }, { status: 400 });
  }

  try {
    const completion = await createOpenAiClient().responses.create({
      model,
      input: [
        { role: "system", content: systemPrompt(mode) },
        { role: "user", content: JSON.stringify({ input, context }) },
      ],
    } as never);
    const raw = extractOpenAiText(completion) || "{}";
    const parsed = parseObject(raw);
    const outputText = typeof parsed.outputText === "string" ? parsed.outputText : raw;

    return NextResponse.json({
      mode,
      model,
      outputText,
      frameDraft: mode === "draft_frame" ? frameDraft(parsed.frameDraft) : undefined,
      reportNotes: typeof parsed.reportNotes === "string" ? parsed.reportNotes : undefined,
      thresholdNote: typeof parsed.thresholdNote === "string" ? parsed.thresholdNote : undefined,
    });
  } catch (error) {
    return NextResponse.json(
      { error: "Operator model request failed", detail: (error as Error)?.message ?? "Unknown error" },
      { status: 502 },
    );
  }
}
```

- [ ] **Step 3: Keep browser-key model calls local-only**

In `nepsis-web/src/app/api/run-with-nepsis/route.ts` and `nepsis-web/src/app/api/playground-nepsis/route.ts`, import `browserModelKeysAllowed`:

```ts
import { browserModelKeysAllowed, modelRoutesEnabled } from "@/lib/publicMode";
```

Replace `createOpenAiClient(apiKey)` with:

```ts
createOpenAiClient(browserModelKeysAllowed() ? apiKey : null)
```

Keep the existing `hasConfiguredOpenAiKey()` fallback checks. This preserves local demos while preventing shared deployments from accepting browser provider keys.

- [ ] **Step 4: Run route-level e2e checks without a real provider key**

Run:

```bash
cd nepsis-web
NEPSIS_LIVE_OPERATOR_ENABLED=true NEPSIS_MODEL_ROUTES_ENABLED=true npm run test:e2e:auth -- --project=chrome-desktop -g "signed-in operator can open live operator route"
```

Expected: PASS. The test does not call the provider.

- [ ] **Step 5: Commit the protected model endpoint**

```bash
git add nepsis-web/src/app/api/operator/model/route.ts nepsis-web/src/lib/operatorModelClient.ts nepsis-web/src/app/api/run-with-nepsis/route.ts nepsis-web/src/app/api/playground-nepsis/route.ts
git commit -m "feat: add protected operator model endpoint"
```

---

### Task 5: Wire Model Assist Into the Operator Workspace

**Files:**
- Modify: `nepsis-web/src/app/engine/page.tsx`

- [ ] **Step 1: Import the model client**

Add:

```ts
import {
  requestOperatorModel,
  type OperatorModelResponse,
} from "@/lib/operatorModelClient";
```

- [ ] **Step 2: Add state for model assist**

Inside `EnginePage`, near other `useState` calls, add:

```ts
const [modelAssistOpen, setModelAssistOpen] = useState(false);
const [modelAssistInput, setModelAssistInput] = useState("");
const [modelAssistBusy, setModelAssistBusy] = useState(false);
const [modelAssistLast, setModelAssistLast] = useState<OperatorModelResponse | null>(null);
```

- [ ] **Step 3: Add a frame-draft handler**

Add this function near the other handlers:

```ts
async function handleDraftFrameWithModel() {
  clearAllErrors();
  const input = optionalText(modelAssistInput);
  if (!input) {
    setLocalError("Model prompt is required.");
    return;
  }
  setModelAssistBusy(true);
  try {
    const result = await requestOperatorModel({
      mode: "draft_frame",
      input,
      context: {
        family,
        current_frame: frameDraft,
        gate_status: displayFrameGateStatus,
      },
    });
    setModelAssistLast(result);
    if (result.frameDraft) {
      setFrameDraft((prev) => ({
        ...prev,
        text: result.frameDraft?.text ?? prev.text,
        objective_type: result.frameDraft?.objective_type ?? prev.objective_type,
        domain: result.frameDraft?.domain ?? prev.domain,
        time_horizon: result.frameDraft?.time_horizon ?? prev.time_horizon,
        key_uncertainty: result.frameDraft?.key_uncertainty ?? prev.key_uncertainty,
        constraints_hard_text: lineListToText(result.frameDraft?.constraints_hard ?? []),
        constraints_soft_text: lineListToText(result.frameDraft?.constraints_soft ?? []),
        red_definition: result.frameDraft?.red_definition ?? prev.red_definition,
        blue_goals: result.frameDraft?.blue_goals ?? prev.blue_goals,
      }));
      pushFrameMessage("nepsis", "Live model draft applied. Review the frame gate before locking.");
    }
  } catch (error) {
    setLocalError(error instanceof Error ? error.message : "Model assist failed.");
  } finally {
    setModelAssistBusy(false);
  }
}
```

- [ ] **Step 4: Add a clearly labeled control**

In the top button cluster next to `Model Sandbox`, add:

```tsx
{liveOperatorSurface && (
  <button
    onClick={() => setModelAssistOpen(true)}
    className="rounded-full border border-amber-500/50 px-3 py-1.5 text-xs text-amber-100 hover:border-amber-300"
  >
    Model Assist
  </button>
)}
```

Near the existing sandbox overlay, add this modal:

```tsx
{modelAssistOpen && (
  <div className="fixed inset-0 z-50">
    <button
      aria-label="Close model assist overlay"
      onClick={() => setModelAssistOpen(false)}
      className="absolute inset-0 bg-black/60"
    />
    <aside className="absolute right-0 top-0 h-full w-full max-w-md border-l border-nepsis-border bg-nepsis-panel p-4 shadow-2xl shadow-black/60">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold">Live Model Assist</h2>
          <p className="text-xs text-nepsis-muted">Authenticated server-side model call. Review gates before commitment.</p>
        </div>
        <button
          onClick={() => setModelAssistOpen(false)}
          className="rounded-full border border-nepsis-border px-2 py-0.5 text-xs hover:border-nepsis-accent"
        >
          Close
        </button>
      </div>
      <label className="block text-xs text-nepsis-muted">
        Model prompt
        <textarea
          value={modelAssistInput}
          onChange={(event) => setModelAssistInput(event.target.value)}
          rows={5}
          disabled={modelAssistBusy}
          className="mt-1 w-full rounded-lg border border-nepsis-border bg-black/20 px-2 py-1.5 text-xs text-nepsis-text"
        />
      </label>
      <button
        onClick={() => void handleDraftFrameWithModel()}
        disabled={modelAssistBusy || !modelAssistInput.trim()}
        className="mt-3 rounded-full bg-nepsis-accent px-4 py-2 text-xs font-semibold text-black disabled:opacity-60"
      >
        {modelAssistBusy ? "Drafting..." : "Draft Frame"}
      </button>
      {modelAssistLast && (
        <pre className="mt-3 max-h-72 overflow-auto rounded border border-nepsis-border bg-black/30 p-2 text-[11px] text-nepsis-muted">
          {JSON.stringify(modelAssistLast, null, 2)}
        </pre>
      )}
    </aside>
  </div>
)}
```

- [ ] **Step 5: Run the mocked model-assist e2e test**

Run:

```bash
cd nepsis-web
npm run test:e2e:auth -- --project=chrome-desktop -g "live operator model assist applies a frame draft"
```

Expected: PASS.

- [ ] **Step 6: Commit UI wiring**

```bash
git add nepsis-web/src/app/engine/page.tsx
git commit -m "feat: wire model assist into live operator workspace"
```

---

### Task 6: Preserve the MVP Freeze With Regression Checks

**Files:**
- No production file changes in this task.

- [ ] **Step 1: Run backend regression tests**

Run from repo root:

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS.

- [ ] **Step 2: Run web static checks**

Run:

```bash
cd nepsis-web
npm run lint
npm run build
```

Expected: PASS.

- [ ] **Step 3: Run public-site e2e checks**

Run:

```bash
cd nepsis-web
npm run test:e2e -- --project=chrome-desktop
```

Expected: PASS. `/mvp` still runs without login or model keys, public model routes stay disabled, and `/operator` is gated.

- [ ] **Step 4: Run signed-in operator e2e checks**

Run:

```bash
cd nepsis-web
npm run test:e2e:auth -- --project=chrome-desktop
```

Expected: PASS.

- [ ] **Step 5: Run secret hygiene**

Run:

```bash
.venv/bin/python scripts/check_openai_secrets.py --all
```

Expected: PASS. No public-site env template or docs path should enable server model keys for the public demo deployment.

---

### Task 7: Update Docs and Smoke Scripts

**Files:**
- Modify: `README.md`
- Modify: `docs/operator-runbook.md`
- Modify: `docs/public-api.md`
- Modify: `nepsis-web/README.md`
- Modify: `scripts/site-smoke.sh`

- [ ] **Step 1: Update the public deployment docs**

Add this to the public deployment section:

```md
`/mvp` remains the public deterministic baseline. `/operator` is a separate live
operator surface and should only be enabled on an authenticated operator
deployment with backend API auth, login email delivery, and server-side model
configuration. Do not enable live model routes on the public demo deployment.
```

- [ ] **Step 2: Add operator deployment env docs**

Add this block to `nepsis-web/README.md`:

```md
Operator deployment mode:

- `NEPSIS_DEPLOYMENT_MODE=operator` or `NEXT_PUBLIC_NEPSIS_OPERATOR_SITE=true`
  enables the live/operator route family.
- `NEPSIS_LIVE_OPERATOR_ENABLED=true` exposes live operator UI affordances.
- `NEPSIS_MODEL_ROUTES_ENABLED=true` enables protected model routes only when
  the deployment is not public-site mode.
- `OPENAI_API_KEY` or `NEPSIS_OPENAI_API_KEY` must be configured server-side
  before `/api/operator/model` returns live model output.
- Browser-local provider keys are local-demo only and are not accepted by shared
  operator deployments.
```

- [ ] **Step 3: Update the public smoke script**

In `scripts/site-smoke.sh`, add `/operator` to the page checks:

```python
check("/operator")
```

Add an unauthenticated operator model-route check:

```python
check("/api/operator/model", method="POST", body={"mode": "draft_frame", "input": "smoke"}, expected={401, 403})
```

Keep the existing `/api/run-with-nepsis` and `/api/playground-nepsis` expected `403` checks for public production.

- [ ] **Step 4: Run docs and smoke checks**

Run:

```bash
bash -n scripts/site-smoke.sh
.venv/bin/python scripts/check_openai_secrets.py --all
```

Expected: PASS.

- [ ] **Step 5: Commit docs**

```bash
git add README.md docs/operator-runbook.md docs/public-api.md nepsis-web/README.md scripts/site-smoke.sh
git commit -m "docs: document live operator deployment"
```

---

## Rollout

1. Deploy the existing public site with `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true`; verify `/mvp` and `/status`.
2. Deploy a separate operator environment with backend URL/token, `NEPSIS_AUTH_SECRET`, email delivery, `NEPSIS_DEPLOYMENT_MODE=operator`, `NEPSIS_LIVE_OPERATOR_ENABLED=true`, `NEPSIS_MODEL_ROUTES_ENABLED=true`, and server-side model key.
3. Run public smoke against the public site and signed-in e2e against the operator environment.
4. Keep `/engine` available as the existing engineering console; make `/operator` the product-facing live path.

## Self-Review

- Spec coverage: `/mvp` stays frozen; `/operator` is separate; live mode is clearly labeled; backend/auth/model readiness is explicit; RED-before-BLUE runtime stays intact.
- Placeholder scan: no task relies on unspecified files or future implementation gaps.
- Type consistency: `OperatorModelMode`, `OperatorFrameDraft`, and `OperatorModelResponse` are defined once in `operatorModelClient.ts` and matched by `/api/operator/model`.

Plan complete and saved to `docs/superpowers/plans/2026-05-22-live-operator-path.md`.

Execution options:

1. Subagent-Driven (recommended): dispatch a fresh subagent per task, review between tasks, fast iteration.
2. Inline Execution: execute tasks in this session using executing-plans, with checkpoints.
