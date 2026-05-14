# NepsisCGN MVP Status

## MVP Freeze

- Freeze baseline: `3d775d3` (`Polish MVP header flow`) on `main`.
- Architecture and packet behavior are MVP-complete enough to stop expanding.
- Next work should be documentation, demo rehearsal, and operator-facing explanation only.

## Working

- `.venv/bin/python -m pytest -q` passes.
- CLI demo emits canonical packet:
  - `.venv/bin/python -m nepsis_cgn.cli.main --json mvp --case jailing`
- API demo route is present:
  - `POST /v1/mvp`
- RED Channel is ordered before BLUE Channel in `audit_trace`.
- Runtime iteration packets include `still` as the finalization interlock.
- Jailing demo preserves the governing `JINGALL` constraint and rejects `JAILING`.
- Contradiction, denominator collapse, retessellation, non-quiescence, two STILL checkpoints, ZeroBack, State Feedback, and final discriminators are explicit fields.

## Broken

- `pytest -q` is not reliable in this checkout unless the package is installed.
- system `python3` is Python 3.9, but the project declares Python >=3.11.

## Missing

- Runtime State Feedback is not implemented; the current State Feedback field is deterministic MVP packet scaffolding only.
- API session packets and MVP packets are separate shapes.
- LLM integration is not part of the deterministic MVP demo path.

## Next Patch

Docs-only. Preserve the `/mvp` UI path, the `/api/engine/mvp` proxy to `POST /v1/mvp`, and the frozen deterministic packet shape.
