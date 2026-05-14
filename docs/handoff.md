# NepsisCGN Handoff Notes

These notes were moved out of the root README during the v0.3 MVP freeze documentation refactor. They are preserved for continuity, not as the public quickstart.

## Current Working State (2026-03-17)

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
