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
- Login codes can fall back to on-screen preview in non-production environments.
- `/api/engine/mvp` is the deterministic v0.3 demo path; session, engine, and LLM flows are experimental.
- `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true` forces public-mode navigation locally for QA.

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

## Environment Variables

Engine connectivity:

- `NEPSIS_API_BASE_URL`: Required in production. Public base URL of the Nepsis API that Vercel should reach.
- `NEPSIS_API_TOKEN`: Optional bearer token forwarded to the Nepsis API.
- `NEPSIS_ENGINE_ALLOW_ANON`: Optional local/demo override to bypass browser login for engine session controls. Ignored in production.
- `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE`: Optional local QA flag. Production builds also render as public-site mode by default.

Passwordless auth:

- `NEPSIS_AUTH_SECRET`: Required in production. Cookie-signing secret for login challenge and user session cookies.
- `RESEND_API_KEY`: Required if the deployment should send real login emails.
- `NEPSIS_AUTH_FROM_EMAIL`: Required with `RESEND_API_KEY`. Verified sender identity for login emails.
- `NEPSIS_AUTH_ALLOW_CODE_PREVIEW`: Optional local/preview-only escape hatch that lets the UI display the one-time code directly when email delivery is unavailable. Keep this disabled in production.

For local login without email, leave `RESEND_API_KEY` and `NEPSIS_AUTH_FROM_EMAIL` blank and set `NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true`. The `/login` page will show the one-time code after `Send code`.

OpenAI-backed playground routes:

- `NEPSIS_MODEL_ROUTES_ENABLED`: Enables server-side model routes. Keep `false` for the public production site unless auth and rate limits have been reviewed.
- `OPENAI_API_KEY` or `NEPSIS_OPENAI_API_KEY`: Optional server-side key for playground/model-sandbox calls.
- `OPENAI_MODEL`: Optional default model. Defaults to `gpt-4.1-mini`.
- `OPENAI_API_URL`: Optional override for the Responses API endpoint.

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

- If `NEPSIS_API_BASE_URL` is missing, `/api/engine/*` returns `503` and `/mvp` links users to `/status`.
- `/api/status` checks the frozen MVP packet path in addition to backend health.
- If `NEPSIS_AUTH_SECRET` is missing, login routes fail closed in production.
- If email delivery is not configured, `/login` either shows a preview code when preview is enabled or tells the operator which auth env vars are missing.
- Engine session controls require signed browser identity unless `NEPSIS_ENGINE_ALLOW_ANON=true` is set outside production.
- `/settings` and `/playground` do not display browser API-key fields in public-site mode.
- `GET /api/playground-nepsis` reports model routes as disabled unless `NEPSIS_MODEL_ROUTES_ENABLED=true`.

Recommended deployment sequence:

1. Deploy the FastAPI backend from the repo-root `render.yaml`.
2. Set Vercel `NEPSIS_API_BASE_URL` to the Render service origin.
3. Set matching `NEPSIS_API_TOKEN` on Render and Vercel.
4. Set `NEPSIS_AUTH_SECRET` to a long random secret.
5. Set `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true` and `NEPSIS_MODEL_ROUTES_ENABLED=false` for public production.
6. Do not set `OPENAI_API_KEY`, `NEPSIS_OPENAI_API_KEY`, `NEPSIS_ENGINE_ALLOW_ANON`, or `NEPSIS_AUTH_ALLOW_CODE_PREVIEW` for public production.
7. Set `RESEND_API_KEY` and `NEPSIS_AUTH_FROM_EMAIL` if operators should receive emailed login codes.
8. Verify `/mvp`, `/status`, `/login`, and gated `/engine` after the deployment is live.
9. Run `NEPSIS_SITE_BASE_URL=https://nepsis-cgn.vercel.app scripts/site-smoke.sh` from the repo root.

## Public API and MCP

The public web API surface is `POST /api/engine/mvp`, which forwards to the
token-protected FastAPI `POST /v1/mvp` route. Direct FastAPI access should stay
behind `NEPSIS_API_TOKEN` unless a separate public API program is opened.

The FastAPI backend exposes `/mcp` as an HTTP MCP JSON-RPC endpoint with
`run_mvp`, `get_mvp_schema`, `health`, and protected `get_routes` tools. MCP is
for connecting NepsisCGN to clients where users already have their own
ChatGPT/Codex, Claude Code, or Gemini account; it should not proxy model account
access through this public website.
