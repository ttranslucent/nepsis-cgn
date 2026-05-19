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
- `/status` is the first stop for deployment health, auth, model-route, and MCP
  readiness.
- `POST /api/engine/mvp` should prefer the FastAPI backend. If the public web
  deployment has no backend URL, it serves bundled frozen v0.3 packets as a
  public-demo safety net and `/status` still reports the backend gap.
- `/engine`, session APIs, playground routes, and LLM/model sandbox flows are
  experimental operator tools.
- Clinical demo packets are not medical advice, not diagnosis, and not clinical
  decision support.
- Browser-stored OpenAI keys are local-demo only. Do not use them as a shared
  deployment secret flow.
- The local launcher is model-free. Future account-based OpenAI/Codex, Claude,
  or Gemini harness work should use supported host or CLI authentication flows
  and receive separate v0.4 design review.

## Shared Deployment Checklist

- Render backend uses the existing `render.yaml` service:
  `python -m pip install -e '.[api]'` and `nepsiscgn-api-asgi`.
- Backend has `NEPSIS_API_HOST=0.0.0.0`, `NEPSIS_API_PORT=$PORT`,
  `NEPSIS_API_TOKEN`, `NEPSIS_API_ALLOWED_ORIGINS`, and, if sessions stay
  enabled, persistent `NEPSIS_API_STORE_PATH`.
- Backend does not set `NEPSIS_API_ALLOW_ANON=true`.
- Web has `NEPSIS_API_BASE_URL=https://<render-service>` and matching
  `NEPSIS_API_TOKEN`.
- Web has a long random `NEPSIS_AUTH_SECRET`.
- Web sets `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true` and
  `NEPSIS_MODEL_ROUTES_ENABLED=false` for the public production site.
- Web does not set `OPENAI_API_KEY` or `NEPSIS_OPENAI_API_KEY` for public
  production unless model routes have auth and rate-limit review.
- Web does not set `NEPSIS_ENGINE_ALLOW_ANON=true` in production.
- Web does not set `NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true` in production.
- Login email delivery is configured with `RESEND_API_KEY` and
  `NEPSIS_AUTH_FROM_EMAIL`.
- Operators rehearse the `/mvp` script before broad testing.

## Public Site Smoke

After Vercel and Render are connected:

```bash
NEPSIS_SITE_BASE_URL=https://nepsis-cgn.vercel.app scripts/site-smoke.sh
```

The smoke checks the landing page, `/mvp`, backend health through the web proxy,
the deterministic MVP POST, auth session shape, and the playground config
endpoint. A failing `/api/engine/mvp` usually means `NEPSIS_API_BASE_URL`,
`NEPSIS_API_TOKEN`, Render service health, or CORS origins are misconfigured.

## Key Safety

The public site must not invite visitors to paste provider keys. If a real key
was previously pasted into `/settings` during public testing, rotate that key
with the provider and clear browser storage for `https://nepsis-cgn.vercel.app`.

## MCP Surface

Backend `/mcp` exposes NepsisCGN as a tool endpoint with public deterministic
tools (`run_mvp`, `get_mvp_schema`, `health`) and protected operator metadata
(`get_routes`). MCP clients should use their own ChatGPT/Codex, Claude Code, or
Gemini authentication; NepsisCGN should not collect or subsidize visitor model
accounts.
