# NepsisCGN v0.3

Last verified: 2026-05-14

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

## Quickstart

Clone and enter the repo:

```bash
git clone <repo>
cd nepsiscgn
```

One-time dependency setup:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,api]'
cd nepsis-web && npm ci && cd ..
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
- The simulated provider exercises red-channel repair without external model access.
- The OpenAI provider maps the `openai` alias to `gpt-4o` unless a specific `gpt-*` model is supplied.

## Known Limitations

- Runtime State Feedback is not implemented; current State Feedback is deterministic MVP packet scaffolding.
- API session packets and MVP packets are separate shapes.
- LLM integration is not part of the deterministic MVP demo path.
- system `python3` may be Python 3.9; use `.venv/bin/python`.
- `pytest -q` alone may fail unless the package/environment is installed correctly.

## v0.4 Backlog Stub

Do not retessellate the v0.3 architecture unless v0.4 is explicitly opened.

Candidate v0.4 work:

- Decide whether runtime State Feedback should become a live feedback engine.
- Decide whether API session packets and MVP packets should converge.
- Decide whether LLM integration belongs in the deterministic MVP path or remains separate.
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
- The manifest loader uses `data/manifests/manifest_definitions.yaml`; pass `--manifest /path/to/manifest_definitions.yaml` for a custom manifest.
- Governance draft: `briefs/nepsis_governance_spec_v1.md`.
