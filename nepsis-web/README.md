Nepsis Web
==========

`nepsis-web` is the Next.js operator UI for NepsisCGN. It serves the public landing pages, passwordless login flow, `/engine` workspace, and server-side proxy routes under `/api/engine/*`.

## Local Development

1. Start the Nepsis backend API from the repo root:

```bash
nepsiscgn-api --host 127.0.0.1 --port 8787
```

2. In this directory, copy the example env file and adjust any local overrides:

```bash
cp .env.example .env.local
```

3. Install dependencies and run the web app:

```bash
npm install
npm run dev
```

4. Open [http://localhost:3000](http://localhost:3000).

Development defaults:

- `/api/engine/*` proxies to `http://127.0.0.1:8787` when `NEPSIS_API_BASE_URL` is unset.
- Login codes can fall back to on-screen preview in non-production environments.

## Engine Proxy Routes

The web app exposes these backend proxy routes:

- `GET /api/engine/health`
- `GET /api/engine/routes`
- `GET /api/engine/openapi`
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
- `NEPSIS_ENGINE_ALLOW_ANON`: Optional local/demo override to bypass browser login for engine session controls.

Passwordless auth:

- `NEPSIS_AUTH_SECRET`: Required in production. Cookie-signing secret for login challenge and user session cookies.
- `RESEND_API_KEY`: Required if the deployment should send real login emails.
- `NEPSIS_AUTH_FROM_EMAIL`: Required with `RESEND_API_KEY`. Verified sender identity for login emails.
- `NEPSIS_AUTH_ALLOW_CODE_PREVIEW`: Optional preview-only escape hatch that lets the UI display the one-time code directly when email delivery is unavailable.

OpenAI-backed playground routes:

- `OPENAI_API_KEY` or `NEPSIS_OPENAI_API_KEY`: Optional server-side key for playground/model-sandbox calls.
- `OPENAI_MODEL`: Optional default model. Defaults to `gpt-4.1-mini`.
- `OPENAI_API_URL`: Optional override for the Responses API endpoint.

Local proto-puzzle overrides:

- `NEPSIS_PYTHON`
- `NEPSIS_PROJECT_ROOT`
- `NEPSIS_PROTO_PUZZLE_CLI`

## Vercel Deployment

Production behavior is intentionally strict:

- If `NEPSIS_API_BASE_URL` is missing, `/api/engine/*` returns `503` and `/engine` shows `Engine backend not configured`.
- If `NEPSIS_AUTH_SECRET` is missing, login routes fail closed in production.
- If email delivery is not configured, `/login` tells the operator which auth env vars are missing instead of claiming an email was sent.

Recommended deployment sequence:

1. Deploy the `nepsis-web` project to Vercel.
2. Set `NEPSIS_API_BASE_URL` to the public Nepsis API origin.
3. Set `NEPSIS_AUTH_SECRET` to a long random secret.
4. Set `RESEND_API_KEY` and `NEPSIS_AUTH_FROM_EMAIL` if operators should receive emailed login codes.
5. Optionally set `NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true` only for preview/testing deployments.
6. Verify `/login` and `/engine` after the deployment is live.
