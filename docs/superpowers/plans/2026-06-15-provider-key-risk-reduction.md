# Provider Key Risk Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove browser/user OpenAI API key collection from the NepsisCGN web app and keep all Nepsis-hosted model calls behind signed-in operator routes with server-side credentials only.

**Architecture:** NepsisCGN should not collect, persist, or proxy individual user provider API keys. The private operator deployment uses one reviewed server-side provider credential, guarded by auth, CSRF, proposal receipts, status checks, and deployment hygiene. True bring-your-own-model access belongs outside the Nepsis web app through MCP-capable clients or future OAuth-style provider connectors, not raw API key entry.

**Tech Stack:** Next.js App Router route handlers, React client pages, TypeScript env gating, FastAPI backend proxy, Python pytest artifact tests, shell launchers.

---

## Hard Recommendation

Do not implement account-bound raw API key storage in NepsisCGN now.

Use this posture instead:

- Public `/mvp`: deterministic, model-free, no provider keys.
- Local private demo: signed-in operator UI, backend running, server-side `OPENAI_API_KEY` optional for live model assist.
- Shared private operator deployment: real OTP login, backend auth, server-side provider key only, rate limits/caps added separately.
- User-owned model access: MCP/ChatGPT/Codex/Claude/Gemini host authenticates to its own model provider and calls Nepsis tools. Nepsis receives packets/tool inputs, not provider keys.

Reason: raw user API keys in browser storage or app databases create avoidable custody, XSS, support, rotation, billing, and multi-user isolation risk. The easiest safe user experience is "sign in to Nepsis; Nepsis runs the private operator route with configured server credentials" for private demos, and "connect your model host to Nepsis MCP" for true bring-your-own account usage.

## File Structure

- Modify `nepsis-web/src/lib/publicMode.ts`: remove `browserModelKeysAllowed()` so no runtime path accepts browser-submitted provider keys.
- Modify `nepsis-web/src/lib/clientStorage.ts`: remove API-key getters/setters; keep only legacy cleanup and connection-notice helpers if still needed.
- Modify `nepsis-web/src/app/settings/page.tsx`: convert from key-entry UI to provider-access status/legacy-key cleanup UI.
- Modify `nepsis-web/src/app/playground/page.tsx`: remove browser-key state and send no `apiKey` field.
- Modify `nepsis-web/src/app/api/playground-nepsis/route.ts`: remove `apiKey` request handling; require server-side key.
- Modify `nepsis-web/src/app/api/run-with-nepsis/route.ts`: remove `apiKey` request handling; require server-side key.
- Modify `nepsis-web/src/app/engine/page.tsx`: remove browser-key state, settings prompts, and sandbox request `apiKey`; describe sandbox as server-key backed.
- Modify `scripts/check_openai_secrets.py`: reject deprecated browser-key env flags and keep blocking public/operator unsafe combinations.
- Modify `tests/test_public_deployment_artifacts.py`: add artifact tests proving browser key storage and browser-submitted `apiKey` paths are gone.
- Modify `tests/test_openai_secret_hygiene.py`: add scanner tests for deprecated browser-key env flags.
- Modify `tests/test_local_mvp_launcher.py`: prove local/private launchers do not enable browser-key ingestion.
- Modify docs: `README.md`, `nepsis-web/README.md`, `docs/operator-runbook.md`, `docs/public-api.md`.

## Task 1: Pin The New Secret-Custody Contract In Tests

**Files:**
- Modify: `tests/test_public_deployment_artifacts.py`
- Modify: `tests/test_openai_secret_hygiene.py`
- Modify: `tests/test_local_mvp_launcher.py`

- [ ] **Step 1: Add artifact test that browser key storage is removed**

Append to `tests/test_public_deployment_artifacts.py`:

```python
def test_browser_provider_key_storage_is_removed_from_web_runtime() -> None:
    src = ROOT / "nepsis-web" / "src"
    files = [
        src / "lib" / "clientStorage.ts",
        src / "lib" / "publicMode.ts",
        src / "app" / "settings" / "page.tsx",
        src / "app" / "playground" / "page.tsx",
        src / "app" / "engine" / "page.tsx",
        src / "app" / "api" / "playground-nepsis" / "route.ts",
        src / "app" / "api" / "run-with-nepsis" / "route.ts",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "browserModelKeysAllowed" not in combined
    assert "getStoredOpenAiKey" not in combined
    assert "hasStoredOpenAiKey" not in combined
    assert "localStorage.setItem(OPENAI_KEY_STORAGE_KEY" not in combined
    assert "nepsis_openai_key" in combined
    assert "clearLegacyOpenAiKey" in combined
    assert "apiKey:" not in (src / "app" / "playground" / "page.tsx").read_text(encoding="utf-8")
    assert "apiKey:" not in (src / "app" / "engine" / "page.tsx").read_text(encoding="utf-8")
```

- [ ] **Step 2: Add route tests that browser-submitted keys are ignored by construction**

Append to `tests/test_public_deployment_artifacts.py`:

```python
def test_model_sandbox_routes_require_server_side_provider_key_only() -> None:
    playground = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "playground-nepsis" / "route.ts"
    ).read_text(encoding="utf-8")
    run_with_nepsis = (
        ROOT / "nepsis-web" / "src" / "app" / "api" / "run-with-nepsis" / "route.ts"
    ).read_text(encoding="utf-8")

    for text in (playground, run_with_nepsis):
        assert "requireEngineControlAuth" in text
        assert "requireCsrfToken" in text
        assert "hasConfiguredOpenAiKey" in text
        assert "createOpenAiClient()" in text
        assert "apiKey" not in text
        assert "apiKeyOverride" not in text
        assert "browserModelKeysAllowed" not in text
```

- [ ] **Step 3: Add scanner test for deprecated browser-key env flag**

Append to `tests/test_openai_secret_hygiene.py`:

```python
def test_scan_blocks_deprecated_browser_model_key_flag(tmp_path: Path) -> None:
    target = tmp_path / ".env.local"
    target.write_text("NEPSIS_BROWSER_MODEL_KEYS_ALLOWED=true\n", encoding="utf-8")

    result = run_scan(target)

    assert result.returncode == 1
    assert "NEPSIS_BROWSER_MODEL_KEYS_ALLOWED is deprecated" in result.stdout
```

- [ ] **Step 4: Add launcher guard test**

Append to `tests/test_local_mvp_launcher.py`:

```python
def test_local_launchers_do_not_enable_browser_provider_key_ingestion() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in [SCRIPT, OPERATOR_SCRIPT]
    )

    assert "NEPSIS_BROWSER_MODEL_KEYS_ALLOWED" not in combined
```

- [ ] **Step 5: Run tests and confirm failure**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_public_deployment_artifacts.py::test_browser_provider_key_storage_is_removed_from_web_runtime tests/test_public_deployment_artifacts.py::test_model_sandbox_routes_require_server_side_provider_key_only tests/test_openai_secret_hygiene.py::test_scan_blocks_deprecated_browser_model_key_flag tests/test_local_mvp_launcher.py::test_local_launchers_do_not_enable_browser_provider_key_ingestion
```

Expected: failures showing browser key helpers, `apiKey` payloads, and scanner support still exist.

## Task 2: Remove Browser Key Storage Helpers And Deprecated Env Gate

**Files:**
- Modify: `nepsis-web/src/lib/clientStorage.ts`
- Modify: `nepsis-web/src/lib/publicMode.ts`
- Modify: `scripts/check_openai_secrets.py`

- [ ] **Step 1: Replace `clientStorage.ts` with legacy cleanup only**

Replace `nepsis-web/src/lib/clientStorage.ts` with:

```ts
const LEGACY_OPENAI_KEY_STORAGE_KEY = "nepsis_openai_key";
export const LLM_CONNECTED_NOTICE_KEY = "nepsis_llm_connected_notice";

