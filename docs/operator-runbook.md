# Operator Runbook

## Deterministic MVP Demo

Use `/mvp` for the public v0.4 deterministic demo. It calls the canonical packet
builder and does not require an LLM.

1. From the repo root, start the local MVP launcher:

```bash
scripts/mvp-local.sh
```

2. Open `http://127.0.0.1:3000/mvp`.
3. Run `JINGALL/JAILING`, `Revised SEA`, and `Wirecard`.
4. Show RED before BLUE, STILL checkpoints, denominator collapse, ZeroBack,
   state feedback, and the audit trace.
5. Use `Ctrl-C` in the launcher terminal to stop both the backend and web UI.

The launcher starts the backend at `127.0.0.1:8787` with
`NEPSIS_API_ALLOW_ANON=true` and starts `nepsis-web` on `127.0.0.1:3000`.
If either child process exits, the launcher shuts down the other process.

Manual fallback:

```bash
NEPSIS_API_ALLOW_ANON=true .venv/bin/python -m nepsis_cgn.api.server --host 127.0.0.1 --port 8787
cd nepsis-web
npm run dev
```

## Boundaries

- `/mvp` is the public deterministic v0.4 demo path.
- `/mvp` is a case-run demo. The public page does not expose a visitor query
  box and should not be described as a chatbot or prompt surface.
- `/status` is the first stop for deployment health, auth, model-route, and MCP
  readiness.
- `POST /api/engine/mvp` should prefer the FastAPI backend. If the public web
  deployment has no backend URL, it serves bundled public v0.4 packets as a
  public-demo safety net and `/status` still reports the backend gap. Fallback
  packets include `fallback_source` and `fallback_reason`; `backend_unconfigured`
  means the public demo is intentionally using the bundled deterministic packet.
- The v0.2.0 raw packet keeps hypothesis `likelihood` support-only and puts
  RED/threshold standing in `post_constraint_standing` and `action_priority`.
  STILL commitment readiness preserves the compatibility `status` field and
  makes ZeroBack/effective action explicit. Use contradiction `level`/`status`
  plus `density_channels` instead of treating the scalar density as a runtime
  gate.
- The Jailing/Jingall packet assumes `JINGALL` is the authoritative source
  token. It does not prove detection of the harder corrupted-source-token
  variant where `JAILING` is true; source-token verification remains a declared
  next-cycle obligation.
- `/engine`, session APIs, playground routes, and LLM/model sandbox flows are
  experimental operator tools.
- `/operator` is the product-facing live operator path. It must stay signed-in
  and backed by configured backend auth. Hosted model routes require separate
  caps and server-side credentials; MCP users should normally bring their own
  authenticated model client.
- `POST /v1/private-demo` is the authenticated NepsisAI private demo backend
  target. It requires `no_phi_acknowledged: true` and returns a
  `nepsis.private_demo_runtime_packet` with a nested operator packet audit. It
  must not be confused with public `POST /v1/mvp`.
- The revised SEA public packet is not medical advice, not diagnosis, and not
  clinical decision support. The Wirecard public packet is not financial,
  accounting, or legal advice.
- Browser-stored OpenAI keys are no longer supported. `/settings` only reports
  provider-access posture and clears legacy browser key storage.
- The local launcher is model-free. MCP harness work should use supported host
  or CLI authentication flows for OpenAI/Codex, Claude, or Gemini instead of
  collecting provider keys in NepsisCGN.

## Shared Deployment Checklist

- Current hosted backend is the Vercel API project `nepsis-cgn-api` at
  `https://nepsis-cgn-api.vercel.app`. It deploys the repo root through
  `api/index.py` and the `vercel.json` rewrite to the FastAPI ASGI app.
- Backend has `NEPSIS_API_TOKEN`, `NEPSIS_API_ALLOWED_ORIGINS`, and, if
  sessions stay enabled, a deliberate persistent `NEPSIS_API_STORE_PATH`.
- Backend sets `NEPSIS_V3_PACKET_SEAL_SECRET` for V3 MCP packets and
  `NEPSIS_OPERATOR_PACKET_SEAL_SECRET` so `/v1/private-demo` can return a
  sealed nested operator packet audit.
