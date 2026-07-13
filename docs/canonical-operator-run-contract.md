# Canonical Operator Run Contract

Version: `nepsis.canonical_operator_run@0.1.0`

Status: target-state governing contract for a private, local-first,
single-operator run authority. The ledger, protected HTTP surface, independent
verifier, read-only import pilot, and loopback evaluation entrypoint are
implemented adoption-gate components, not a designation of canonical
authority. This contract does not change the current public MVP, stateless
operator-packet, or MCP contracts. Use for operator pilot work is forbidden
until the gate passes.

## 1. Object Under Test

The object under test is whether NepsisCGN can become the sole canonical owner
of private Nepsis packet state, audit events, artifacts, lineage, governance
decisions, and verification receipts while:

- Codex App Server owns conversational continuity and non-canonical history;
- NepsisMC remains a trust-bearing cockpit and integration client;
- the operator retains disposition and commitment authority;
- models remain proposal-only actors;
- the public deterministic `/mvp` path remains model-free and unchanged; and
- existing NepsisMC sessions do not acquire a second canonical writer.

The authority rule is:

> Codex proposes. The operator disposes. NepsisCGN validates and commits.

## 2. Non-Negotiable Invariants

1. Exactly one canonical append boundary exists for a run.
2. RED completes before BLUE may rank an action.
3. BLUE utility cannot compensate for an unresolved RED blocker.
4. STILL is a commitment interlock, not a display state.
5. ZeroBack preserves evidence, contradictions, protected constraints, and
   lineage while reopening the frame or hypothesis class.
6. Models cannot accept, reject, defer, override, release, seal, or commit.
7. Actor identity is assigned by the authenticated capability boundary; input
   payloads cannot declare or elevate their own actor.
8. Stale expected heads cannot mutate canonical state.
9. Event, artifact, projection, idempotency, and head updates are one atomic
   transaction.
10. A packet projection is reconstructable from canonical events and artifacts.
11. A conversation, UI cache, provider response, or model claim is never
    canonical state.
12. No private ledger, authentication state, or model-facing behavior is added
    to the public `/mvp` runtime.

## 3. Ownership Topology

### 3.1 Codex App Server owns

- conversation threads, turns, interruptions, and resumption;
- non-canonical transcript history and compaction;
- requests for clarification;
- provisional explanations and candidate proposals; and
- authenticated ChatGPT session, model, usage, and host status reporting. The
  operator and provider, not App Server, retain account authority.

Codex history may be useful and durable, but it is not required to reconstruct
canonical Nepsis state.

### 3.2 NepsisCGN owns

- run identity and current canonical head;
- event ordering, canonical serialization, and hashes;
- immutable content-addressed artifacts;
- packet, phase, governance, and lineage projections;
- stale-write detection and idempotency;
- RED, BLUE, STILL, ZeroBack, contradiction, and denominator-collapse legality;
- operator-governance profile revisions and session snapshots;
- private canonical exports; and
- append and verification receipts.

### 3.3 NepsisMC owns

- the local cockpit and direct-manipulation experience;
- durable local binding of one Codex thread to one NepsisCGN run;
- capability-separated requests on behalf of model and operator actors;
- streamed conversation presentation;
- compact verified receipts and failure truthfulness;
- optional non-canonical caches; and
- migration orchestration while the cutover gate is incomplete.

NepsisMC remains trust-bearing even when it is thin in domain logic. It must
keep model prose, requested actions, tool results, and verified canonical status
visibly distinct.

### 3.4 The operator owns

- candidate acceptance, rejection, or deferral;
- required confirmations and rationales;
- operator-governance profile revision;
- session-scoped overrides;
- STILL release and gate unlock;
- ZeroBack invocation; and
- final decision commitment.

## 4. Deployment and Public Boundary

The canonical run authority is a protected private surface. Its first supported
deployment is a loopback-only, single-operator process with durable local
storage. A hosted or multi-user writer requires a separate storage, identity,
authorization, tenancy, backup, and threat contract.

The implementation must not:

