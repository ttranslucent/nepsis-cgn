# Operator Runbook

## Deterministic MVP Demo

Use `/mvp` for the v0.3 demo. It calls the canonical packet builder and does
not require an LLM.

1. Start the backend with local anonymous API access:

```bash
NEPSIS_API_ALLOW_ANON=true .venv/bin/python -m nepsis_cgn.api.server --host 127.0.0.1 --port 8787
```

2. Start the web UI:

```bash
cd nepsis-web
npm run dev
```

3. Open `http://localhost:3000/mvp`.
4. Run `Jailing`, then `Clinical`.
5. Show RED before BLUE, STILL checkpoints, denominator collapse, ZeroBack,
   state feedback, and the audit trace.

## Boundaries

- `/mvp` is the frozen deterministic demo path.
- `/engine`, session APIs, playground routes, and LLM/model sandbox flows are
  experimental.
- Clinical demo packets are not medical advice, not diagnosis, and not clinical
  decision support.
- Browser-stored OpenAI keys are local-demo only. Do not use them as a shared
  deployment secret flow.

## Shared Deployment Checklist

- Backend has `NEPSIS_API_TOKEN` set.
- Backend does not set `NEPSIS_API_ALLOW_ANON=true`.
- Web has `NEPSIS_API_BASE_URL` and `NEPSIS_API_TOKEN` set.
- Web has a long random `NEPSIS_AUTH_SECRET`.
- Web does not set `NEPSIS_ENGINE_ALLOW_ANON=true` in production.
- Web does not set `NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true` in production.
- Login email delivery is configured with `RESEND_API_KEY` and
  `NEPSIS_AUTH_FROM_EMAIL`.
- Operators rehearse the `/mvp` script before broad testing.