- Backend explicitly sets `NEPSIS_API_ALLOW_ANON=false`.
- Web has `NEPSIS_API_BASE_URL=https://nepsis-cgn-api.vercel.app` and matching
  `NEPSIS_API_TOKEN`.
- The NepsisAI front door must set `NEPSIS_PRIVATE_DEMO_URL` to the external
  backend `https://nepsis-cgn-api.vercel.app/v1/private-demo`, not `/v1/mvp`,
  and must pass its private backend smoke check before outside testers use the
  page.
- Web has a long random `NEPSIS_AUTH_SECRET`.
- Web sets `NEPSIS_AUTH_ALLOWED_EMAILS` to the exact operator email addresses
  permitted to request OTP login.
- For invited-user access, the current repo uses exact-email allowlisting.
  Supabase OTP may provide email-code delivery, but CGN still issues its own
  signed operator session cookie after verification. Do not use Supabase as a
  vault for raw model-provider API keys.
- Web sets `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true` and
  `NEPSIS_MODEL_ROUTES_ENABLED=false` for the public production site.
- Web does not set `OPENAI_API_KEY`, `NEPSIS_OPENAI_API_KEY`,
  `NEPSIS_ENGINE_ALLOW_ANON=true`, `NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true`, or
  `NEPSIS_MODEL_ROUTES_ENABLED=true` for the public production site.
- A separate private operator deployment may set
  `NEPSIS_DEPLOYMENT_MODE=operator`, `NEPSIS_LIVE_OPERATOR_ENABLED=true`,
  `NEPSIS_MODEL_ROUTES_ENABLED=true`, and a server-side model key. Do not reuse
  that configuration for the public demo deployment.
- Login email delivery is configured with either
  `NEXT_PUBLIC_SUPABASE_URL` plus `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` or
  `RESEND_API_KEY` plus `NEPSIS_AUTH_FROM_EMAIL`; preview-code login stays
  disabled on shared operator deployments.
- `.venv/bin/python scripts/check_openai_secrets.py --all` passes before
  deployment env templates or config changes are committed.
- Operators rehearse the `/mvp` script before broad testing.

## Private Demo Runtime Smoke

Use this smoke when validating the backend before wiring the NepsisAI front door:
confirm the backend has `NEPSIS_API_TOKEN` and
`NEPSIS_OPERATOR_PACKET_SEAL_SECRET` set first.

```bash
curl -sS -X POST https://nepsis-cgn-api.vercel.app/v1/private-demo \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <backend-token>" \
  -d '{
    "case_id": "jailing",
    "prompt": "No PHI. Source token is JINGALL and the candidate answer collapses to JAILING; preserve the mismatch and show the packet audit.",
    "no_phi_acknowledged": true,
    "thread_id": "private-demo-smoke",
    "user_id": "private-demo-smoke"
  }'
```

Expected response evidence:

- `schema_id` is `nepsis.private_demo_runtime_packet`.
- `mode` is `external-private-runtime`.
- `case_reasoning_compiler.schema_id` is `nepsis.case_reasoning_compiler`.
- `case_reasoning_compiler.compiler_valid` is `true`.
- `case_reasoning_compiler.domain_red_hazard.hazard` names the domain hazard,
  not the runtime safety boundary.
- `operator_packet.schema_id` is `nepsis.operator_packet`.
- `audit_trace` includes `LOCK_FRAME`, `RUN_REPORT`, `LOCK_REPORT`, and
  `SET_THRESHOLD_DECISION`.

The private demo runtime is still no-PHI and operator-reviewed. A threshold hold
is expected; do not present the packet as autonomous clinical guidance.

## Private Demo Web Smoke

The authenticated web path is `/private-demo`. It submits no-PHI prompts through
the web proxy at `/api/engine/private-demo`, which forwards to backend
`POST /v1/private-demo`. This path is distinct from public `/mvp` and must not
serve bundled MVP fallback packets.

Before testing the page, confirm:

- Backend has `NEPSIS_API_TOKEN`.
- Backend has `NEPSIS_OPERATOR_PACKET_SEAL_SECRET`.
- Backend has `NEPSIS_API_ALLOW_ANON=false`.
- Web has `NEPSIS_API_BASE_URL` pointed at the backend origin.
- Web has matching `NEPSIS_API_TOKEN`.
- Web has operator login configured.

Local verification:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_private_demo_benchmark.py
npm --prefix nepsis-web run lint
npm --prefix nepsis-web run test:e2e:auth -- e2e-auth/private-demo.spec.ts
```

Expected UI evidence:

- `/private-demo` requires operator access when signed out.
- The form requires a no-PHI acknowledgement before submission.
- The packet view shows `nepsis.private_demo_runtime_packet`.
- Topology shows `LOCK_FRAME`, `RUN_REPORT`, `LOCK_REPORT`, and
  `SET_THRESHOLD_DECISION`.
- Compiler view shows `nepsis.case_reasoning_compiler` and
  `compiler_valid: true`.
- Lineage view shows the nested `nepsis.operator_packet` packet ID and loop ID.
- Raw view exposes the full packet artifact for review.

## Private Demo Benchmark Suite

The repo includes a no-PHI/no-PII authority-suppression benchmark fixture at
`data/private_demo_cases/authority_suppressed_red_channel.json`. It covers the
medical and finance cases where RED must not close from authority, reassurance,
or plausibility alone.

Run the local audit-packet benchmark from the repo root:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_private_demo_benchmark.py
```

