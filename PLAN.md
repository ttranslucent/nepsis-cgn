# NepsisCGN MVP Plan

## What Already Works

- Python package imports and tests pass in the local `.venv`.
- CLI supports puzzle, clinical, and safety manifold runs.
- API supports session create/step/reframe/packet replay/stage-audit.
- Next web app has an engine UI and API proxy for the backend engine.
- Manifest config exists at `data/manifests/manifest_definitions.yaml`.
- RED/BLUE channel manifolds exist in `src/nepsis_cgn/manifolds/red_blue.py`.
- Clinical red/blue manifolds exist in `src/nepsis_cgn/manifolds/clinical.py`.
- Iteration packet lineage/audit output exists in `src/nepsis_cgn/core/packet.py`.

## What Was Missing

- One canonical MVP packet with the requested fields.
- One deterministic demo path proving RED -> BLUE -> contradiction/retessellation -> audit packet.
- A direct CLI/API route for that MVP demo.
- Root handoff docs for the current implementation path.

## Smallest Path

1. Keep existing runtime and session engine intact.
2. Add a canonical MVP packet builder as a thin deterministic scaffold.
3. Expose the scaffold through CLI and API.
4. Add focused acceptance tests for packet shape, ordering, constraint preservation, and retessellation.
5. Document the verified run path.

## Acceptance Tests

- `.venv/bin/python -m pytest -q tests/test_mvp_packet.py`
- `.venv/bin/python -m pytest -q tests/test_cli_main.py tests/test_engine_api_server.py`
- `.venv/bin/python -m pytest -q`