- change `/mvp`, `/v1/mvp`, public fallback packets, or public release fixtures;
- add provider calls to public or stateless NepsisCGN routes;
- share the private canonical database with a public serverless process;
- store canonical data under serverless `/tmp`;
- expose private run discovery or mutation without authentication; or
- overload the ambient singleton `/v1/operator/*` surface as the canonical API.

Private canonical routes use the run-addressed prefix
`/v1/operator-runs/{run_id}`. The exact HTTP surface is additive and remains
separate from the public application. The evaluation runtime exposes neither
public `/mvp` nor OpenAPI/docs discovery.

### 4.1 Isolated evaluation runtime

`nepsiscgn-private-runs` is the only supported process entrypoint for the
current private evaluation surface. It requires all of the following:

- `NEPSIS_CANONICAL_RUNS_ENABLED=1`;
- `NEPSIS_CANONICAL_RUNS_BIND_HOST`, which must be a literal loopback address
  and defaults to `127.0.0.1`;
- `NEPSIS_CANONICAL_RUNS_PORT`, which defaults to `8789`;
- distinct absolute, non-temporary database paths in
  `NEPSIS_CANONICAL_RUNS_STORE_PATH` and
  `NEPSIS_GOVERNANCE_PROFILE_STORE_PATH`;
- an existing Ed25519 PEM key at
  `NEPSIS_CANONICAL_RUNS_SIGNING_KEY_PATH`, with group and other permissions
  denied, plus `NEPSIS_CANONICAL_RUNS_SIGNING_KEY_ACTIVATED_AT`; and
- distinct model, operator, and validator bearer tokens of at least 32
  characters in `NEPSIS_CANONICAL_RUNS_MODEL_TOKEN`,
  `NEPSIS_CANONICAL_RUNS_OPERATOR_TOKEN`, and
  `NEPSIS_CANONICAL_RUNS_VALIDATOR_TOKEN`.

Missing, disabled, non-loopback, temporary-storage, weak-token, duplicate-token,
invalid-key, or invalid-port configuration fails startup closed. The runtime
enables the closed operator set `submit_operator_disposition`, `release_still`,
`perform_zeroback`, and `request_decision_commit`. Disposition records review
without application. STILL release requires the exact accepted proposal and
proposal-review hold. Decision commitment applies only the artifact's exact
requested change through a validator-authored event after all canonical
preconditions pass. ZeroBack replaces only the frame root and records the
protected roots it preserves. Both policy bindings are immutable run-genesis
inputs. Enabling any other action requires a deterministic adapter and adoption
step, not an environment toggle.

## 5. Canonical Object Set

The initial neutral object identifiers are:

- `nepsis.canonical_run@0.1.0`
- `nepsis.canonical_run_event@0.1.0`
- `nepsis.canonical_run_artifact@0.1.0`
- `nepsis.canonical_run_protected_export@0.1.0`
- `nepsis.operator_visible_proposal@0.1.0`
- `nepsis.operator_proposal_state@0.1.0`
- `nepsis.operator_disposition_policy@0.1.0`
- `nepsis.canonical_actualization_policy@0.1.0`
- `nepsis.proposal_application@0.1.0`
- `nepsis.zeroback_state@0.1.0`
- `nepsis.external_codex_ref@0.1.0`
- `nepsis.context_manifest@0.1.0`
- `nepsis.thread_run_binding@0.1.0`
- `nepsis.action_request@0.1.0`
- `nepsis.action_receipt@0.1.0`
- `nepsis.action_receipt_trust_anchor@0.1.0`
- `nepsis.import_receipt@0.1.0`
- `nepsis.run_snapshot_attestation@0.1.0`
- `nepsis.verification_report@0.1.0`
- `nepsis.operator_governance_profile@0.1.0`
- `nepsis.session_governance_snapshot@0.1.0`

Each neutral object declares one object-specific version field whose value is
the complete identifier, such as
`canonical_run_schema_version: nepsis.canonical_run@0.1.0`. It does not carry a
second independently mutable schema ID. Canonical identifiers, hashes,
timestamps, and idempotency behavior are schema fields, not transport metadata.

