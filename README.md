# NepsisCGN v0.3

Last verified: 2026-05-19

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

- `/mvp` is public, deterministic, and does not require login or model keys.
- `/status` shows backend, auth, model-route, and MCP readiness.
- `/engine`, `/playground`, and `/settings` are operator surfaces. Public production hides or gates API-key/model flows.
- Production should not set `OPENAI_API_KEY`, `NEPSIS_OPENAI_API_KEY`, `NEPSIS_ENGINE_ALLOW_ANON`, or `NEPSIS_AUTH_ALLOW_CODE_PREVIEW` unless a separate protected operator deployment has been reviewed.

Deploy the existing FastAPI backend as the API service. `render.yaml` defines a
Render web service that installs `.[api]`, starts `nepsiscgn-api-asgi`, binds to
`0.0.0.0:$PORT`, sets `NEPSIS_API_TOKEN`, configures CORS origins, and stores
engine sessions under `/var/data` when sessions are enabled.

Configure the Vercel web app with:

```bash
NEPSIS_API_BASE_URL=https://<render-service>
NEPSIS_API_TOKEN=<same-token-as-render>
NEPSIS_AUTH_SECRET=<long-random-secret>
NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true
NEPSIS_MODEL_ROUTES_ENABLED=false
```

After deployment, run:

```bash
NEPSIS_SITE_BASE_URL=https://nepsis-cgn.vercel.app scripts/site-smoke.sh
```

The script uses Python stdlib HTTP calls and checks `/`, `/mvp`,
`/api/engine/health`, `POST /api/engine/mvp`, auth session state, and the
playground config endpoint.

## Public API and MCP

Public-safe web access is `POST /api/engine/mvp` from the Vercel app. The direct
FastAPI `POST /v1/mvp` endpoint remains protected by `NEPSIS_API_TOKEN` in shared
deployments so the web proxy can control CORS and rollout posture.

The backend also exposes a minimal HTTP MCP JSON-RPC endpoint at `/mcp` with
tools `run_mvp`, `get_mvp_schema`, `health`, and protected `get_routes`.
MCP is a tool surface, not a model-provider bypass: Codex/ChatGPT, Claude Code,
and Gemini users should connect their own authenticated client to Nepsis tools
rather than routing their model account through NepsisCGN.

See [docs/public-api.md](docs/public-api.md) for request examples and the MCP
tool list.

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
- `OPENAI_API_KEY` is required only for real model calls.
- Browser-stored OpenAI keys are local-demo only; do not use them as shared deployment secrets.
- The simulated provider exercises red-channel repair without external model access.
- The OpenAI provider maps the `openai` alias to `gpt-4o` unless a specific `gpt-*` model is supplied.
- Security policy: [SECURITY.md](SECURITY.md).
- License: [LICENSE](LICENSE).

## Open Model Harness Direction

The local MVP launcher is intentionally model-free. The frozen `/mvp` path
should stay deterministic while v0.4 explores an open model harness that uses
supported host or CLI authentication flows instead of asking operators to paste
provider API keys into NepsisCGN.

- OpenAI API calls use API keys, while Codex supports ChatGPT sign-in. Future
  OpenAI integration should prefer a supported Codex, ChatGPT Apps SDK, or MCP
  path where that fits the harness boundary. See
  [OpenAI API authentication](https://developers.openai.com/api/reference/overview#authentication),
  [Codex authentication](https://developers.openai.com/codex/auth), and
  [Apps SDK authentication](https://developers.openai.com/apps-sdk/build/auth).
- Claude account-based use needs separate review: Anthropic documents API-key
  methods for third-party Agent SDK integrations unless claude.ai login access
  is separately approved. See the
  [Claude Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview).
- Gemini can be approached through an already-authenticated Gemini CLI flow or
  an explicit OAuth/ADC design. See
  [Gemini CLI authentication](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/authentication.mdx)
  and [Gemini OAuth](https://ai.google.dev/gemini-api/docs/oauth).

## Known Limitations

- Runtime State Feedback is not implemented; current State Feedback is deterministic MVP packet scaffolding.
- API session packets and MVP packets are separate shapes.
- LLM integration is not part of the deterministic MVP demo path.
- Engine sessions, playground/model sandbox calls, and browser-stored OpenAI keys are experimental.
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
