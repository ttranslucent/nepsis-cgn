# Visual Topology Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggleable Visual Topology Mode to the public `/mvp` demo so first-time stakeholders can see the RED -> STILL -> BLUE -> STILL -> commitment -> feedback -> audit flow before diving into raw telemetry.

**Architecture:** Keep the frozen MVP packet and API contract unchanged. Add a pure UI view-model builder that derives topology state from `NepsisMvpPacket`, render it in a focused React component, then integrate it into the existing `/mvp` client page with a segmented `Topology` / `Telemetry` switch. The raw packet panels and JSON remain available; the new mode is a presentation layer only.

**Tech Stack:** Next.js App Router, React 19, TypeScript, Tailwind CSS v4, Playwright e2e, existing bundled MVP fallback data.

---

## Branch

Use this branch for implementation:

```bash
git checkout codex/mvp-visual-topology-mode
```

If the branch does not exist in a fresh workspace:

```bash
git checkout -b codex/mvp-visual-topology-mode
```

## File Structure

- Modify: `nepsis-web/e2e/public-site.spec.ts`
  - Add e2e coverage proving the public MVP can toggle between topology and telemetry without login or model keys.
- Create: `nepsis-web/src/app/mvp/topology.ts`
  - Pure packet-to-topology mapper. No React. No network. No engine changes.
- Create: `nepsis-web/src/app/mvp/VisualTopologyMode.tsx`
  - Presentational component for the channel map, node states, and compact packet summary.
- Modify: `nepsis-web/src/app/mvp/page.tsx`
  - Add the result-view segmented control and render either `VisualTopologyMode` or the current telemetry panels.
- Modify: `docs/public-api.md`
  - Document that Visual Topology Mode is UI-only and does not add or alter public API fields.

## Design Rules

- Preserve the deterministic MVP boundary: no provider API calls, no auth requirement, no runtime session creation.
- Do not add a diagramming dependency for this pass. Use accessible HTML, CSS grid, and Tailwind classes.
- Default result view should be `Topology`; `Telemetry` exposes the current detailed panels and raw JSON.
- Do not remove raw JSON or existing packet guts. The goal is progressive disclosure, not simplification by deletion.
- Avoid ornamental animation. Dynamic state is shown through status, color, edge emphasis, and shape treatment.
- Keep RED before BLUE visually and semantically. BLUE may show as bounded when RED remains active.

---

### Task 1: Write Failing E2E Coverage

**Files:**
- Modify: `nepsis-web/e2e/public-site.spec.ts`

- [ ] **Step 1: Add topology assertions to the public MVP test**

Append this test after `public MVP can run without login or model key`:

```ts
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
```

- [ ] **Step 2: Run the targeted e2e test and verify it fails**

Run:

```bash
cd nepsis-web
npm run test:e2e -- --project=chrome-desktop -g "public MVP exposes topology mode before raw telemetry"
```

Expected: fail because the `Visual topology mode` region and `Topology` / `Telemetry` controls do not exist yet.

- [ ] **Step 3: Commit the failing test**

```bash
git add nepsis-web/e2e/public-site.spec.ts
git commit -m "test: cover public MVP topology mode"
```

---

### Task 2: Add the Packet-to-Topology View Model

**Files:**
- Create: `nepsis-web/src/app/mvp/topology.ts`

- [ ] **Step 1: Create the pure topology mapper**

Create `nepsis-web/src/app/mvp/topology.ts` with:

