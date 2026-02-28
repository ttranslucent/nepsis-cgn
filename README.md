NepsisCGN v0.3
================

NepsisCGN is a governance-first reasoning engine that runs sidecar to LLMs. It enforces a three-step protocol—Triage → Projection → Validation—with a ZeroBack repair loop and explicit red/blue channels. This repository includes reference manifolds, an LLM provider registry, and a CLI for quick runs.

Key Components
--------------
- Supervisor: orchestrates triage → projection → validation with bounded retries and ZeroBack deltas.
- Manifolds:
  - WordGameManifold (multiset/dictionary check with repair hints).
  - UTF8HiddenManifold (enforces hidden U+200B marker).
  - Utf8StreamManifold (RFC-style UTF-8 validator/normalizer).
  - SeedManifold (Voronoi-style adversarial seed demo).
  - GravityRoomManifold (ARC-style physics with stepwise gravity and collision detection; static vs mobile separation, graded blue_score).
- Geometry: additive-weighted Voronoi engine for seed-based partitioning.
- Meta: DevianceMonitor adjusts tau_R based on SAFE / NEAR_MISS / CRASH history.
- LLM Providers: simulated stub and OpenAI provider (defaults to gpt-4o; map “openai” alias).
 - Interpretant layer: Bayesian selector that binds signs to manifolds (semantic worlds) and instantiates constraint geometry, transforms, and ruin seeds.
 - Manifold Governor: tension-aware collapse gate with history/velocity to catch acute spikes vs slow drift; emits trace metadata for UI.

CLI Usage
---------
Examples:
- Word game: `python -m nepsis.cli --mode word_game --letters "JANIGLL" --model simulated`
- UTF-8 hidden marker: `python -m nepsis.cli --mode utf8 --target "NEPSIS" --model simulated`
- Seed manifold: `python -m nepsis.cli --mode seed --candidate "OK" --model simulated`
- Gravity/ARC: `python -m nepsis.cli --mode arc --query "[[0,0,0],[0,1,0],[0,0,0],[2,2,2]]" --model simulated`
- OpenAI (needs OPENAI_API_KEY): `python -m nepsis.cli --mode arc --model openai --query "[[0,0,0],[0,1,0],[0,0,0],[2,2,2]]"`

LLM Provider Registry
---------------------
- Simulated: exercises red-channel repair (hallucinates once, then complies).
- OpenAI: Chat Completions; use `--model openai` (maps to gpt-4o) or a specific gpt-* model.

Tests
-----
Run `pytest -q` (current suite covers word-game, UTF-8 hidden/stream, seed manifold, deviance monitor, and gravity manifold).

Notes
-----
- OPENAI_API_KEY must be set for real model calls.
- ZeroBack adds `next_projection_delta` on validation failure to tighten subsequent prompts.
- GravityRoomManifold treats IDs on the bottom row as static terrain; only mobile objects fall. Blue score is graded by error density.
- Governance spec (draft): `briefs/nepsis_governance_spec_v1.md`

Architecture Overview
---------------------
- Signs (input) → Interpretant layer → manifold selection/construction → constraint solving → collapse governor → output.
- Interpretant = manifold selector: chooses manifold family and fills seeds, transformation rules, ruin nodes, success signatures; updates posteriors via Bayesian weights.
- Manifold = instantiated interpretant: defines constraint geometry and transforms; evaluated by CGNSolver.
- Manifold Governor = temporal vitals: tracks tension history/velocity/accel, triggers warn/collapse/ruin, and logs causes for traceability.
- Manifest loader: YAML-driven interpretant/manifold registry (`data/manifests/manifest_definitions.yaml`) with per-manifold governor thresholds.

Flow (semantic locking before solving):
```
Sign / Raw Input -> parse -> Interpretant Manager (posterior over manifolds)
    -> select Manifold (family + seeds + transforms + ruin)
    -> Manifold.run(sign) -> CGNSolver
    -> ManifoldGovernor (tension history + velocity/accel)
    -> decision (continue/warn/collapse/ruin) + trace
```