For a machine-readable report:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_private_demo_benchmark.py --json
```

The report is a `nepsis.private_demo_benchmark_report`. A case passes when the
private demo runtime returns a `nepsis.private_demo_runtime_packet`, the nested
operator packet reaches `threshold_set`, the audit trace includes
`LOCK_FRAME`, `RUN_REPORT`, `LOCK_REPORT`, and `SET_THRESHOLD_DECISION`, and
the validated Case Reasoning Compiler matches the fixture's expected RED
status and threshold action. Authority-suppressed cases should hold and
escalate RED; the true-closure case should de-escalate instead of proving an
always-red behavior.

## Private operator deployment

Use `nepsis-web/.env.operator.example` only for a separate private deployment.
It belongs to the signed-in `/operator` path with real email login and live
model routes. It is not a public `/mvp` template.

Required private operator web env:

```bash
NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=false
NEPSIS_DEPLOYMENT_MODE=operator
NEXT_PUBLIC_NEPSIS_OPERATOR_SITE=true
NEPSIS_LIVE_OPERATOR_ENABLED=true
NEPSIS_API_BASE_URL=https://nepsis-cgn-api.vercel.app
NEPSIS_API_TOKEN=<private-backend-token>
NEPSIS_V3_PACKET_SEAL_SECRET=<long-random-v3-packet-seal-secret>
NEPSIS_OPERATOR_PACKET_SEAL_SECRET=<long-random-operator-packet-seal-secret>
NEPSIS_AUTH_SECRET=<long-random-secret>
NEPSIS_AUTH_ALLOWED_EMAILS=<operator-email-list>
NEPSIS_AUTH_SESSION_REVOKE_BEFORE=
NEXT_PUBLIC_SUPABASE_URL=<supabase-project-url>
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<supabase-publishable-key>
RESEND_API_KEY=<resend-api-key>
NEPSIS_AUTH_FROM_EMAIL=Nepsis Operator <login@operator.example>
NEPSIS_AUTH_ALLOW_CODE_PREVIEW=false
NEPSIS_ENGINE_ALLOW_ANON=false
NEPSIS_MODEL_ROUTES_ENABLED=true
OPENAI_API_KEY=<server-side-openai-key>
```

For the public deterministic `/mvp` deployment, use
`nepsis-web/.env.public.example` instead and keep model routes and live operator
mode disabled. Do not use `NEPSIS_API_ALLOWED_ORIGINS=*` in public or operator
runtime environments.

## Guided Operator Completion

Guided completion is an authenticated `/operator` workflow. It is not part of
the public deterministic `/mvp` demo.

The operator moves through explicit boxes:

1. Frame question.
2. Key uncertainty.
3. Hard constraints.
4. Soft constraints.
5. RED channel definition.
6. BLUE channel goals.
7. Report observations, generated and reviewed through the engine report path.
8. Threshold decision and hold rationale.
9. Carry-forward next frame.

Each assist button asks the server-side model for one field only. The model can
suggest text; it cannot lock a frame, run a report, lock a report, set a
threshold, or commit an iteration. The operator must accept, edit, or reject a
suggestion before it can influence packet state.

The threshold decision itself has no assist target. The model may draft hold
rationale; the proceed/hold decision belongs to the operator. This is enforced
in the TypeScript target union, the model route allowlist, and the UI.

### Assist Provenance

Accepted and edited suggestions are sent as `assist_acceptances` on the next
packet transition. Each entry carries a SHA-256 hash of the model proposal and,
for accepted or edited dispositions, a SHA-256 hash of the final field value.
The backend recomputes the final hash from the field being locked and rejects
the transition on mismatch.

Each model suggestion also carries a server-signed proposal receipt. The receipt
binds the proposal hash to the protected model route, target field, model name,
and current stateless operator packet `loop_id`. Packet transitions reject
accepted, edited, or rejected model-suggestion records when the receipt is
missing, tampered, signed by the wrong key, or bound to a different loop.

- `accepted` means the final field is byte-identical to the model proposal.
- `edited` means the operator changed the proposal before the packet transition.
- `rejected` records that a suggestion was offered and declined; rejected
  entries carry the proposal hash only and are recorded on the next successful
  transition.

Rejected suggestions are recorded only if a later packet transition occurs. If
the operator rejects suggestions and abandons the packet before any transition,
those rejection records are not preserved in the packet trace.

Completion is defined by packet gates, not model confidence: frame gate before
frame lock, report lock before threshold review, threshold gate before commit,
and commit opens the carry-forward frame for the next loop.

## Public Site Smoke

After the Vercel API backend and Vercel web deployment are connected:

```bash
NEPSIS_API_BASE_URL=https://nepsis-cgn-api.vercel.app scripts/api-smoke.sh
NEPSIS_SITE_BASE_URL=https://nepsis-cgn.vercel.app scripts/site-smoke.sh
```

The smoke checks the landing page, `/mvp`, `/api/status`, backend health through
the web proxy, the deterministic MVP POST, unauthenticated auth session shape,
disabled model routes, and the playground config endpoint. A failing
`/api/engine/mvp` usually means `NEPSIS_API_BASE_URL`, `NEPSIS_API_TOKEN`,
Vercel API health, or CORS origins are misconfigured.

For hosted operator V3, the API smoke is also the backend catch-up gate. It must
see `POST /v1/operator-packet/v3/start`, `/field`, `/propose`, and `/lock` in
`/v1/routes`. With `NEPSIS_API_TOKEN` set, it also sends invalid-body probes to
those four routes and expects handler-level validation failures. If the route
manifest is missing any V3 path, or the probes do not reach the route handlers,
the web `/operator` surface must keep V3 layer-loop controls unavailable.

## Key Safety

The public site must not invite visitors to paste provider keys. If a real key
was previously pasted into `/settings` during public testing, rotate that key
with the provider and use `/settings` to clear legacy browser storage for
`https://nepsis-cgn.vercel.app`.

## MCP Surface

Backend `/mcp` exposes NepsisCGN as a tool endpoint with public deterministic
discovery (`initialize`, `tools/list`) and capability-token-protected tool
calls. The operator flow is stateless packet-in/packet-out: each tool receives a
`nepsis.operator_packet` v2 object and returns the next packet, with
RED-before-BLUE gates enforced by phase transitions. Operator runtimes require
`NEPSIS_OPERATOR_PACKET_SEAL_SECRET` so inbound operator packets can be
rejected if they were tampered with before replay. V3 orchestration tools also
require `NEPSIS_V3_PACKET_SEAL_SECRET` so packet artifacts stay verifiable
across MCP process boundaries. MCP clients should use their own ChatGPT/Codex,
Claude Code, or Gemini authentication; NepsisCGN should not collect or
subsidize visitor model accounts.