export function clearLegacyOpenAiKey(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const hadKey = window.localStorage.getItem(LEGACY_OPENAI_KEY_STORAGE_KEY) !== null;
    window.localStorage.removeItem(LEGACY_OPENAI_KEY_STORAGE_KEY);
    window.localStorage.removeItem(LLM_CONNECTED_NOTICE_KEY);
    return hadKey;
  } catch {
    return false;
  }
}

export function consumeConnectedNotice(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const hasNotice = window.localStorage.getItem(LLM_CONNECTED_NOTICE_KEY) === "1";
    if (hasNotice) {
      window.localStorage.removeItem(LLM_CONNECTED_NOTICE_KEY);
    }
    return hasNotice;
  } catch {
    return false;
  }
}
```

- [ ] **Step 2: Remove browser key env gate**

In `nepsis-web/src/lib/publicMode.ts`, delete:

```ts
export function browserModelKeysAllowed(): boolean {
  return process.env.NODE_ENV !== "production" && !publicSiteMode() && envFlag("NEPSIS_BROWSER_MODEL_KEYS_ALLOWED");
}
```

- [ ] **Step 3: Make scanner reject deprecated flag**

In `scripts/check_openai_secrets.py`, add near env constants:

```python
DEPRECATED_BROWSER_KEY_FLAGS = {"NEPSIS_BROWSER_MODEL_KEYS_ALLOWED"}
```

Inside `_scan_text`, after collecting `assignments`, add:

```python
    for name in sorted(DEPRECATED_BROWSER_KEY_FLAGS):
        assignment = assignments.get(name)
        if assignment and assignment.value.strip():
            issues.append(
                Issue(
                    path=path,
                    line=assignment.line,
                    message=(
                        f"{name} is deprecated. NepsisCGN must not accept browser-submitted "
                        "provider API keys; use server-side operator credentials or MCP host auth."
                    ),
                )
            )
```

- [ ] **Step 4: Run focused helper tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_openai_secret_hygiene.py::test_scan_blocks_deprecated_browser_model_key_flag tests/test_local_mvp_launcher.py::test_local_launchers_do_not_enable_browser_provider_key_ingestion
```

Expected: pass.

## Task 3: Convert Settings From Key Entry To Access Status

**Files:**
- Modify: `nepsis-web/src/app/settings/page.tsx`

- [ ] **Step 1: Replace settings page**

Replace `nepsis-web/src/app/settings/page.tsx` with:

```tsx
"use client";

import { useEffect, useState } from "react";

import { clearLegacyOpenAiKey } from "@/lib/clientStorage";
import { publicSiteMode } from "@/lib/publicMode";

export default function SettingsPage() {
  const [message, setMessage] = useState<string | null>(null);
  const publicMode = publicSiteMode();

  useEffect(() => {
    if (clearLegacyOpenAiKey()) {
      setMessage("Removed a legacy browser-stored OpenAI key from this browser.");
    }
  }, []);

  function clearLegacyKey() {
    const removed = clearLegacyOpenAiKey();
    setMessage(
      removed
        ? "Removed a legacy browser-stored OpenAI key from this browser."
        : "No legacy browser-stored OpenAI key was present.",
    );
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 md:px-6 md:py-12">
      <section className="rounded-2xl border border-nepsis-border bg-nepsis-panel p-6 md:p-7">
        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-nepsis-muted">
          {publicMode ? "Public site mode" : "Provider access"}
        </div>
        <h1 className="mt-3 text-2xl font-semibold">Model Access</h1>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-nepsis-muted">
          NepsisCGN does not collect or store user provider API keys in the browser. Public MVP runs are deterministic
          and model-free. Private operator model assistance uses reviewed server-side credentials, while user-owned
          model accounts should connect through MCP-capable hosts such as ChatGPT, Codex, Claude, or Gemini.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <a
            href="/mvp"
            className="rounded-full bg-nepsis-accent px-4 py-2 text-sm font-semibold text-black transition hover:bg-nepsis-accentSoft"
          >
            Run MVP Demo
          </a>
          <a
            href="/status"
            className="rounded-full border border-nepsis-border px-4 py-2 text-sm transition hover:border-nepsis-accent"
          >
            System Status
          </a>
          <button
            type="button"
            onClick={clearLegacyKey}
            className="rounded-full border border-red-500/40 px-4 py-2 text-sm text-red-300 transition hover:border-red-400"
          >
            Clear Legacy Browser Key
          </button>
        </div>
        {message && <p className="mt-3 text-xs text-nepsis-muted">{message}</p>}
      </section>
    </div>
  );
}
```

