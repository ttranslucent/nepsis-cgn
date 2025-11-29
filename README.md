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
