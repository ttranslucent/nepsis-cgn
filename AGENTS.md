# NepsisCGN Agent Notes

This repo is not a greenfield redesign. Preserve the existing Python package,
FastAPI/HTTP API, Next web app, manifest loader, manifold runtime, and packet
lineage work.

## Current Entry Points

- CLI: `nepsiscgn` via `src/nepsis_cgn/cli/main.py`
- HTTP API: `nepsiscgn-api` via `src/nepsis_cgn/api/server.py`
- FastAPI ASGI: `nepsiscgn-api-asgi` via `src/nepsis_cgn/api/asgi.py`
- Engine service: `src/nepsis_cgn/api/service.py`
- Next UI: `nepsis-web/src/app/engine/page.tsx`
- Next API proxy: `nepsis-web/src/app/api/engine`

## MVP Discipline

- Keep RED Channel before BLUE Channel.
- Do not replace the manifold/navigation runtime with a generic chatbot flow.
- Canonical MVP packet output lives in `src/nepsis_cgn/core/mvp.py`.
- Existing iteration packet output lives in `src/nepsis_cgn/core/packet.py`.
- Run tests with `.venv/bin/python -m pytest -q` from repo root.
