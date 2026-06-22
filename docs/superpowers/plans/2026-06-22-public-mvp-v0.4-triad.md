# Public MVP v0.4 Triad Implementation Plan

## Objective

Ship the public deterministic MVP v0.4 packet set with exactly three public
cases:

- `jailing`: JINGALL/JAILING hard source-constraint preservation.
- `sea_ivdu`: revised spinal epidural abscess red-channel preservation from
  intravenous-use risk.
- `wirecard`: financial authority-suppression and unverifiable-cash governance.

The release must preserve `/mvp`, `POST /v1/mvp`, and
`POST /api/engine/mvp` as public, deterministic, login-free, and model-free.

## Implementation Steps

1. Update tests first.
   - Change MVP packet tests to expect schema version `0.2.0`.
   - Replace public `clinical` coverage with `sea_ivdu` and `wirecard`.
   - Assert the SEA packet keeps RED open from intravenous-use risk alone.
   - Assert the Wirecard packet keeps RED open until independent cash evidence.
   - Update web fallback tests to require exactly the three public cases.
   - Extend public artifact and Playwright checks so `/mvp` exposes and runs all
     three cases without model or auth dependencies.

2. Update canonical packet builder.
   - Bump `MVP_PACKET_SCHEMA_VERSION` to `0.2.0`.
   - Change public `MvpCaseId` values to `jailing`, `sea_ivdu`, and `wirecard`.
   - Add a compact public v0.4 release block to each packet.
   - Keep RED-before-BLUE, STILL, contradiction monitor, retessellation,
     ZeroBack, state feedback, and final output fields stable for topology and
     raw packet views.
   - Ensure old `clinical` public case ids are rejected by the public builder.

3. Regenerate bundled fallback packets.
   - Build `nepsis-web/src/data/mvpPackets.json` from the canonical Python
     packet builder after the backend packet changes land.
   - Keep fallback packet comparison deterministic by ignoring only generated
     identifiers and timestamps.

4. Update public UI and operational copy.
   - Update `/mvp` case selector to the v0.4 triad.
   - Say "Public MVP v0.4", "Deterministic packet proof",
     "Model-free deterministic run", and "No login or API key required".
   - Do not imply live model reasoning, clinical diagnosis, financial advice,
     or private benchmark execution.
   - Update nearby docs that describe the frozen public packet set.

5. Verify.
   - Run focused pytest coverage for MVP packets, fallback packets, and public
     deployment artifacts.
   - Run the full backend pytest suite if focused tests pass.
   - Run frontend lint and the public-site Playwright flow.
   - Use browser verification on `/mvp` to confirm all three public cases are
     visible and runnable.

6. Finish through GitHub when verification is clean.
   - Commit the implementation.
   - Push the branch.
   - Open a PR.
   - Merge to `main` and push/pull cleanly if CI and local verification support
     it.
   - Leave stale May stashes untouched unless separately authorized.

## Proof Required

- Backend packet tests pass for all three public cases.
- Bundled fallback packets match the canonical packet builder.
- Public artifact tests continue to prove `/mvp` is not using model-assist or
  operator-model routes.
- Browser or Playwright verification shows the v0.4 public page can run all
  three deterministic cases.
