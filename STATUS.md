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

## Private Authority Candidate (Inactive)

- The durable canonical-run ledger, Ed25519 receipts, challenged snapshots,
  detached export verifier, and immutable governance-profile snapshots are
  implemented behind the separate loopback private runtime.
- Proposal disposition is distinct from application. Acceptance retains a
  STILL hold; release is explicit; only a validator-authored commit applies the
  exact content-addressed proposal.
- ZeroBack preserves protected context roots, and irrecoverable conversation
  recovery creates an atomically lineage-bound fork rather than rebinding a
  new thread to the old run.
- This code does not activate `cgn_writer`, freeze legacy MC sessions, or alter
  public `/mvp`. Activation still requires the separately reviewed signed
  cutover marker and adoption evidence.

## Broken

- `pytest -q` is not reliable in this checkout unless the package is installed.
- system `python3` is Python 3.9, but the project declares Python >=3.11.

## Missing

- Runtime State Feedback is not implemented; the current State Feedback field is deterministic MVP packet scaffolding only.
- API session packets and MVP packets are separate shapes.
- LLM integration is not part of the deterministic MVP demo path.

## Next Patch

Operational review only: inspect the signed capability-policy and adoption
evidence before any cutover decision. Preserve the `/mvp` UI path, the
`/api/engine/mvp` proxy to `POST /v1/mvp`, and the frozen deterministic packet
shape.