```ts
import type { NepsisMvpPacket } from "@/lib/engineClient";

export type MvpTopologyNodeId =
  | "red"
  | "still_1"
  | "blue"
  | "still_2"
  | "commitment"
  | "feedback"
  | "audit";

export type MvpTopologyStatus = "idle" | "clear" | "active" | "bounded" | "hold" | "ready" | "blocked";

export type MvpTopologyNode = {
  id: MvpTopologyNodeId;
  label: string;
  eyebrow: string;
  status: MvpTopologyStatus;
  statusLabel: string;
  summary: string;
  metrics: Array<{ label: string; value: string }>;
};

export type MvpTopologyEdge = {
  from: MvpTopologyNodeId;
  to: MvpTopologyNodeId;
  label: string;
  emphasized: boolean;
};

export type MvpTopologyModel = {
  headline: string;
  subhead: string;
  nodes: MvpTopologyNode[];
  edges: MvpTopologyEdge[];
  activeFacts: string[];
};

export function buildMvpTopology(packet: NepsisMvpPacket): MvpTopologyModel {
  const redActive = packet.red_channel.escalation_required || packet.red_channel.active_hazards.length > 0;
  const contradictionActive = packet.contradiction_monitor.contradictions.length > 0;
  const retessellationRequired = packet.denominator_collapse.retessellation_required;
  const still1 = packet.still.checkpoints.find((checkpoint) => checkpoint.position === "after_red_before_blue");
  const still2 = packet.still.checkpoints.find((checkpoint) => checkpoint.position === "after_blue_before_commitment");
  const readiness = packet.still.commitment_readiness.status;
  const blueBounded = redActive && packet.blue_channel.hypotheses.length > 0;
  const feedbackStatus = packet.state_feedback.loop_decision.status;

  const nodes: MvpTopologyNode[] = [
    {
      id: "red",
      label: "RED Channel",
      eyebrow: "Constraint and hazard gate",
      status: redActive ? "active" : "clear",
      statusLabel: redActive ? "ACTIVE" : "CLEAR",
      summary: packet.red_channel.rationale,
      metrics: [
        { label: "Hazards", value: String(packet.red_channel.active_hazards.length) },
        { label: "Missing discriminators", value: String(packet.red_channel.missing_discriminators.length) },
      ],
    },
    {
      id: "still_1",
      label: "STILL 1",
      eyebrow: "Before BLUE",
      status: still1?.trigger_status === "hold" ? "hold" : "ready",
      statusLabel: still1?.trigger_status?.toUpperCase() ?? "READY",
      summary: still1?.reason ?? "No pre-BLUE checkpoint was emitted.",
      metrics: [{ label: "Required checks", value: String(still1?.required_before_commitment.length ?? 0) }],
    },
    {
      id: "blue",
      label: "BLUE Channel",
      eyebrow: "Bounded hypothesis work",
      status: blueBounded ? "bounded" : "active",
      statusLabel: blueBounded ? "BOUNDED" : "ACTIVE",
      summary: blueBounded
        ? "BLUE can explain candidate interpretations, but cannot clear an unresolved RED boundary."
        : "BLUE is available for hypothesis comparison.",
      metrics: [
        { label: "Hypotheses", value: String(packet.blue_channel.hypotheses.length) },
        { label: "Axes", value: String(Object.keys(packet.blue_channel.evaluation_axes).length) },
      ],
    },
    {
      id: "still_2",
      label: "STILL 2",
      eyebrow: "Before commitment",
      status: still2?.trigger_status === "hold" ? "hold" : readiness === "ready" ? "ready" : "blocked",
      statusLabel: still2?.trigger_status?.toUpperCase() ?? readiness.toUpperCase(),
      summary: still2?.reason ?? packet.still.commitment_readiness.rationale,
      metrics: [{ label: "Readiness", value: readiness }],
    },
    {
      id: "commitment",
      label: "Commitment",
      eyebrow: "Voronoi selection",
      status: retessellationRequired ? "blocked" : "ready",
      statusLabel: retessellationRequired ? "RETESSELLATE" : "READY",
      summary: packet.voronoi_commitment.recommended_action,
      metrics: [{ label: "Threshold", value: packet.voronoi_commitment.threshold_basis }],
    },
    {
      id: "feedback",
      label: "State feedback",
      eyebrow: "Predicted next state",
      status: feedbackStatus === "continue" ? "active" : "hold",
      statusLabel: feedbackStatus.toUpperCase(),
      summary: packet.state_feedback.loop_decision.next_observation_required,
      metrics: [{ label: "Observed", value: packet.state_feedback.observed_next_state.status }],
    },
    {
      id: "audit",
      label: "Audit",
      eyebrow: "Packet lineage",
      status: "active",
      statusLabel: "RECORDED",
      summary: packet.final_output.concise_recommendation,
      metrics: [
        { label: "Events", value: String(packet.audit_trace.length) },
        { label: "Schema", value: packet.schema_version },
      ],
    },
  ];

  return {
    headline: contradictionActive ? "Constraint conflict detected" : "No contradiction detected",
    subhead: retessellationRequired ? "Retessellation required" : "Current topology is commitment-ready",
    nodes,
    edges: [
      { from: "red", to: "still_1", label: redActive ? "holds boundary" : "permits", emphasized: redActive },
      { from: "still_1", to: "blue", label: blueBounded ? "bounded entry" : "entry", emphasized: blueBounded },
      { from: "blue", to: "still_2", label: "returns to check", emphasized: true },
      { from: "still_2", to: "commitment", label: retessellationRequired ? "blocks closure" : "permits", emphasized: retessellationRequired },
      { from: "commitment", to: "feedback", label: "predicts next state", emphasized: true },
      { from: "feedback", to: "audit", label: "records lineage", emphasized: true },
    ],
    activeFacts: [
      `Contradiction density: ${packet.contradiction_monitor.contradiction_density}`,
      `Density basis: ${packet.contradiction_monitor.density_basis.model}`,
      `Denominator collapse: ${packet.denominator_collapse.detected ? "detected" : "clear"}`,
      `ZeroBack: ${packet.zeroback.triggered ? "triggered" : "clear"}`,
    ],
  };
}
```