### 5.1 Run identity

A canonical run has a stable `run_id`, `owner_id`, creation timestamp, status,
current head sequence/hash, packet projection hash, pinned system-policy
versions/hashes, pinned governance snapshot hash, and optional migration or fork
provenance. Fork provenance includes `forked_from_run_id`, the parent source
head, inherited evidence roots, a policy-diff artifact hash, and fork reason.

The head event hash is the `run_revision` and may advance for an event that does
not change packet content. `packet_projection_hash` separately identifies the
packet projection. A reconstructed projection does not receive a new random
identity. Any display `packet_id` is derived from or bound to the packet
projection hash, not merely the audit head.

### 5.2 Event identity

Every event records:

- run ID and monotonic sequence;
- event schema, type, and timestamp;
- server-assigned actor and provenance class;
- previous event hash;
- canonical payload hash;
- event hash;
- idempotency key and intent hash when mutation was requested;
- caused-by event/artifact hashes when applicable; and
- referenced artifact hashes.

Events are append-only. Update or deletion is prohibited.

### 5.3 Artifact identity

Artifacts are immutable, content-addressed canonical bytes. The database stores
the artifact body, schema/version, role, and hash. Hash-only provenance is not a
substitute for a reconstructable canonical artifact.

### 5.4 External Codex reference

An external Codex reference records only the provenance required to identify a
consequential proposal:

- host type and adapter version;
- account fingerprint when available, never credentials;
- thread, turn, and tool-call identifiers;
- model and model-configuration epoch;
- exact operator-visible proposal artifact hash; and
- optional non-canonical transcript export reference.

The full conversation is not copied into the canonical event chain.

### 5.5 Operator-visible proposal

A consequential model proposal is stored as an immutable content-addressed
artifact. It contains the normalized requested change, the exact
operator-visible proposal and rationale, named evidence references, and
alternatives and hazard summary. A paired external Codex reference binds that
proposal artifact hash to its origin; the proposal does not hash the external
reference back and therefore creates no content-addressing cycle. Omission or
mutation of any displayed consequential content changes the artifact hash and
invalidates the request binding.

The packet projection carries a closed
`nepsis.operator_proposal_state@0.1.0` lifecycle. A recorded model candidate
creates one `pending` state bound to the proposal hash, candidate intent,
adapter, and pinned disposition policy. A pending proposal cannot be silently
replaced. An operator disposition moves that same state to `accepted`,
`rejected`, or `deferred`, binds the confirmation and disposition intent, and
changes no other packet field. Acceptance records review; it does not apply the
proposal's requested change.

An accepted proposal keeps an active STILL hold at `proposal_review`.
`release_still` changes only the postcondition to `decision_ready`; it does not
change packet content. `request_decision_commit` must repeat the exact
content-addressed proposal change and is refused during denominator collapse or
while any contradiction or RED-hazard root remains unresolved. Only the
validator-authored `decision_committed` event writes the governed field record
and `nepsis.proposal_application@0.1.0` evidence. The signed receipt remains
operator-authored and the event records the exact `requested_by_actor_id`.

`perform_zeroback` is a separate repair transition. It replaces the frame root,
places an active hold, and records a `nepsis.zeroback_state@0.1.0` proof that
evidence, observation, population, contradiction, and RED-hazard roots were
preserved. It cannot be used as a hidden proposal-application path.

### 5.6 Context manifest

NepsisCGN generates every context manifest from a canonical snapshot. A model or
adapter may only echo its hash; it cannot author, trim, or substitute the
manifest. Every model-authored candidate binds to a manifest covering:

- run ID, current run head, and packet projection hash;
- active frame and population roots;
- operator profile, session snapshot, and effective governance-policy hashes;
- evidence and observation roots;
- unresolved RED hazards and contradictions;
- denominator-collapse and active-hold state; and
- relevant artifact revisions.

Matching only the current event head is insufficient if the proposal cites a
superseded semantic artifact. A missing or stale manifest refuses the candidate.

### 5.7 Thread/run binding