- [ ] **Step 2: Run frontend artifact test**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_public_deployment_artifacts.py::test_browser_provider_key_storage_is_removed_from_web_runtime
```

Expected: still fails until API and engine/playground paths are updated, but no settings-specific key-entry failures remain.

## Task 4: Remove Browser Key Payloads From Playground And Sandbox Routes

**Files:**
- Modify: `nepsis-web/src/app/api/playground-nepsis/route.ts`
- Modify: `nepsis-web/src/app/api/run-with-nepsis/route.ts`
- Modify: `nepsis-web/src/app/playground/page.tsx`

- [ ] **Step 1: Update playground route request type and key handling**

In `nepsis-web/src/app/api/playground-nepsis/route.ts`:

```ts
import { modelRoutesEnabled } from "@/lib/publicMode";
```

Replace request type with:

```ts
type PlaygroundRequest = {
  prompt?: string;
  packId?: string;
  model?: string;
};
```

Replace:

```ts
  const { prompt, packId, apiKey, model } = body as PlaygroundRequest;
  const effectiveApiKey = browserModelKeysAllowed() ? apiKey ?? null : null;
```

with:

```ts
  const { prompt, packId, model } = body as PlaygroundRequest;
```

Replace:

```ts
  if (!effectiveApiKey?.trim() && !hasConfiguredOpenAiKey()) {
```

with:

```ts
  if (!hasConfiguredOpenAiKey()) {
```

Replace:

```ts
    const completion = await createOpenAiClient(effectiveApiKey).responses.create({
```

with:

```ts
    const completion = await createOpenAiClient().responses.create({
```

- [ ] **Step 2: Update run-with-nepsis route**

In `nepsis-web/src/app/api/run-with-nepsis/route.ts`:

```ts
import { modelRoutesEnabled } from "@/lib/publicMode";
```

Replace:

```ts
    const { prompt, apiKey, model } = await req.json();
    const browserApiKey = typeof apiKey === "string" ? apiKey : null;
    const effectiveApiKey = browserModelKeysAllowed() ? browserApiKey : null;
```

with:

```ts
    const { prompt, model } = await req.json();
```

Replace:

```ts
    if (!effectiveApiKey?.trim() && !hasConfiguredOpenAiKey()) {
```

with:

```ts
    if (!hasConfiguredOpenAiKey()) {
```

Replace:

```ts
    const completion = await createOpenAiClient(effectiveApiKey).responses.create({
```

with:

```ts
    const completion = await createOpenAiClient().responses.create({
```

- [ ] **Step 3: Update playground client page**

In `nepsis-web/src/app/playground/page.tsx`, remove:

```ts
import { getStoredOpenAiKey, hasStoredOpenAiKey } from "@/lib/clientStorage";
```

Remove `hasBrowserKey` state and set:

```ts
const keyReady = hasServerKey === true;
```

In the status text, render:

```tsx
OpenAI key:{" "}
{hasServerKey === null ? "checking..." : hasServerKey ? "server key configured" : "server key missing"}
```

Replace the missing-key error with:

```ts
setError("Server-side OpenAI key required. Configure the private operator deployment before running Playground.");
```

Replace the POST body with:

```ts
body: JSON.stringify({
  prompt,
  packId,
}),
```

Replace the settings link with a status link:

```tsx
{!keyReady && hasServerKey !== null && (
  <a href="/status" className="ml-3 text-xs font-semibold text-nepsis-accent hover:underline">
    Open Status
  </a>
)}
```

- [ ] **Step 4: Run route tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_public_deployment_artifacts.py::test_model_sandbox_routes_require_server_side_provider_key_only
```

Expected: pass after engine page is updated in Task 5.

## Task 5: Remove Browser Key State From Engine Sandbox

**Files:**
- Modify: `nepsis-web/src/app/engine/page.tsx`

- [ ] **Step 1: Update imports**

Replace:

```ts
import {
  consumeConnectedNotice,
  getStoredOpenAiKey,
  hasStoredOpenAiKey,
} from "@/lib/clientStorage";
```

with:

```ts
import { consumeConnectedNotice } from "@/lib/clientStorage";
```

- [ ] **Step 2: Remove key state**

Delete:

```ts
const [hasConnectedKey, setHasConnectedKey] = useState<boolean | null>(null);
```

In the connected notice effect, replace the key lookup block with:

```ts
let connected = connectedFromQuery;
try {
  connected = connected || consumeConnectedNotice();
} catch {}
setShowConnectedNotice(connected);
```

Delete the `llmKeyLabel` constant.

- [ ] **Step 3: Remove apiKey from detached sandbox POST**

Replace:

```ts
const apiKey = getStoredOpenAiKey();
const res = await fetch("/api/run-with-nepsis", {
  method: "POST",
  headers: withCsrfHeader({ "Content-Type": "application/json" }),
  body: JSON.stringify({
    prompt: text,
    model: detachedModel,
    apiKey: apiKey ?? undefined,
  }),
});
```

with:

```ts
const res = await fetch("/api/run-with-nepsis", {
  method: "POST",
  headers: withCsrfHeader({ "Content-Type": "application/json" }),
  body: JSON.stringify({
    prompt: text,
    model: detachedModel,
  }),
});
```

- [ ] **Step 4: Replace browser-key warning**

Delete the `hasConnectedKey === false` warning block that links to `/settings`.

Add a server-key warning near the model sandbox button area:

```tsx
{userMode && (
  <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
    <span>Model sandbox and assist routes require private server-side provider configuration. NepsisCGN does not collect browser API keys.</span>
    <a href="/status" className="rounded-full border border-amber-400/50 px-3 py-1 hover:border-amber-300">
      Open Status
    </a>
  </div>
)}
```

- [ ] **Step 5: Run artifact tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_public_deployment_artifacts.py::test_browser_provider_key_storage_is_removed_from_web_runtime tests/test_public_deployment_artifacts.py::test_model_sandbox_routes_require_server_side_provider_key_only
```

Expected: pass.

## Task 6: Update Documentation And Local Operator Language

**Files:**
- Modify: `README.md`
- Modify: `nepsis-web/README.md`
- Modify: `docs/operator-runbook.md`
- Modify: `docs/public-api.md`
- Modify: `scripts/operator-local.sh`

- [ ] **Step 1: Update root README key guidance**

In `README.md`, replace the browser-key limitation bullet:

```md
- Browser-stored OpenAI keys are local-demo only; do not use them as shared deployment secrets.
```

with:

```md
- NepsisCGN does not collect browser/user provider API keys. Hosted model calls require reviewed server-side private operator credentials; bring-your-own-model workflows should use MCP-capable hosts that authenticate to their own provider accounts.
```

Also update the "Open Model Harness Direction" paragraph to state that raw provider key collection has been removed from the web app.

- [ ] **Step 2: Update web README**

In `nepsis-web/README.md`, replace lines describing browser-local provider keys with:

```md
- Browser-local provider keys are not accepted by NepsisCGN web routes. The web app no longer stores OpenAI keys in localStorage.
- `/settings` only reports provider-access posture and clears any legacy browser-stored key.
```

- [ ] **Step 3: Update operator runbook**

In `docs/operator-runbook.md`, replace:

```md
- Browser-stored OpenAI keys are local-demo only. Do not use them as a shared
  deployment secret flow.
```

with:

```md
- Browser-stored OpenAI keys are not supported. Do not ask operators or visitors to paste provider keys into NepsisCGN.
```

- [ ] **Step 4: Update public API docs**

In `docs/public-api.md`, ensure the MCP section says:

```md
MCP clients should authenticate to their own model provider separately. NepsisCGN does not proxy visitor OpenAI, Claude, or Gemini accounts through the public web site, and the web app does not collect raw provider API keys.
```

- [ ] **Step 5: Update local launcher status line**

In `scripts/operator-local.sh`, keep server-side key detection, but make the message explicit:

```bash
printf 'Model:   no server-side OPENAI_API_KEY/NEPSIS_OPENAI_API_KEY is set; model assist will report "Server model key required".\n'
```

- [ ] **Step 6: Run doc and launcher tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_public_deployment_artifacts.py tests/test_local_mvp_launcher.py
```

Expected: pass.

## Task 7: Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run secret hygiene**

Run:

```bash
.venv/bin/python scripts/check_openai_secrets.py --all
```

Expected: no output and exit code `0`.

- [ ] **Step 2: Run backend/API artifact tests**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_openai_secret_hygiene.py tests/test_public_deployment_artifacts.py tests/test_local_mvp_launcher.py tests/test_engine_api_server.py tests/test_operator_packet.py
```

Expected: pass.

- [ ] **Step 3: Run frontend lint/build**

Run:

```bash
cd nepsis-web
npm run lint
npm run build
```

Expected: both pass.

- [ ] **Step 4: Start local private operator demo**

Run:

```bash
scripts/operator-local.sh
```

Expected:

- `http://127.0.0.1:8787/v1/health` returns `{"ok":true}`.
- `http://127.0.0.1:3000/status` shows backend ready and model key missing unless a server-side key is supplied.
- `/settings` has no key input and offers only legacy cleanup/status.
- `/playground` does not mention browser-local keys and points to server configuration/status when no key exists.
- `/operator` still renders live operator workspace after local preview-code login.

- [ ] **Step 5: Verify no browser key strings remain in active runtime paths**

Run:

```bash
rg -n "getStoredOpenAiKey|hasStoredOpenAiKey|browserModelKeysAllowed|NEPSIS_BROWSER_MODEL_KEYS_ALLOWED|localStorage\\.setItem\\(OPENAI_KEY_STORAGE_KEY|apiKey:" nepsis-web/src scripts tests README.md docs
```

Expected: no active runtime references. Test strings may remain only where they assert absence or scanner rejection.

- [ ] **Step 6: Final git checks**

Run:

```bash
git diff --check
git status --short
```

Expected: no whitespace errors; changed files are limited to the planned files plus any already-unrelated parked docs.

## Self-Review

- Spec coverage: removes browser storage, route-level browser key acceptance, UI key entry, docs ambiguity, and secret-hygiene gaps.
- Public `/mvp` boundary: unchanged and still deterministic/model-free.
- Private operator path: still supports model assist through server-side key only.
- User ease: users sign in and use the operator workflow; no API-key paste flow. True user-owned provider usage is routed to MCP-capable hosts.
- Residual future work: if business requirements later demand per-user Nepsis-hosted provider accounts, design a separate OAuth/provider-token vault with encryption, per-user ownership, rotation, audit, and revocation. Do not implement that as raw localStorage or raw database API keys.
