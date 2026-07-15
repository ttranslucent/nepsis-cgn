# Nepsis Neutral Interop Contracts

This directory contains persistence-independent JSON Schemas and pinned test
artifacts shared across the NepsisMC-to-NepsisCGN authority boundary.

Neutral objects use one object-specific version field containing the full
artifact identifier. They are canonicalized with
`nepsis.canonical_json@0.1.0`: NFC strings, ASCII snake-case keys, no nulls or
floats, JavaScript-safe integers, and millisecond UTC timestamps.

The checked-in NepsisMC bundle, golden fixture, and tamper declarations are
mirrored byte-for-byte. NepsisCGN verification code must not import NepsisMC or
the CGN ledger/projection implementation. Exact asset hashes are pinned in
`contract-manifest.json`.

These contracts describe an isolated non-authoritative test surface. Their
presence does not activate the private CGN writer or change public `/mvp`.

## Independent verification boundary

`verify_interop_bundle` accepts only full, unredacted
`nepsis.interop_bundle@0.2.0` objects. Its successful `verified_checks` cover:

- artifact and audit-chain integrity;
- export-attestation, policy, contract, projection-reference, and lineage
  binding;
- decision, phase, and exact Markdown reconstruction;
- RED-before-BLUE, STILL, and commitment ordering; and
- the supported semantic branch: accepted manual calibration, non-resampled
  integer inference, and RED/BLUE governance recomputation.

The result remains deliberately scoped. `unverified_claims` names
blocked/discriminator governance, denominator-collapse repair, rejuvenation,
resampling, and model-calibration proposal quality. If the subject actually
uses an unsupported semantic branch, the report adds
`subject_semantic_path:<reason>` instead of treating that branch as verified.
Success still reports `adoption_eligible: false`, `anchor_status: unanchored`,
and `authenticity: unanchored_self_consistency`. This proves bounded internal
consistency, not external truth or source identity.

`nepsis.canonical_run_protected_export@0.1.0` is the corresponding signed
private-run export. It carries the canonical run, events, artifacts, packet
projection, persisted outcomes, one signed action receipt per outcome, the
pinned receipt trust anchor, and an export root over all of those fields. Its
detached verifier does not import the writer or store. It independently
reconstructs the proposal pending/disposition lifecycle, explicit STILL
release, validator-owned exact proposal application, and ZeroBack preservation.
It also verifies the operator-request/validator-event identity split. A
separate pair verifier binds an atomically frozen predecessor to its forked
successor and checks exact policy-diff and inherited-evidence lineage. Broader
domain projection semantics, external observation truth, and external
timestamp authority remain unverified.

`nepsis.run_snapshot_attestation@0.1.0` is a challenged, signed current-head
view for thread resume and cache reconciliation. The caller supplies a fresh
challenge hash; a response for another challenge, run, policy pin, or trust
anchor cannot be reused as current evidence.

## Read-only import pilot

`nepsis.import_receipt@0.1.0` is the signed receipt for admitting a full,
sealed, committed/exported bundle to the immutable NepsisMC import registry.
It binds the complete bundle hash, subject hash, artifact root, source session
and audit tip, deterministic imported-run ID, verifier scope, and the source
authenticity classification. It always declares `read_only: true`.

The receipt signature proves which local CGN import service issued the receipt;
it does not convert `unanchored_self_consistency` into anchored authenticity,
does not create a live writer run, and does not authorize append. Replays return
the same signed receipt, while a changed bundle or idempotency request fails
closed.

## Private evaluation runtime

The separate `nepsiscgn-private-runs` entrypoint requires
`NEPSIS_CANONICAL_RUNS_ENABLED=1`, a literal loopback bind address, distinct
absolute non-temporary run/profile database paths, an access-restricted
Ed25519 signing key and activation timestamp, and distinct model/operator/
validator bearer tokens of at least 32 characters. See the canonical operator
run contract for the exact variable names.

This runtime is an inactive adoption-gate surface, not an activated canonical
operator deployment. Its operator-action resolver enables only four pinned
actions: proposal disposition, STILL release, ZeroBack, and decision-commit
request. The canonical-actualization policy applies a requested change only at
the validator-authored `decision_committed` event, after exact acceptance,
STILL release, and RED/contradiction/denominator checks. ZeroBack replaces only
the frame root and records preserved evidence, observation, population,
contradiction, and RED-hazard roots. Both disposition and actualization policy
bindings are pinned at run genesis; no environment variable bypasses them.
Public `/mvp`, API docs, and OpenAPI discovery are absent from the private app.