NepsisMC owns an append-only control-plane binding log separate from packet
truth. Each record includes owner/account fingerprint, thread ID, run ID,
adapter version, binding status, creation/revocation timestamps, and the last
verified run head. A thread binds to exactly one run. A run has at most one
active thread; recovery requires explicit revocation of the prior binding before
a replacement thread becomes active. Failed host resume never leaves a durable
binding that the host did not confirm.

### 5.8 Read-only import receipt

`nepsis.import_receipt@0.1.0` records admission of one full, unredacted,
independently verified, sealed NepsisMC bundle into the immutable import pilot.
It binds the source session and audit tip, subject, artifact root, complete
bundle hash, deterministic imported-run ID, verifier scope, import time, and
source authenticity classification. It always declares `read_only: true` and
is signed by the local CGN import service. The CGN signature authenticates the
receipt issuance; it does not upgrade the source bundle from
`unanchored_self_consistency` to externally anchored truth. An imported bundle
is not a live canonical run and cannot be mutated or silently replayed into the
writer.

## 6. Capability and Actor Boundary

V0 capabilities are intentionally narrow:

| Capability | Actor | Effect |
|---|---|---|
| `read_snapshot` | model or operator | Read bounded verified state. |
| `create_run` | operator | Create a run with a pinned governance snapshot and validated pre-genesis overrides. |
| `submit_model_candidate` | model | Record a revision-bound candidate only. |
| `submit_operator_disposition` | operator | Record accept, reject, or defer of the exact pending proposal; do not apply it. |
| `revise_operator_profile` | operator | Create a new reusable profile revision. |
| `release_still` | operator | Request release with confirmation and rationale. |
| `perform_zeroback` | operator | Request governed reframe/repair. |
| `request_decision_commit` | operator | Authorize a commit attempt with required rationale. |
| `export_run` | operator or detached read client | Export a bounded verification bundle. |
| `verify_run` | detached read client | Verify an export without mutation authority. |
| `import_sealed_bundle` | validator import service | Admit one verified sealed bundle to the immutable read-only import registry. |

The server ignores or refuses any payload-supplied `actor`, `provenance_class`,
or authority claim. Model and operator capabilities use separate credentials or
unforgeable local capability handles and separate idempotency namespaces.

A UI click is not sufficient operator provenance unless it is a fresh local
gesture tied to the exact action payload, confirmation, and rationale required
by policy.

Profile creation and lifecycle actions are not run mutations. They use a
separate private profile-registry boundary with profile-head expected-revision
CAS, idempotency, and operator capability. A profile action cannot advance a run
head. Only `create_run` may consume validated pre-genesis overrides.

## 7. Append Transaction

Every `nepsis.action_request@0.1.0` includes:

- `action_request_schema_version`, run ID, and trusted adapter intent ID;
- `expected_head_event_hash` and expected sequence;
- a transport-scoped capability whose actor is assigned by the server;
- canonical intent hash;
- idempotency key;
- context-manifest, governance-profile, and referenced artifact hashes; and
- operator confirmation/rationale when required.

Inside one database transaction, NepsisCGN must:

1. authenticate capability and assign actor identity;
2. lock or compare the current run head;
3. resolve idempotency and reject conflicts;
4. validate schema, policy pins, references, authority, phase, holds, and gates;
5. persist required immutable artifacts;
6. append the canonical event or eligible canonical refusal;
7. update packet, phase, governance, lineage, and receipt projections;
8. advance the run head; and
9. commit all changes together.

Any failure rolls back the entire transaction.

A stale expected head returns a non-mutating action receipt containing the
actual head. It does not append a new event to the head it failed to match.
Malformed, unauthenticated, unsupported-version, and stale requests never
append. A structurally admitted governance or domain refusal appends exactly one
`validator_refusal_created` event while leaving the governed packet projection
unchanged.

## 8. Idempotency, Concurrency, and Recovery

- Replaying the same idempotency key and intent hash returns the original
  receipt without adding events or artifacts.
- Reusing an idempotency key with a different intent hash is refused.
- Two writers targeting the same expected head cannot both advance it.
- The append API exposes query-by-idempotency-key for lost acknowledgements.
- No client may optimistically display canonical success before reading a
  verified receipt at the new head.