Clinical and puzzle examples:
- Puzzle: strict_set vs phonetic_variant manifolds (Jailing/Jingall) with ruin on missing hidden letters; silent-U and I/J transforms optional.
- Clinical: radicular_spasm (blue) vs cauda_equina (red) manifolds with red-flag ruin seeds and follow-up transforms; interpretant likelihood favors cauda when saddle/bladder flags appear.

CLI
---
Install deps (ensure `pyyaml` is present) and run:
- Puzzle: `nepsiscgn --json puzzle --letters JAIILUNG --candidate JAILING`
- Safety red/blue: `nepsiscgn --json safety --critical-signal`
- Safety with governance gate: `nepsiscgn --json --c-fp 1 --c-fn 9 safety --critical-signal`
- Safety with iteration packet: `nepsiscgn --json --emit-packet safety --critical-signal`
- Safety committed-stage packet: `nepsiscgn --json --emit-packet --commit safety --critical-signal`
- Safety with override capture: `nepsiscgn --json --c-fp 1 --c-fn 9 --continue-override --override-reason "Need confirmatory test" safety --critical-signal`
- Safety with packet sink: `nepsiscgn --json --packet-dir ./packets safety --critical-signal`
- Clinical red/blue: `nepsiscgn clinical --radicular-pain --spasm-present --notes "L5 paresthesias"`

Backend API (Engine Sessions)
-----------------------------
Run local backend API server:
- `nepsiscgn-api --host 127.0.0.1 --port 8787`

Endpoints:
- `POST /v1/sessions` create session (`family`: `puzzle|clinical|safety`, optional `governance`, `frame`)
- `GET /v1/sessions` list session summaries
- `GET /v1/sessions/{session_id}` session summary (stage/frame/packet count)
- `DELETE /v1/sessions/{session_id}` delete session and in-memory state
- `POST /v1/sessions/{session_id}/step` run one iteration (`sign`, optional `commit`, `user_decision`, `override_reason`)
- `POST /v1/sessions/{session_id}/reframe` update frame version
- `GET /v1/sessions/{session_id}/packets` replay packets
- `GET /v1/routes` route manifest for API discoverability
- `GET /v1/health` health check

Example session flow:
```bash
curl -sX POST http://127.0.0.1:8787/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"family":"safety","governance":{"c_fp":1,"c_fn":9}}'
```
```bash
curl -sX POST http://127.0.0.1:8787/v1/sessions/<SESSION_ID>/step \
  -H 'Content-Type: application/json' \
  -d '{"sign":{"critical_signal":true},"commit":false}'
```

The CLI loads `data/manifests/manifest_definitions.yaml`, instantiates interpretants/manifolds, runs navigation with tension-aware governor, and emits a trace (manifold, decision, tension/velocity, cause, posterior). Add `--manifest /path/to/manifest_definitions.yaml` to use a custom manifest.

What Is a Manifold?
-------------------
A manifold is a semantic world with its own constraints, ruin conditions, tension parameters, and transformation rules. The interpretant selects the manifold; the governor evaluates tension inside it. If evidence no longer fits, the system collapses or vectors to a new manifold.

Example Run
-----------
- Puzzle (strict-set ruin):
  - `$ nepsiscgn --json puzzle --letters JAIILUNG --candidate JAILING`
  - `{"manifold":"strict_set","decision":"ruin","cause":"RUIN_NODE",...}`
- Clinical (benign radicular):
  - `$ nepsiscgn clinical --json --radicular-pain --spasm-present --notes "L5 paresthesias"`
  - `manifold=radicular_spasm decision=continue tension=0.0 posterior={'clinical_radicular_spasm': 0.75, 'clinical_cauda_equina': 0.25}`
- Clinical (cauda red flags):
  - `$ nepsiscgn clinical --json --radicular-pain --saddle-anesthesia --bladder-dysfunction`
  - `{"manifold":"cauda_equina","decision":"continue","tension":0.0,"posterior":{"clinical_radicular_spasm":0.27,"clinical_cauda_equina":0.73}}`
- Safety (red-channel escalation):
  - `$ nepsiscgn --json safety --critical-signal`
  - `{"manifold":"red_channel","decision":"warn","cause":"ABS_TENSION",...}`
