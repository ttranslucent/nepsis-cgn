# Operator Runbook

## Deterministic MVP Demo

Use `/mvp` for the v0.3 demo. It calls the canonical packet builder and does
not require an LLM.

1. From the repo root, start the local MVP launcher:

```bash
scripts/mvp-local.sh
```

2. Open `http://127.0.0.1:3000/mvp`.
3. Run `Jailing`, then `Clinical`.
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

- `/mvp` is the frozen deterministic demo path.
- `/mvp` is a case-run demo. The public page does not expose a visitor query
  box and should not be described as a chatbot or prompt surface.
- `/status` is the first stop for deployment health, auth, model-route, and MCP
  readiness.
- `POST /api/engine/mvp` should prefer the FastAPI backend. If the public web
  deployment has no backend URL, it serves bundled frozen v0.3 packets as a
  public-demo safety net and `/status` still reports the backend gap. Fallback
  packets include `fallback_source` and `fallback_reason`; `backend_unconfigured`
  means the public demo is intentionally using the bundled deterministic packet.
- The v0.1.7 raw packet keeps hypothesis `likelihood` support-only and puts
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
- Clinical demo packets are not medical advice, not diagnosis, and not clinical
  decision support.
- Browser-stored OpenAI keys are no longer supported. `/settings` only reports
  provider-access posture and clears legacy browser key storage.
- The local launcher is model-free. MCP harness work should use supported host
  or CLI authentication flows for OpenAI/Codex, Claude, or Gemini instead of
  collecting provider keys in NepsisCGN.

## Shared Deployment Checklist

- Render backend uses the existing `render.yaml` service:
  `python -m pip install -e '.[api]'` and `nepsiscgn-api-asgi`.
- Backend has `NEPSIS_API_HOST=0.0.0.0`, `NEPSIS_API_PORT=$PORT`,
  `NEPSIS_API_TOKEN`, `NEPSIS_API_ALLOWED_ORIGINS`, and, if sessions stay
  enabled, persistent `NEPSIS_API_STORE_PATH`.
- Backend explicitly sets `NEPSIS_API_ALLOW_ANON=false`.
- Web has `NEPSIS_API_BASE_URL=https://<render-service>` and matching
  `NEPSIS_API_TOKEN`.
- Web has a long random `NEPSIS_AUTH_SECRET`.
- Web sets `NEPSIS_AUTH_ALLOWED_EMAILS` to the exact operator email addresses
  permitted to request OTP login.
- For invited-user access, the current repo uses exact-email allowlisting. When
  Supabase is added, use Supabase invite approval as the login source, not as a
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
- Login email delivery is configured with `RESEND_API_KEY` and
  `NEPSIS_AUTH_FROM_EMAIL`; preview-code login stays disabled on shared
  operator deployments.
- `.venv/bin/python scripts/check_openai_secrets.py --all` passes before
  deployment env templates or config changes are committed.
- Operators rehearse the `/mvp` script before broad testing.

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
NEPSIS_API_BASE_URL=https://<private-render-service>
NEPSIS_API_TOKEN=<private-backend-token>
NEPSIS_OPERATOR_PACKET_SEAL_SECRET=<long-random-operator-packet-seal-secret>
NEPSIS_AUTH_SECRET=<long-random-secret>
NEPSIS_AUTH_ALLOWED_EMAILS=<operator-email-list>
NEPSIS_AUTH_SESSION_REVOKE_BEFORE=
RESEND_API_KEY=<resend-api-key>
NEPSIS_AUTH_FROM_EMAIL=Nepsis Operator <login@operator.example>
NEPSIS_AUTH_ALLOW_CODE_PREVIEW=false
NEPSIS_ENGINE_ALLOW_ANON=false
NEPSIS_MODEL_ROUTES_ENABLED=true
OPENAI_API_KEY=<server-side-openai-key>
```

For the frozen public `/mvp` deployment, use
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

After Vercel and Render are connected:

```bash
NEPSIS_SITE_BASE_URL=https://nepsis-cgn.vercel.app scripts/site-smoke.sh
```

The smoke checks the landing page, `/mvp`, `/api/status`, backend health through
the web proxy, the deterministic MVP POST, unauthenticated auth session shape,
disabled model routes, and the playground config endpoint. A failing
`/api/engine/mvp` usually means `NEPSIS_API_BASE_URL`, `NEPSIS_API_TOKEN`,
Render service health, or CORS origins are misconfigured.

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
`NEPSIS_OPERATOR_PACKET_SEAL_SECRET` so inbound packets can be rejected if they
were tampered with before replay. MCP clients should use their own
ChatGPT/Codex, Claude Code, or Gemini authentication; NepsisCGN should not
collect or subsidize visitor model accounts.
