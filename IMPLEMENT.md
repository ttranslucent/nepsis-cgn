# NepsisCGN MVP Implementation

## Files Added

- `src/nepsis_cgn/core/still.py`
  - Builds the deterministic STILL checkpoint pathway for canonical MVP packets.
  - Emits checkpoint logic, commitment readiness, learning notes, and STILL audit events.

- `src/nepsis_cgn/core/state_feedback.py`
  - Builds the deterministic MVP State Transition Monitor field.
  - Declares current state, predicted next state, failure conditions, pending delta analysis, and loop decision.

- `src/nepsis_cgn/core/mvp.py`
  - Builds the canonical `nepsis.mvp_packet`.
  - Supports `jailing` and `clinical` cases.
  - Preserves required packet fields: RED Channel, STILL checkpoints, BLUE Channel, contradiction monitor, denominator collapse, Voronoi commitment, non-quiescence, ZeroBack, State Feedback, audit trace, and final output.

- `tests/test_mvp_packet.py`
  - Proves canonical shape, RED-before-BLUE ordering, constraint preservation, and retessellation.

## Files Updated

- `src/nepsis_cgn/cli/main.py`
  - Adds `nepsiscgn --json mvp --case jailing|clinical`.

- `src/nepsis_cgn/api/server.py`
  - Adds `POST /v1/mvp` to the built-in HTTP server.

- `src/nepsis_cgn/api/asgi.py`
  - Adds `POST /v1/mvp` to the FastAPI app.

- `src/nepsis_cgn/core/__init__.py`
  - Exports the MVP packet builder.

- `tests/test_cli_main.py`
  - Adds CLI coverage for canonical MVP packet output.

- `tests/test_engine_api_server.py`
  - Adds route/openapi coverage and handler coverage for `POST /v1/mvp`.

## Demo Commands

```bash
.venv/bin/python -m nepsis_cgn.cli.main --json mvp --case jailing
```

```bash
NEPSIS_API_ALLOW_ANON=true .venv/bin/python -m nepsis_cgn.api.server --host 127.0.0.1 --port 8787
```

```bash
curl -s -X POST http://127.0.0.1:8787/v1/mvp \
  -H 'Content-Type: application/json' \
  -d '{"case_id":"jailing"}'
```
