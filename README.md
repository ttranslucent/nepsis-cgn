# NepsisCGN v0.3

Last verified: 2026-05-22

NepsisCGN is a governance-first reasoning engine that runs sidecar to LLMs. It enforces structured reasoning under uncertainty with distinct RED/BLUE decision spaces, STILL checkpoints, contradiction monitoring, denominator collapse detection, ZeroBack repair, consequence-weighted commitment, state feedback scaffolding, and audit packets.

## v0.3 MVP

Freeze baseline: `3d775d3` (`Polish MVP header flow`) on `main`.

The v0.3 MVP exposes a deterministic proof packet through CLI, API, and the local Next UI.

Flow:

RED → STILL → BLUE → STILL → commitment → state feedback → audit

The MVP demonstrates:

- RED Channel hazard and constraint preservation.
- BLUE Channel bounded analysis inside the RED safety boundary.
- STILL metacognitive checkpoints before BLUE and before commitment.
- Contradiction, denominator collapse, and non-quiescence detection.
- Retessellation and ZeroBack reset when the frame is unstable.
- Consequence-weighted Voronoi commitment.
- Predicted next-state / State Feedback scaffolding.
- Auditable reasoning trace.

`state_feedback` in v0.3 is deterministic MVP scaffolding only, not a live runtime feedback engine.

## What This Is Not

The v0.3 MVP is not a medical diagnostic tool, not a live clinical decision support system, and not a replacement for clinician judgment. The demo packets are deterministic proof artifacts showing the governance architecture, not autonomous model conclusions.

## Supported Runtime Matrix

| Component | Supported runtime | Notes |
| --- | --- | --- |
| Python package/API | CPython 3.11 | Use `.venv/bin/python`; install with `.[dev,api]`. |
| Next UI | Node.js 20 LTS with npm lockfile | Use `npm ci` from `nepsis-web`. |
| MVP demo | Python 3.11 backend plus local Next UI | Frozen deterministic v0.3 path. |
| Engine/session/LLM flows | Experimental | Keep behind auth and do not treat as the MVP proof path. |

See [docs/runtime-matrix.md](docs/runtime-matrix.md) for the smoke path and deployment notes.

## Quickstart

Clone and enter the repo:

```bash
git clone <repo>
cd nepsiscgn
```

One-time dependency setup:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,api]'
cd nepsis-web
npm ci
cd ..
```

Start the local deterministic MVP from the repo root:

```bash
scripts/mvp-local.sh
```

This starts the backend on `http://127.0.0.1:8787` and the Next UI at
`http://127.0.0.1:3000/mvp` with local demo settings. Use `Ctrl-C` in the
launcher terminal to stop both processes.

Full reproducibility smoke path from the repo root:

```bash
scripts/smoke.sh
```

## CLI Demo

Run the canonical MVP packet builder:

```bash
.venv/bin/python -m nepsis_cgn.cli.main --json mvp --case jailing
.venv/bin/python -m nepsis_cgn.cli.main --json mvp --case clinical
```

## API Demo

Start the backend:

```bash
NEPSIS_API_ALLOW_ANON=true .venv/bin/python -m nepsis_cgn.api.server --host 127.0.0.1 --port 8787
```

Call `POST /v1/mvp`:

```bash
curl -sS -X POST http://127.0.0.1:8787/v1/mvp \
  -H 'Content-Type: application/json' \
  -d '{"case_id":"jailing"}' | .venv/bin/python -m json.tool
```

The local Next API proxy used by the UI is `/api/engine/mvp`, which forwards to backend `POST /v1/mvp`.

## Public Website Deployment

The public site posture is intentionally narrow:

- `/mvp` is public, deterministic, and does not require login or model keys. Visitors can run the canonical cases or paste a short query into the selected MVP scaffold.
- `/operator` is a separate live operator surface. Enable it only on an authenticated operator deployment with backend API auth, exact-email OTP allowlisting, and login email delivery; keep hosted model routes disabled unless separately reviewed and capped.
- `/status` shows backend, auth, model-route, and MCP readiness.
- `/engine`, `/playground`, and `/settings` are operator surfaces. Public production hides or gates model flows, and the web app does not collect browser/user provider API keys.
- Public production must not set `OPENAI_API_KEY`, `NEPSIS_OPENAI_API_KEY`, `NEPSIS_ENGINE_ALLOW_ANON`, `NEPSIS_AUTH_ALLOW_CODE_PREVIEW`, or `NEPSIS_MODEL_ROUTES_ENABLED=true`.
- `POST /api/engine/mvp` uses the FastAPI backend when configured and falls back
  to bundled frozen v0.3 packets when production has no backend URL, so the
  public demo remains usable while backend deployment is completed. Fallback
  responses include `fallback_source` and `fallback_reason` so operators can
  distinguish an intentional bundled packet from a proxied backend packet.

