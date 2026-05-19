# Security Policy

## Supported Versions

Security hardening is focused on the v0.3 deterministic MVP demo and its local
API/UI smoke path. Older prototype flows are not supported for shared
deployment.

| Surface | Status | Notes |
| --- | --- | --- |
| `/v1/mvp`, `/api/engine/mvp`, `/mvp` | Supported v0.3 demo | Deterministic packet path only. |
| Engine session APIs | Experimental | Requires API token on the backend and signed web identity for shared use. |
| LLM/playground flows | Experimental | Keep out of production demos unless separately reviewed. |
| Browser-stored OpenAI keys | Local demo only | Do not use this as a shared deployment secret flow. |

## Reporting a Vulnerability

Report suspected vulnerabilities privately to the repository owner. Include:

- affected component and route or file path,
- reproduction steps or proof of concept,
- expected security invariant,
- impact and required preconditions.

Do not include real patient data, production credentials, API keys, or private
operator emails in reports.

## Deployment Security Baseline

- Set `NEPSIS_API_TOKEN` for backend API deployments.
- Leave `NEPSIS_API_ALLOW_ANON` disabled except for local demos.
- Set a long random `NEPSIS_AUTH_SECRET` for the Next app.
- Keep `NEPSIS_ENGINE_ALLOW_ANON` disabled outside local demos.
- Use emailed login codes through a configured sender for shared deployments.
- Leave `NEPSIS_AUTH_ALLOW_CODE_PREVIEW` disabled outside preview-only testing.
- Treat browser-local OpenAI key storage as local-demo only.

## Clinical Boundary

NepsisCGN v0.3 is not medical advice, not a medical diagnostic tool, and not a
clinical decision support system. Clinical examples are deterministic governance
packet demonstrations only.
