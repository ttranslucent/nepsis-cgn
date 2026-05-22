# NepsisCGN Handoff Notes

These notes were moved out of the root README during the v0.3 MVP freeze documentation refactor. They are preserved for continuity, not as the public quickstart.

## Current Working State (2026-05-22)

- Primary repo path: `/Users/trentthorn/Code/nepsiscgn`
- Reference-only accidental workspace from earlier Codex work:
  - `/Users/trentthorn/Documents/Codex/2026-05-21/have-built-the-harness-now-i/nepsis-cgn`
- Current feature branch:
  - `codex/stateless-user-model-connectivity`
- Current draft PR:
  - `https://github.com/ttranslucent/nepsis-cgn/pull/4`
- `main` currently includes PR #3:
  - `4beedc1` (`[codex] add live operator path (#3)`)
- PR #4 currently contains:
  - stateless `nepsis.operator_packet` v2 runtime,
  - shared MCP handler for stdio and HTTP,
  - hosted MCP capability-token auth for all `tools/call` requests,
  - docs/status updates for user-owned model connectivity,
  - negative tests for missing capability tokens and missing commit trace gates.
- Canonical path for user-owned model connectivity:
  - `src/nepsis_cgn/api/operator_packet.py`
  - `src/nepsis_cgn/mcp/handler.py`
  - `src/nepsis_cgn/mcp/stdio.py`
  - FastAPI/HTTP wiring in `src/nepsis_cgn/api/asgi.py` and `src/nepsis_cgn/api/server.py`
- Existing stateful `/v1/operator/*` routes remain private/transitional for the
  current operator UI and compatibility. They are not the canonical hosted model
  harness path.
- Most recent detailed ledger entry:
  - `ledger/sessions/2026-05-22_session-50.md`

## May 2026 Pickup

1. To inspect current PR work:
   - `git switch codex/stateless-user-model-connectivity`
   - `git status -sb`
   - `gh pr view 4 --web`
2. To check readiness:
   - `gh pr checks 4`
   - `.venv/bin/python -m pytest -q`
   - `cd nepsis-web && npm run lint`
   - `cd nepsis-web && npm run build`
3. If PR #4 is accepted:
   - `gh pr merge 4 --squash`
   - `git checkout main`
   - `git pull --ff-only`
4. Keep the public MVP boundary intact:
   - `/mvp` remains deterministic and model-free.
   - Hosted model routes stay disabled unless a separate operator deployment
     explicitly enables and caps them.
   - MCP users bring their own model host and provider account.

## Previous Working State (2026-03-17)

- Primary branch: `main`
- Primary repo path: `/Users/trentthorn/Code/nepsiscgn`
- Start point: current `main` HEAD in this repo path
- Stable product anchor commit: `4a0aec4` (`feat: harden nepsis web auth and engine deployment flow`)
- `main` includes:
  - stage-gate integration hardening and adversarial QA verifier/report artifacts,
  - passwordless auth repair with signed cookies and optional Resend delivery,
  - `/engine` connectivity/status hardening for deployed environments,
  - Vercel-facing `nepsis-web` README and `.env.example` updates,
  - close-out handoff notes in the root README and ledger.
- Local sidecar branch preserved for unrelated follow-up work:
  - `codex/openai-secret-hygiene` at `9cae352`

## March Session Pickup

1. Confirm clean starting point:
   - `git switch main`
   - `git pull --ff-only`
2. Re-verify the web app if touching `/engine` or auth:
   - `cd nepsis-web && npm run lint`
   - `cd nepsis-web && npm run build`
3. Review the latest handoff notes:
   - `ledger/sessions/2026-03-11_session-47.md`
   - `ledger/sessions/2026-03-17_session-48.md`
   - `ledger/sessions/2026-03-17_session-49.md`
4. For deployment follow-up, start with:
   - `nepsis-web/README.md`
   - `nepsis-web/.env.example`

## May 2026 MVP Freeze

- Freeze baseline before README refactor: `3d775d3` (`Polish MVP header flow`) on `main`.
- Documentation freeze follow-up: `517a207` (`Document MVP freeze demo script`) on `main`.
- The MVP is considered complete enough to stop architecture expansion.
- Next work should be documentation, demo rehearsal, and operator-facing explanation unless a new scope is approved.
- Architecture and packet behavior are MVP-complete enough to stop expanding; do not retessellate the architecture unless v0.4 is explicitly opened.

## Notes Moved From Root README

- The root README is now the public front door for v0.3.
- Local machine paths, preserved side branches, March close-out notes, deployment/auth continuity, and ledger references live here instead.
- `ledger/sessions/` remains the detailed chronological record.