Deploy the existing FastAPI backend as the API service. `render.yaml` defines a
Render web service that installs `.[api]`, starts `nepsiscgn-api-asgi`, binds to
`0.0.0.0:$PORT`, keeps anonymous backend access disabled, sets
`NEPSIS_API_TOKEN`, configures CORS origins, and stores engine sessions under
`/var/data` when sessions are enabled.

Configure the Vercel web app with:

```bash
NEPSIS_API_BASE_URL=https://<render-service>
NEPSIS_API_TOKEN=<same-token-as-render>
NEPSIS_AUTH_SECRET=<long-random-secret>
NEPSIS_AUTH_ALLOWED_EMAILS=<operator-email-list>
NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true
NEPSIS_MODEL_ROUTES_ENABLED=false
```

### Public site setup

Start public Vercel env from `nepsis-web/.env.public.example`. That template is
for the frozen `/mvp` deployment only: it sets
`NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true`, keeps operator mode off, keeps
`NEPSIS_MODEL_ROUTES_ENABLED=false`, and leaves `OPENAI_API_KEY` and
`NEPSIS_OPENAI_API_KEY` unset. The public site may point at the FastAPI backend,
but `/api/engine/mvp` can still serve bundled frozen packets while the backend
is being completed.

Configure the backend MCP capability-token hashes with:

```bash
NEPSIS_MCP_CAPABILITY_TOKEN_HASHES=operator-1:<sha256-of-capability-token>
```

Only token hashes and labels are stored. MCP clients send the raw capability
token as `Authorization: Bearer <token>` or `X-Nepsis-Capability-Token` when
calling tools.

For a private live operator deployment, use a separate environment from the
public demo. Hosted model routes stay disabled by default; enable them only with
`NEPSIS_DEPLOYMENT_MODE=operator`, `NEPSIS_LIVE_OPERATOR_ENABLED=true`,
`NEPSIS_MODEL_ROUTES_ENABLED=true`, exact-email OTP allowlisting, login email
delivery, backend auth, rate limits, and explicit server-side model credentials.
Do not enable live model routes on the public demo deployment.

### Private operator deployment

Start private operator Vercel env from `nepsis-web/.env.operator.example`, not
the public template. That path requires a reachable backend, `NEPSIS_API_TOKEN`,
`NEPSIS_OPERATOR_PACKET_SEAL_SECRET`, `NEPSIS_AUTH_SECRET`,
`NEPSIS_AUTH_ALLOWED_EMAILS`, real email delivery with `RESEND_API_KEY` and
`NEPSIS_AUTH_FROM_EMAIL`, `NEPSIS_DEPLOYMENT_MODE=operator`,
`NEXT_PUBLIC_NEPSIS_OPERATOR_SITE=true`, `NEPSIS_LIVE_OPERATOR_ENABLED=true`,
`NEPSIS_MODEL_ROUTES_ENABLED=true`, and a server-side
`OPENAI_API_KEY` or `NEPSIS_OPENAI_API_KEY`.

After deployment, run:

```bash
NEPSIS_SITE_BASE_URL=https://nepsis-cgn.vercel.app scripts/site-smoke.sh
```

The script uses Python stdlib HTTP calls and checks `/`, `/mvp`, `/api/status`,
`/api/engine/health`, `POST /api/engine/mvp`, unauthenticated auth session
state, disabled public model routes, and the playground config endpoint.

Before committing deployment env files or public-site config changes, run:

```bash
.venv/bin/python scripts/check_openai_secrets.py --all
```

The repo also includes a local `pre-commit` hook that runs the same checker on
staged files and blocks hardcoded OpenAI keys, browser-exposed key env names,
deprecated browser-key flags, and public-site env combinations that would enable
model routes, anonymous engine controls, login preview codes, wildcard CORS, or
server OpenAI keys.

### Private demo runtime endpoint

`POST /v1/private-demo` is the backend target for the NepsisAI authenticated
Full Private Demo page. It is protected by the same backend API token policy as
the non-public API routes and requires an explicit no-PHI acknowledgement.
Production and operator deployments must also set
`NEPSIS_OPERATOR_PACKET_SEAL_SECRET` because the private demo runtime returns a
nested sealed operator packet audit.

Example:

```bash
curl -sS -X POST https://<private-backend>/v1/private-demo \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <backend-token>" \
  -d '{
    "case_id": "jailing",
    "prompt": "No PHI. Source token is JINGALL and the candidate answer collapses to JAILING; preserve the mismatch and show the packet audit.",
    "no_phi_acknowledged": true,
    "thread_id": "private-demo-thread",
    "user_id": "private-demo-user"
  }'
```