- Process restart reconstructs the identical event, artifact, packet, and
  lineage identities.
- Corruption, missing artifacts, projection mismatch, or unsupported versions
  fail closed and never regenerate a plausible replacement identity.

## 9. Verified Receipts and Independent Verification

An action receipt reports request identity, prior and resulting heads, status,
event/artifact hashes, policy versions, canonical postcondition summary,
signer/key identity, signature, and verification level. Its outcome is exactly
one of `candidate_recorded`, `committed`, `refused`, `stale_head`, or
`invalid_request`. An idempotent replay returns the original receipt unchanged;
transport metadata may separately report `replayed: true`. Only a receipt built
from a post-commit CGN reread may report a committed outcome. An operator
authorization does not itself emit `decision_committed`; only the deterministic
validator may emit it after all gates pass. Model prose cannot manufacture or
override a receipt.

V0 action receipts use Ed25519 over neutral canonical bytes. A loopback writer
loads a local private key outside the ledger, and each
`nepsis.canonical_run_protected_export@0.1.0` includes the exact pinned public
trust anchor plus one signed receipt for every persisted outcome. The export
root binds the event chain, artifacts, packet projection, outcomes, receipts,
and trust anchor. The current writer accepts one active, non-revoked anchor and
refuses startup with a revoked anchor. A durable key-lifecycle/rotation ledger
is not implemented yet and remains an adoption blocker; prior receipts cannot
be relabeled as current under a replacement key.

For thread resume and cache reconciliation, the client sends a fresh challenge
hash to the protected snapshot-attestation route. The signed
`nepsis.run_snapshot_attestation@0.1.0` binds that challenge to the current run
head, packet projection, governance pins, and validator policy. A replayed
attestation for a different challenge is not fresh evidence and cannot advance
a thread/run binding.

The current detached verifier:

- consumes exported bytes without database, model, Codex, or writer access;
- does not import NepsisMC code or NepsisCGN ledger/projection implementations;
- verifies artifact and event-chain integrity, export-attestation binding,
  pinned contracts and policies, projection references, lineage graphs,
  decision and phase reconstruction, RED-before-BLUE/STILL ordering, and exact
  Markdown reconstruction;
- independently recomputes the checked-in supported semantic path: accepted
  manual-calibration materialization, non-resampled integer inference, and RED
  and BLUE governance;
- reports, rather than implies, that blocked/discriminator governance,
  denominator-collapse repair, inference rejuvenation, inference resampling,
  and model-calibration proposal quality remain unverified branches; a bundle
  that actually takes an unsupported semantic branch is labeled in
  `unverified_claims` as `subject_semantic_path:<reason>`;
- distinguishes self-consistency from externally anchored authenticity; and
- verifies checked-in golden and tamper vectors from both repositories.

A successful report therefore means `valid: true` within the stated
`verification_scope`; it still reports `adoption_eligible: false`,
`anchor_status: unanchored`, and
`authenticity: unanchored_self_consistency`. Unsupported branches are not
listed in `verified_checks`, and unanchored verification is not a claim about
the external truth of the source observations.

A detached verification produces a separate
`nepsis.verification_report@0.1.0` that binds the export root, checked action
receipts, verifier version, check results, authenticity status, and optional
anchor. A writer action receipt is never renamed into an independent
verification report.

The protected-run export verifier is separate from the writer and store. It
verifies the export root, canonical event chain, artifact references, packet
and postcondition hashes, all outcome/receipt identities, Ed25519 signatures,
and run governance pins. When proposal events are present, it also independently
reconstructs the closed pending-to-disposed lifecycle, exact proposal-artifact
causes, confirmation/capability intent binding, pinned adapter policy, and the
invariant that disposition changes no non-lifecycle packet field. Broader domain
projection semantics, external observation truth, and external timestamp
authority remain unverified; therefore a valid protected export remains
`adoption_eligible: false` until the remaining domain-semantic and operational
gates pass.