- [ ] **Step 2: Run lint and verify the new file type-checks through ESLint**

Run:

```bash
cd nepsis-web
npm run lint
```

Expected: pass. If lint reports an unused export, keep the type only if it is used by `VisualTopologyMode` in the next task; otherwise remove it before committing.

- [ ] **Step 3: Commit the view model**

```bash
git add nepsis-web/src/app/mvp/topology.ts
git commit -m "feat: derive MVP topology view model"
```

---

### Task 3: Add the Visual Topology Component

**Files:**
- Create: `nepsis-web/src/app/mvp/VisualTopologyMode.tsx`

- [ ] **Step 1: Create the component**

Create `nepsis-web/src/app/mvp/VisualTopologyMode.tsx` with:

```tsx
import type { NepsisMvpPacket } from "@/lib/engineClient";

import { buildMvpTopology, type MvpTopologyNode, type MvpTopologyStatus } from "./topology";

const STATUS_CLASS: Record<MvpTopologyStatus, string> = {
  idle: "border-nepsis-border bg-black/20 text-nepsis-muted",
  clear: "border-emerald-300/45 bg-emerald-400/10 text-emerald-100",
  active: "border-red-300/55 bg-red-500/10 text-red-100",
  bounded: "border-sky-300/55 bg-sky-500/10 text-sky-100",
  hold: "border-nepsis-accent/70 bg-nepsis-accent/10 text-nepsis-accentSoft",
  ready: "border-emerald-300/55 bg-emerald-400/10 text-emerald-100",
  blocked: "border-red-300/60 bg-red-500/15 text-red-100",
};

export function VisualTopologyMode({ packet }: { packet: NepsisMvpPacket }) {
  const topology = buildMvpTopology(packet);

  return (
    <section
      aria-label="Visual topology mode"
      className="rounded-3xl border border-nepsis-border bg-nepsis-panel p-5 md:p-6"
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(18rem,24rem)] lg:items-start">
        <div>
          <div className="text-xs uppercase tracking-[0.14em] text-nepsis-muted">Visual topology mode</div>
          <h2 className="mt-2 text-xl font-semibold">{topology.headline}</h2>
          <p className="mt-2 text-sm text-nepsis-muted">{topology.subhead}</p>
        </div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
          {topology.activeFacts.map((fact) => (
            <div key={fact} className="rounded-2xl border border-nepsis-border bg-black/20 px-3 py-2 text-xs text-nepsis-text">
              {fact}
            </div>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-3 xl:grid-cols-[1fr_1fr_1fr_1fr_1fr_1fr_1fr]">
        {topology.nodes.map((node, index) => (
          <TopologyNodeCard
            key={node.id}
            node={node}
            edgeLabel={topology.edges[index]?.label}
            edgeEmphasized={topology.edges[index]?.emphasized ?? false}
            isLast={index === topology.nodes.length - 1}
          />
        ))}
      </div>
    </section>
  );
}

function TopologyNodeCard({
  node,
  edgeLabel,
  edgeEmphasized,
  isLast,
}: {
  node: MvpTopologyNode;
  edgeLabel?: string;
  edgeEmphasized: boolean;
  isLast: boolean;
}) {
  return (
    <div className="relative min-w-0">
      <div className={`min-h-64 rounded-2xl border p-4 ${STATUS_CLASS[node.status]}`}>
        <div className="text-[11px] uppercase tracking-[0.12em] opacity-80">{node.eyebrow}</div>
        <h3 className="mt-2 text-base font-semibold">{node.label}</h3>
        <div className="mt-3 inline-flex rounded-full border border-current/35 px-2 py-1 font-mono text-[11px]">
          {node.statusLabel}
        </div>
        <p className="mt-3 text-sm leading-relaxed text-nepsis-text">{node.summary}</p>
        <div className="mt-4 space-y-2">
          {node.metrics.map((metric) => (
            <div key={`${node.id}-${metric.label}`} className="rounded-xl border border-white/10 bg-black/20 px-3 py-2">
              <div className="text-[10px] uppercase tracking-[0.12em] text-nepsis-muted">{metric.label}</div>
              <div className="mt-1 break-words text-xs text-nepsis-text">{metric.value}</div>
            </div>
          ))}
        </div>
      </div>
      {!isLast && edgeLabel && (
        <div className="mt-2 flex items-center gap-2 text-[11px] uppercase tracking-[0.12em] text-nepsis-muted xl:absolute xl:left-[calc(100%+0.2rem)] xl:top-1/2 xl:z-10 xl:mt-0 xl:w-24 xl:-translate-y-1/2">
          <span className={`h-px flex-1 ${edgeEmphasized ? "bg-nepsis-accent" : "bg-nepsis-border"}`} />
          <span className="max-w-20 text-center">{edgeLabel}</span>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Run lint**

Run:

```bash
cd nepsis-web
npm run lint
```

Expected: pass. If line length or class formatting warnings appear, run the repo's existing formatter if one is configured; otherwise adjust manually.

- [ ] **Step 3: Commit the component**

```bash
git add nepsis-web/src/app/mvp/VisualTopologyMode.tsx
git commit -m "feat: add MVP visual topology component"
```

---

### Task 4: Integrate the Toggle Into `/mvp`

**Files:**
- Modify: `nepsis-web/src/app/mvp/page.tsx`

- [ ] **Step 1: Import the component**

Add this import near the existing imports:

```tsx
import { VisualTopologyMode } from "./VisualTopologyMode";
```

- [ ] **Step 2: Add the result view mode state**

Inside `MvpDemoPage`, below existing state declarations:

```tsx
const [resultView, setResultView] = useState<"topology" | "telemetry">("topology");
```

- [ ] **Step 3: Keep the default view topology when running a new packet**

Inside `runDemo`, immediately before `setPacket(result);`:

```tsx
setResultView("topology");
```

- [ ] **Step 4: Pass view state to `PacketView`**

Replace:

```tsx
{packet ? <PacketView packet={packet} /> : <EmptyState />}
```

with:

```tsx
{packet ? (
  <PacketView packet={packet} resultView={resultView} onResultViewChange={setResultView} />
) : (
  <EmptyState />
)}
```

- [ ] **Step 5: Update the `PacketView` signature and add the segmented control**

Replace:

```tsx
function PacketView({ packet }: { packet: NepsisMvpPacket }) {
```

with:

```tsx
function PacketView({
  packet,
  resultView,
  onResultViewChange,
}: {
  packet: NepsisMvpPacket;
  resultView: "topology" | "telemetry";
  onResultViewChange: (value: "topology" | "telemetry") => void;
}) {
```

Then replace the opening return:

```tsx
return (
  <div className="mt-5 space-y-5">
```

with:

```tsx
return (
  <div className="mt-5 space-y-5">
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-3xl border border-nepsis-border bg-nepsis-panel p-3">
      <div className="text-xs uppercase tracking-[0.14em] text-nepsis-muted">Result view</div>
      <div className="inline-flex rounded-full border border-nepsis-border bg-black/20 p-1">
        {(["topology", "telemetry"] as const).map((view) => {
          const selected = resultView === view;
          return (
            <button
              key={view}
              type="button"
              aria-pressed={selected}
              onClick={() => onResultViewChange(view)}
              className={`rounded-full px-4 py-2 text-sm font-semibold capitalize transition ${
                selected ? "bg-nepsis-accent text-black" : "text-nepsis-muted hover:text-nepsis-text"
              }`}
            >
              {view}
            </button>
          );
        })}
      </div>
    </div>

    {resultView === "topology" ? (
      <VisualTopologyMode packet={packet} />
    ) : (
      <>
```

At the end of `PacketView`, immediately before the closing `</div>` for the wrapper, close the telemetry fragment:

```tsx
      </>
    )}
  </div>
);
```

The existing telemetry sections should remain inside the `<>...</>` fragment unchanged.

- [ ] **Step 6: Run the targeted e2e test**

Run:

```bash
cd nepsis-web
npm run test:e2e -- --project=chrome-desktop -g "public MVP exposes topology mode before raw telemetry"
```

Expected: pass.

- [ ] **Step 7: Run the existing public MVP e2e test**

Run:

```bash
cd nepsis-web
npm run test:e2e -- --project=chrome-desktop -g "public MVP can run without login or model key"
```

Expected: fail at first if it still expects telemetry fields without switching modes. Fix the test by clicking `Telemetry` before asserting `Evaluation axes`, `action_priority`, and raw packet text:

```ts
await page.getByRole("button", { name: "Telemetry" }).click();
await expect(page.getByText("Evaluation axes", { exact: true })).toBeVisible();
await expect(page.locator("main")).toContainText("action_priority");
```

Run the test again.

- [ ] **Step 8: Commit the integration**

```bash
git add nepsis-web/src/app/mvp/page.tsx nepsis-web/e2e/public-site.spec.ts
git commit -m "feat: toggle MVP topology and telemetry views"
```

---

### Task 5: Document Public API Non-Change

**Files:**
- Modify: `docs/public-api.md`

- [ ] **Step 1: Add a short UI note**

Append this section:

```md
## Public MVP Visual Topology Mode

The `/mvp` page may render a Visual Topology Mode for stakeholder review. This is a browser-side view over the canonical `nepsis.mvp_packet` response.

Visual Topology Mode does not add public API fields, does not require login, does not call provider models, and does not create runtime engine sessions. The raw telemetry and JSON packet remain available from the same page through the `Telemetry` result view.
```

- [ ] **Step 2: Commit the documentation**

```bash
git add docs/public-api.md
git commit -m "docs: describe MVP topology mode boundary"
```

---

### Task 6: Full Verification

**Files:**
- No source changes expected.

- [ ] **Step 1: Run Python tests from repo root**

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run web lint**

```bash
cd nepsis-web
npm run lint
```

Expected: pass.

- [ ] **Step 3: Run production build**

```bash
cd nepsis-web
npm run build
```

Expected: pass.

- [ ] **Step 4: Run public e2e coverage**

```bash
cd nepsis-web
npm run test:e2e -- --project=chrome-desktop -g "public MVP"
```

Expected: the topology test and existing public MVP test pass.

- [ ] **Step 5: Run site smoke script against local or deployed app**

For local Next:

```bash
scripts/site-smoke.sh http://127.0.0.1:3000
```

For production after deploy:

```bash
scripts/site-smoke.sh https://nepsis-cgn.vercel.app
```

Expected: `/mvp`, `/status`, public model-route gating, and `/api/engine/mvp` checks pass.

- [ ] **Step 6: Browser verification**

Open `/mvp`, run both deterministic cases, and check:

- Topology mode is the default result view after each run.
- RED appears before BLUE.
- Clinical case preserves RED hazard gating before BLUE.
- Jailing case shows constraint conflict and retessellation.
- Telemetry mode exposes the existing detailed panels and raw JSON.
- Text does not overlap at mobile width or desktop width.

- [ ] **Step 7: Final commit if verification changed tests or docs**

```bash
git status --short
git add <changed-files>
git commit -m "test: verify MVP topology mode"
```

If no files changed, do not create an empty commit.

---

## Self-Review

- Spec coverage: The plan adds a top-level toggle, a clean high-level map, dynamic channel status, preservation of raw telemetry, and public no-login behavior.
- Boundary check: The plan does not modify Python packet builders, FastAPI routes, Next API routes, or provider-key behavior.
- Type consistency: `MvpTopologyStatus`, `MvpTopologyNode`, and `MvpTopologyModel` are defined before use. `VisualTopologyMode` consumes only `NepsisMvpPacket`.
- Placeholder scan: No placeholder markers, deferred implementation, or unspecified tests remain.
