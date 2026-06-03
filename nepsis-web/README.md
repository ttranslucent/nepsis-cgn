Nepsis Web
==========

`nepsis-web` is the Next.js operator UI for NepsisCGN. It serves the public landing pages, passwordless login flow, `/engine` workspace, and server-side proxy routes under `/api/engine/*`.

## Local Development

For the full frozen MVP demo, use the repo-root launcher after one-time
dependency setup:

```bash
scripts/mvp-local.sh
```

Open [http://127.0.0.1:3000/mvp](http://127.0.0.1:3000/mvp), choose `Jailing`
or `Clinical`, and click `Run Demo`. Use `Ctrl-C` in the launcher terminal to
stop both the backend and web UI.

For web-only development, start the Nepsis backend API from the repo root:

```bash
NEPSIS_API_ALLOW_ANON=true .venv/bin/python -m nepsis_cgn.api.server --host 127.0.0.1 --port 8787
```

Then in this directory, copy the example env file and adjust any local
overrides:

```bash
cp .env.example .env.local
```

Install dependencies and run the web app:

```bash
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

Development defaults:

- `/api/engine/*` proxies to `http://127.0.0.1:8787` when `NEPSIS_API_BASE_URL` is unset.
- Login codes can fall back to on-screen preview when local preview-code mode is enabled.
- `/api/engine/mvp` is the deterministic v0.3 demo path; session, engine, and LLM flows are experimental.
- `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true` forces public-mode navigation locally for QA.
- Deployment env should start from `nepsis-web/.env.public.example` or
  `nepsis-web/.env.operator.example`; `.env.example` is for local development.

## Engine Proxy Routes

The web app exposes these backend proxy routes:

- `GET /api/engine/health`
- `GET /api/engine/routes`
- `GET /api/engine/openapi`
- `POST /api/engine/mvp`
- `POST /api/engine/sessions`
- `GET /api/engine/sessions`
- `GET /api/engine/sessions/:sessionId`
- `DELETE /api/engine/sessions/:sessionId`
- `POST /api/engine/sessions/:sessionId/step`
- `POST /api/engine/sessions/:sessionId/reframe`
- `GET /api/engine/sessions/:sessionId/stage-audit`
- `POST /api/engine/sessions/:sessionId/stage-audit`
- `GET /api/engine/sessions/:sessionId/packets`

Key frontend integration points:

- Typed client: `src/lib/engineClient.ts`
- Session/state hook: `src/lib/useEngineSession.ts`
- Operator workspace: `src/app/engine/page.tsx`
- Live operator route alias: `src/app/operator/page.tsx`

## Environment Variables

Engine connectivity:

- `NEPSIS_API_BASE_URL`: Required in production. Public base URL of the Nepsis API that Vercel should reach.
- `NEPSIS_API_TOKEN`: Optional bearer token forwarded to the Nepsis API.
- `NEPSIS_ENGINE_ALLOW_ANON`: Optional local/demo override to bypass browser login for engine session controls. Ignored in public-site mode.
- `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE`: Optional local QA flag. Production builds also render as public-site mode by default.

Passwordless auth:

- `NEPSIS_AUTH_SECRET`: Required in production. Cookie-signing secret for login challenge and user session cookies.
- `NEPSIS_AUTH_ALLOWED_EMAILS`: Required for operator login. Exact email addresses allowed to request OTP login, separated by commas or spaces.
- `NEPSIS_AUTH_SESSION_REVOKE_BEFORE`: Optional ISO timestamp that invalidates older signed browser sessions globally.
- `RESEND_API_KEY`: Required if the deployment should send real login emails.
- `NEPSIS_AUTH_FROM_EMAIL`: Required with `RESEND_API_KEY`. Verified sender identity for login emails.
- `NEPSIS_AUTH_ALLOW_CODE_PREVIEW`: Optional local-only escape hatch that lets the UI display the one-time code directly when email delivery is unavailable. Ignored in public-site and operator modes.

For local login without email, set `NEPSIS_AUTH_ALLOWED_EMAILS` to the local test address, leave `RESEND_API_KEY` and `NEPSIS_AUTH_FROM_EMAIL` blank, and set `NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true`. The `/login` page will show the one-time code after `Send code`.

OpenAI-backed playground routes:

- `NEPSIS_MODEL_ROUTES_ENABLED`: Enables server-side model routes only outside public-site mode. Public-site mode keeps these routes disabled even if this is set to `true`.
- `OPENAI_API_KEY` or `NEPSIS_OPENAI_API_KEY`: Optional server-side key for playground/model-sandbox calls.
- `OPENAI_MODEL`: Optional default model. Defaults to `gpt-4.1-mini`.
- `OPENAI_API_URL`: Optional override for the Responses API endpoint.

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

Browser-local OpenAI key storage in `/settings` is local-demo only and is hidden
in public-site mode. Do not use it as a shared deployment secret flow; prefer
reviewed server-side environment variables for private operator deployments.

Open model harness direction:

- The repo-root MVP launcher remains model-free and preserves the deterministic
  `/mvp` path.
- Future account-based model support should be designed separately around
  supported host or CLI authentication flows for OpenAI/Codex, Claude, and
  Gemini rather than making this UI collect provider API keys.

Local proto-puzzle overrides:

- `NEPSIS_PYTHON`
- `NEPSIS_PROJECT_ROOT`
- `NEPSIS_PROTO_PUZZLE_CLI`

## Vercel Deployment

Production behavior is intentionally strict:

- If `NEPSIS_API_BASE_URL` is missing, most `/api/engine/*` routes return `503`
  and affected pages link users to `/status`.
- Exception: `POST /api/engine/mvp` serves bundled frozen v0.3 packets when the
  backend URL is missing, so the public demo remains runnable while `/status`
  reports the backend gap.
- `/api/status` checks the frozen MVP packet path in addition to backend health.
- If `NEPSIS_AUTH_SECRET` is missing, login routes fail closed in production.
- Operator login requires `NEPSIS_AUTH_ALLOWED_EMAILS`; unlisted addresses receive a generic response and no OTP.
- If email delivery is not configured, `/login` shows a preview code only in non-public, non-operator local mode; otherwise it tells the operator which auth env vars are missing.
- Signed browser sessions persist for 30 days by default. Set `NEPSIS_AUTH_SESSION_REVOKE_BEFORE` to an ISO timestamp to invalidate older sessions globally.
- Engine session controls require signed browser identity unless `NEPSIS_ENGINE_ALLOW_ANON=true` is set outside public-site mode.
- `/settings` and `/playground` do not display browser API-key fields in public-site mode.
- `GET /api/playground-nepsis` reports model routes as disabled in public-site mode.

### Public site setup

Use `nepsis-web/.env.public.example` for the frozen public `/mvp` site. It keeps
`NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true`, operator mode disabled,
`NEPSIS_MODEL_ROUTES_ENABLED=false`, local preview codes disabled, anonymous
engine controls disabled, and provider keys unset. Public `/mvp` does not
require login or model credentials.

Recommended public deployment sequence:

1. Deploy the FastAPI backend from the repo-root `render.yaml`.
2. Set Vercel `NEPSIS_API_BASE_URL` to the Render service origin.
3. Set matching `NEPSIS_API_TOKEN` on Render and Vercel.
4. Set `NEPSIS_AUTH_SECRET` to a long random secret.
5. Set `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true` and `NEPSIS_MODEL_ROUTES_ENABLED=false` for public production.
6. Do not set `OPENAI_API_KEY`, `NEPSIS_OPENAI_API_KEY`, `NEPSIS_ENGINE_ALLOW_ANON`, or `NEPSIS_AUTH_ALLOW_CODE_PREVIEW` for public production.
7. Set `NEPSIS_AUTH_ALLOWED_EMAILS`, `RESEND_API_KEY`, and `NEPSIS_AUTH_FROM_EMAIL` if operators should receive emailed login codes.
8. Verify `/mvp`, `/status`, `/login`, and gated `/engine` after the deployment is live.
9. Run `NEPSIS_SITE_BASE_URL=https://nepsis-cgn.vercel.app scripts/site-smoke.sh` from the repo root.

### Private operator deployment

Use `nepsis-web/.env.operator.example` only for a separate private deployment.
That path sets `NEPSIS_DEPLOYMENT_MODE=operator`,
`NEXT_PUBLIC_NEPSIS_OPERATOR_SITE=true`, `NEPSIS_LIVE_OPERATOR_ENABLED=true`,
and `NEPSIS_MODEL_ROUTES_ENABLED=true`. It also requires backend auth,
`NEPSIS_AUTH_SECRET`, `NEPSIS_AUTH_ALLOWED_EMAILS`, real login email delivery
through `RESEND_API_KEY` and `NEPSIS_AUTH_FROM_EMAIL`, and a server-side
`OPENAI_API_KEY` or `NEPSIS_OPENAI_API_KEY`. Keep `NEPSIS_ENGINE_ALLOW_ANON=false` and
`NEPSIS_AUTH_ALLOW_CODE_PREVIEW=false` for shared operator deployments.

Run the repository safety check before committing env or deployment changes:

```bash
.venv/bin/python scripts/check_openai_secrets.py --all
```

The local pre-commit hook uses the same checker for staged files.

## Public API and MCP

The public web API surface is `POST /api/engine/mvp`, which forwards to the
token-protected FastAPI `POST /v1/mvp` route. Direct FastAPI access should stay
behind `NEPSIS_API_TOKEN` unless a separate public API program is opened.

The FastAPI backend exposes `/mcp` as an HTTP MCP JSON-RPC endpoint. Discovery
methods (`initialize`, `tools/list`) stay unauthenticated, while every hosted
`tools/call` requires a Nepsis capability token configured as
`NEPSIS_MCP_CAPABILITY_TOKEN_HASHES=operator-1:<sha256-of-token>`. MCP is for
connecting NepsisCGN to clients where users already have their own
ChatGPT/Codex, Claude Code, or Gemini account; it should not proxy model account
access through this public website.