## 10. Conversation and Data Boundary

The local transport does not make OpenAI inference local. Each run records a
data classification and whether remote inference is authorized. The cockpit
shows retention and remote-processing status while a Codex thread is active.

Codex may continue non-canonical discussion while the ledger is unavailable,
but it cannot submit a candidate, release a gate, or claim commitment. Recovery
requires a fresh verified snapshot and context manifest.

One Codex thread binds to one canonical run. A new thread may continue from a
verified run snapshot, but an existing thread cannot be silently rebound to
another run or operator identity. Binding state is control-plane provenance and
must be durable, auditable, and recoverable without becoming packet truth.

## 11. Migration and Cutover

Migration is one-way and gate-controlled:

1. NepsisMC remains the sole writer while NepsisCGN implements detached
   verification.
2. NepsisCGN verifies a full NepsisMC interop bundle and produces a scoped,
   explicitly unanchored verification result.
3. The read-only import pilot may admit one verified synthetic bundle and issue
   a signed `nepsis.import_receipt@0.1.0`. That receipt preserves the source
   authenticity classification and does not make the import a mutable run.
4. A later, separately approved private CGN migration may use the verified
   source as an immutable bootstrap root with explicit operator approval.
5. The imported run is reconstructed byte-for-byte and exercised through one
   append, restart, export, and detached verification cycle.
6. New pilot sessions are created only in CGN. No session has two writers.
7. Existing NepsisMC sessions remain readable and exportable; they are not
   silently replayed into a second live chain.
8. After the adoption gate passes, NepsisMC disables canonical mutation for
   CGN-owned runs and becomes a client/cache/projection surface.

There is no bidirectional audit-chain synchronization and no last-write-wins
merge.

## 12. Adoption Gate

The CGN writer may become authoritative only after tests prove:

1. append-only event and immutable-artifact enforcement;
2. atomic event/artifact/projection/idempotency/head commitment;
3. stale-head and concurrent-writer refusal;
4. idempotent recovery after a lost acknowledgement;
5. byte-equivalent reconstruction after restart;
6. stable run, event, artifact, packet-revision, and lineage identities;
7. crash injection at each transaction boundary leaves no partial state;
8. model capability cannot invoke operator actions or self-assign provenance;
9. operator disposition and T3/T4 rationale/confirmation requirements;
10. RED-before-BLUE, STILL, ZeroBack, contradiction, and collapse invariants;
11. governance-profile pinning and override behavior;
12. exact Codex proposal/context provenance and stale semantic-reference refusal;
13. import and independent verification of NepsisMC golden bundles;
14. tamper-vector refusal and truthful authenticity labels;
15. thread/run/account binding cardinality, explicit rebinding revocation, and
    failed-resume recovery;
16. full public `/mvp`, public fallback, stateless packet, and MCP regression;
17. clean-process restart on durable local storage; and
18. no canonical writes or private-data reads from the public deployment;
19. unauthenticated private discovery, read, export, and mutation refusal;
20. profile-registry CAS, retry idempotency, lifecycle projection, comparator,
    and concurrent-activation behavior;
21. fork lineage and unchanged-parent verification;
22. context manifests are CGN-generated and cannot be selectively omitted or
    model-authored;
23. proposal-artifact omission or tampering is refused;
24. Ed25519 receipt signing, rotation, revocation-time, and anchor reporting; and
25. NepsisMC has no canonical write path for a CGN-owned run after cutover.

Failure of any gate leaves NepsisMC as the canonical writer and CGN as verifier
or experimental pilot. It does not justify weakening the contract.

## 13. Deliberate V0 Non-Goals

- public, hosted, multi-user, or clinical-production canonical writing;
- autonomous profile learning or candidate promotion;
- transcript duplication into the audit chain;
- a general policy DSL or arbitrary JSON Patch;
- profile inheritance graphs;
- model-selected actor, authority, tier, waiver, or commitment;
- bidirectional synchronization of NepsisMC and NepsisCGN audit chains;
- changing the deterministic public MVP; and
- deleting the existing NepsisMC writer before verified cutover.
