# Supported Runtime Matrix

NepsisCGN v0.3 is supported as a deterministic MVP demo with a local Python
backend and a local Next.js UI.

| Component | Supported Runtime | Install Command | Required For |
| --- | --- | --- | --- |
| Python package | CPython 3.11 | `.venv/bin/python -m pip install -e '.[dev,api]'` | CLI, API, tests |
| Backend API | CPython 3.11 plus `api` extra | `.venv/bin/python -m nepsis_cgn.api.server` | `/v1/mvp`, experimental sessions |
| Next UI | Node.js 20 LTS, npm with lockfile | `cd nepsis-web && npm ci` | `/mvp`, `/engine`, auth routes |
| Browser | Current Chromium/Safari/Firefox | N/A | Local UI demo |
| Public backend | Render Python web service | `render.yaml` | Token-protected FastAPI and `/mcp` |
| Public web | Vercel Next.js app | `nepsis-web` | `/mvp`, `/status`, gated operator pages |

## Smoke Path

From the repository root:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,api]'
.venv/bin/python -m pytest -q
cd nepsis-web
npm ci
npm run lint
npm run build
```

The same sequence is available as:

```bash
scripts/smoke.sh
```

The script defaults to `python3.11`. If that executable is unavailable, it uses
`python3` only when the interpreter is still Python 3.11 or newer. Set
`PYTHON_BIN=/path/to/python3.11 scripts/smoke.sh` to force a specific runtime.

## Deployment Notes

- Use `.venv/bin/python`; do not rely on system `python3`.
- Keep `/mvp` as the frozen deterministic demo path.
- Public production should set `NEPSIS_API_BASE_URL`, matching
  `NEPSIS_API_TOKEN`, `NEPSIS_AUTH_SECRET`, `NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true`,
  and `NEPSIS_MODEL_ROUTES_ENABLED=false`.
- Public production should not set server OpenAI keys unless model routes have
  auth and rate-limit review.
- Treat engine sessions, LLM calls, and browser-stored OpenAI keys as
  experimental unless separately reviewed for the target deployment.