The response has `schema_id: "nepsis.private_demo_runtime_packet"`,
`mode: "external-private-runtime"`, a nested
`operator_packet.schema_id: "nepsis.operator_packet"`, and audit events such as
`LOCK_FRAME`, `RUN_REPORT`, `LOCK_REPORT`, and `SET_THRESHOLD_DECISION`. The
`RUN_REPORT` interpretation includes a validated
`case_reasoning_compiler` packet so thresholding consumes domain-specific RED
hazard, closure, authority-pushback, and trajectory fields rather than a
process-safety receipt.
This is a no-PHI packet/audit runtime for invited testing. It is not the public
deterministic `/v1/mvp` packet and it is not an autonomous clinical or model
recommendation endpoint.

## Public API and MCP

Public-safe web access is `POST /api/engine/mvp` from the Vercel app. The direct
FastAPI `POST /v1/mvp` endpoint remains protected by `NEPSIS_API_TOKEN` in shared
deployments so the web proxy can control CORS and rollout posture.

The backend also exposes an HTTP MCP JSON-RPC endpoint at `/mcp`. `initialize`
and `tools/list` are discoverable without a token. Every hosted `tools/call`
requires a Nepsis capability token and returns packet-in/packet-out tool
results; NepsisCGN stores no provider API keys and no packet bodies for
stateless MCP calls. MCP is a tool surface, not a model-provider bypass:
Codex/ChatGPT, Claude Code, and Gemini users should connect their own
authenticated client to Nepsis tools rather than routing their model account
through NepsisCGN.

See [docs/public-api.md](docs/public-api.md) for request examples and the MCP
tool list.
See [docs/hosted-mcp-codex.md](docs/hosted-mcp-codex.md) for hosted Codex
streamable-HTTP MCP verification with a Nepsis capability token.
See [docs/local-mcp-harness.md](docs/local-mcp-harness.md) for copy-paste
local Codex, Claude Code, and Gemini CLI stdio config plus a host-config
verification flow for `nepsiscgn-mcp` or direct
`python -m nepsis_cgn.mcp.stdio` entrypoints.

## Clickable UI Demo

Start the local UI:

```bash
cd nepsis-web
npm run dev
```

Open `http://localhost:3000/mvp`, choose `Jailing` or `Clinical`, then click `Run Demo`.

## MVP Freeze Demo Script

1. Open `/mvp`.
2. Point to the header flow: RED → STILL → BLUE → STILL → commitment → state feedback → audit.
3. Run `Jailing`.
4. Show RED preserving the governed `JINGALL` source-token constraint.
5. Show STILL preventing naive commitment.
6. Show contradiction and denominator collapse forcing retessellation.
7. Show ZeroBack reset.
8. Show State Feedback declaring expected next-state checks.
9. Open the raw JSON and audit trace.
10. Run `Clinical`.
11. Show RED preserving high-consequence clinical uncertainty and final output listing required discriminators.

## Canonical MVP Packet Fields

- `case_id`
- `input_text`
- `observations`
- `constraints`
- `red_channel`
- `still.checkpoints`
- `blue_channel`
- `contradiction_monitor`
- `denominator_collapse`
- `non_quiescence`
- `zeroback`
- `voronoi_commitment`
- `state_feedback`
- `audit_trace`
- `final_output`

## Core Architecture

- Signal intake parses scenario input into observations, context, constraints, hypotheses, and unknowns.
- RED Channel runs first and preserves must-not-miss hazards and governing constraints.
- STILL asks whether the engine has permission to continue, hold, retessellate, or stop.
- BLUE Channel performs bounded analytic reasoning inside the RED safety boundary.
- Contradiction and denominator collapse detection prevent premature narrative closure.
- ZeroBack records reset logic when contradiction or wrong-manifold risk persists.
- State Feedback declares what the next observed state should show if the frame is correct.
- Audit packets preserve the ordered reasoning trace.

Runtime architecture also includes the triage → projection → validation supervisor, reference manifolds, manifest loader, tension-aware manifold governor, and LLM provider registry. Runtime `nepsis.iteration_packet` output includes `still` as the finalization interlock for session/API runs.

These broader engine/session/LLM flows are experimental in v0.3. Keep `/mvp`,
`POST /v1/mvp`, and `POST /api/engine/mvp` as the frozen deterministic demo
path.

## Tests and Environment Notes

Run the backend tests:

```bash
.venv/bin/python -m pytest -q
```

Run the web checks:

```bash
cd nepsis-web
npm run lint
npm run build
```

Environment notes:

- Python must be >=3.11.
- Use `.venv/bin/python`; system `python3` may be Python 3.9.
- `OPENAI_API_KEY` is required only for reviewed server-side private operator model calls.
- `NEPSIS_MCP_CAPABILITY_TOKEN_HASHES` stores hosted MCP capability-token hashes, not provider keys.
- NepsisCGN does not collect browser/user provider API keys. Hosted model calls require reviewed server-side private operator credentials; bring-your-own-model workflows should use MCP-capable hosts that authenticate to their own provider accounts.
- The simulated provider exercises red-channel repair without external model access.
- The OpenAI provider maps the `openai` alias to `gpt-4o` unless a specific `gpt-*` model is supplied.
- Security policy: [SECURITY.md](SECURITY.md).
- License: [LICENSE](LICENSE).

## Open Model Harness Direction

The local MVP launcher is intentionally model-free. The frozen `/mvp` path
stays deterministic. The model harness boundary is now MCP-first: NepsisCGN
exports deterministic tools and stateless operator packets, while the user's
Codex/ChatGPT, Claude Code, Gemini CLI, or other MCP-capable host supplies the
model and pays its own subscription or API usage. NepsisCGN should not collect
OpenAI, Anthropic, or Gemini provider keys for this path.

- OpenAI/ChatGPT/Codex users should connect through their own authenticated
  client or an OAuth-style ChatGPT connector in a later branch.
- Claude and Gemini users should use their own MCP-capable client or CLI auth
  path and pass Nepsis only packet/tool inputs.
- Hosted model calls through Nepsis remain private and disabled unless a
  separate operator deployment explicitly enables and caps them.
- Raw provider key collection has been removed from the web app; do not
  reintroduce it as a browser-storage or raw database-token path.

## Known Limitations

- Runtime State Feedback is not implemented; current State Feedback is deterministic MVP packet scaffolding.
- API session packets and MVP packets are separate shapes.
- LLM integration is not part of the deterministic MVP demo path.
- Engine sessions and playground/model sandbox calls are experimental operator paths.
- system `python3` may be Python 3.9; use `.venv/bin/python`.
- `pytest -q` alone may fail unless the package/environment is installed correctly.

## v0.4 Backlog Stub

Do not expand the v0.3 architecture unless v0.4 development is explicitly opened.

Candidate v0.4 work:

- Decide whether runtime State Feedback should become a live feedback engine.
- Decide whether API session packets and MVP packets should converge.
- Define how LLM integration should call into the deterministic governance packet path without making the MVP demo dependent on live model behavior.
- Expand demo documentation before adding architecture.

## Additional CLI Examples

The canonical v0.3 MVP command is `.venv/bin/python -m nepsis_cgn.cli.main --json mvp --case jailing`. These older or broader runtime examples are useful for engine exploration, but they are not the primary MVP quickstart.

- Puzzle: `nepsiscgn --json puzzle --letters JAIILUNG --candidate JAILING`
- Safety red/blue: `nepsiscgn --json safety --critical-signal`
- Safety with governance gate: `nepsiscgn --json --c-fp 1 --c-fn 9 safety --critical-signal`
- Safety with iteration packet: `nepsiscgn --json --emit-packet safety --critical-signal`
- Safety committed-stage packet: `nepsiscgn --json --emit-packet --commit safety --critical-signal`
- Safety with override capture: `nepsiscgn --json --c-fp 1 --c-fn 9 --continue-override --override-reason "Need confirmatory test" safety --critical-signal`
- Safety with packet sink: `nepsiscgn --json --packet-dir ./packets safety --critical-signal`
- Clinical red/blue: `nepsiscgn clinical --radicular-pain --spasm-present --notes "L5 paresthesias"`
- Legacy word game: `python -m nepsis.cli --mode word_game --letters "JANIGLL" --model simulated`
- Legacy UTF-8 hidden marker: `python -m nepsis.cli --mode utf8 --target "NEPSIS" --model simulated`
- Legacy seed manifold: `python -m nepsis.cli --mode seed --candidate "OK" --model simulated`
- Legacy gravity/ARC: `python -m nepsis.cli --mode arc --query "[[0,0,0],[0,1,0],[0,0,0],[2,2,2]]" --model simulated`

## Handoff Notes

- March continuity, deployment/auth notes, local machine paths, and side-branch notes were moved to `docs/handoff.md`.
- Operator rehearsal checklist: `docs/operator-runbook.md`.
- The manifest loader uses `data/manifests/manifest_definitions.yaml`; pass `--manifest /path/to/manifest_definitions.yaml` for a custom manifest.
- Governance draft: `briefs/nepsis_governance_spec_v1.md`.
