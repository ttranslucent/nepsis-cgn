# RED Authority and Anti-Capture Contract

Version: `nepsis.red_authority_contract@0.1.0`

Status: governing semantic invariant with partial reference-runtime enforcement.
The public deterministic `/mvp` packet and behavior are unchanged. A typed,
canonical RED-hazard assessment and supersession transition remains an explicit
private-authority adoption blocker.

## 1. Object Under Test

The object under test is whether Nepsis can preserve a credible ruin boundary
without allowing RED to become an unfalsifiable explanation, a global veto, or
an indefinitely repeating escalation pathway.

The governing rule is:

> RED has authority over admissibility, not authority over truth.

Ruin remains non-compensatory for the actions that would traverse a qualified
ruin boundary. Severity does not establish that the ruin hypothesis is true,
erase competing explanations, or select the positive action by itself.

The compact doctrine is **asymmetric commitment, symmetric falsifiability**:

- irreversible commitment may require a lower threshold for protective friction;
- every claim that a ruin criterion applies remains answerable to evidence; and
- a RED veto may remain active while its frame, scope, or applicability is
  challenged.

## 2. Distinct Objects

Nepsis must not collapse these objects into one flag:

1. **Ruin criterion** — the protected definition of an unacceptable outcome.
2. **Applicability claim** — the evidence-linked claim that the criterion applies
   to the current frame and exposure.
3. **RED veto** — the named actions made inadmissible while that applicability
   claim remains qualified and unresolved.
4. **Protective response** — the containment, test, delay, or escalation chosen
   to preserve the boundary.
5. **Working explanation** — the best-supported account of what is true.

The ruin criterion may be locked and non-waivable while the applicability claim,
veto scope, and protective response remain reviewable. Preserving a hazard's
lineage does not mean preserving its unresolved status forever.

## 3. Non-Negotiable Invariants

1. RED precedes BLUE when defining the admissible action set.
2. BLUE cannot trade away a qualified unresolved ruin boundary with aggregate
   utility, fluency, or confidence.
3. RED cannot convert severity into likelihood or claim truth authority.
4. A veto is scoped to the actions capable of traversing the named hazard. A
   global veto requires evidence that the exposure is global.
5. Competing explanations and evidence against RED applicability remain visible.
6. The protective response is itself governed. Its direct harm, delay,
   irreversibility, resource burden, information loss, and opportunity cost must
   be inspectable.
7. Nepsis chooses the least-burdensome reversible response that preserves the
   qualified boundary. An irreversible protective response requires its own
   explicit justification.
8. Every RED hold names a safe next discriminator, a review trigger, and release
   or narrowing criteria.
9. Review, contradiction, or ZeroBack never silently releases a live veto.
10. Repeated RED without a changed action, changed evidence, or explicit review
    is a governance failure, not proof that continued escalation is correct.

## 4. RED Capture

**RED capture** is the failure mode in which a protected hazard acquires
unearned epistemic or global decision authority. Signals include:

- the same escalation repeats beyond the configured RED dwell limit;
- disconfirming evidence cannot lower the hazard's applicability;
- ambiguity is repeatedly counted as evidence for ruin;
- the veto scope expands without new evidence;
- BLUE's best-supported explanation disappears without being falsified;
- the protective response prevents the discriminator needed to test RED;
- response burden rises without reducing exposure; or
- no governed release or narrowing path exists.

A RED-capture trigger requires reflexive review. The veto remains active while
Nepsis runs a safe discriminator or ZeroBack. The review challenges the current
frame and applicability claim, not the protected ruin criterion.

## 5. Response Ladder

RED is not a single all-or-nothing response:

1. A merely conceivable hazard is recorded without acquiring a veto.
2. A credible but safely testable hazard receives monitoring or a bounded hedge.
3. A qualified, action-relevant hazard receives minimum sufficient containment
   plus the next safe discriminator.
4. A credible one-way-door exposure with no reliable later checkpoint receives
   a hard veto over the actions that traverse it.
5. Persistent RED that is not gaining information enters reflexive review or
   ZeroBack while retaining the applicable veto.

Cost asymmetry affects the response, not the truth status of the hazard. A high
ruin mass may block unsafe commitment even when the least-cost response is
containment and discrimination rather than immediate escalation.

Default `logit-v2` calibration does not count ambiguity, posterior entropy,
margin collapse, contradiction density, or a constraint explicitly classified
as `manifold_mismatch` as evidence that the bad state is true. Those signals may
require more search or a different frame, but they do not strengthen the
protective-action cost case merely because the selected interpretation was
falsified. Explicit non-default calibration remains inspectable in the packet.

## 6. STILL and ZeroBack

STILL has two interlocks:

- **Hazard gate:** does a qualified unresolved hazard make this commitment
  inadmissible?
- **Capture gate:** has RED remained scoped, falsifiable, cost-visible, and
  responsive to evidence?

Failure of either gate blocks irreversible finalization. Bounded reversible
containment or information gathering may remain legal when explicitly named.

ZeroBack preserves the ruin criterion, source evidence, contradictions, and
prior assessment lineage. It replaces the frame or applicability assessment. A
later governed assessment may narrow, contain, resolve, or supersede the live
hazard state without deleting its history.

## 7. Packet Contract

Reference runtime `nepsis.iteration_packet@0.2.0` records RED decision authority
separately from governance posture:

- `governance.red_veto_active` says whether unsafe commitment remains blocked;
- `governance.red_authority.applicability_basis` distinguishes direct ruin and
  ruin-mass evidence from the expected-loss cost gate;
- a cost-gate crossing by itself produces review, not a RED veto;
- `governance.red_authority.decision_scope` is `unsafe_commitment`;
- `governance.red_authority.epistemic_scope` states that RED is a hazard-
  applicability claim, not truth selection;
- `governance.red_authority.posterior_hypothesis_weights_preserved` says only
  that the packet retains the posterior hypothesis map; it does not claim that
  complete competing explanations or evidence assessments are present;
- both protective-action and omitted-protection losses remain visible; and
- `RED_CAPTURE_REVIEW` latches applicability review without clearing the veto.

The reference veto is a coarse interlock over the controller's single global
commit/finalization class. It does not prohibit bounded evidence gathering or
other reversible work, but it also does not implement the named, per-action
scope required for canonical authority. `decision_scope=unsafe_commitment`
must not be read as proof of full scoped-veto enforcement.

A cost review pauses commitment until it is reviewed or explicitly
dispositioned with a recorded reason. That operator-disposition path does not
release a RED veto and does not give expected-loss arithmetic RED truth
authority.

Under the default `evidence-v2` policy:

- `evidence_update.content_hash` is computed from substantive observation
  content, excludes top-level `evidence_id` and `independent_observation`, and
  removes those control tags when they are embedded in free-text notes;
- replaying an `evidence_id` with the same content does not update the posterior,
  while reusing that ID with different content is refused;
- anonymous duplicate content and duplicate content under a new ID are also
  deduplicated unless the caller supplies both an explicit ID and an
  `independent_observation` attestation;
- `independent_observation=true` is a recorded caller attestation, not runtime
  proof that two sources are genuinely independent; and
- rotating IDs or cosmetic note changes cannot disguise an unchanged structured
  RED-applicability signature for capture dwell. An admitted observation with
  an explicit independence attestation counts as genuinely new evidence for the
  reference dwell heuristic.

The posterior-deduplication hash detects normalized field-content changes; it
does not prove that a changed note is materially new evidence. The separate
capture-dwell signature therefore ignores note churn, but evidentiary
materiality still remains part of the typed canonical-assessment adoption gate.

The reference runtime maintains two different latches. A capture-review latch
persists while RED remains active and clears only when applicability clears or a
substantive reframe with an explicit rationale occurs. A directly observed ruin
criterion remains latched across reframe and unassessed follow-up; releasing it
requires a newly admitted, explicitly identified, independence-attested
observation whose relevant RED fields are all assessed negative.

That independence is caller-attested in the reference runtime. It is not
canonical proof of independent provenance. Canonical release requires the typed
assessment, evidence relationships, and verifier described below.

Full canonical enforcement requires a typed
`nepsis.red_hazard_assessment@0.1.0` artifact with, at minimum:

- criterion, frame, and prior-assessment references;
- applicability state and evidence for and against it;
- named blocked actions and minimum sufficient protection;
- safeguard burden and reversibility;
- next safe discriminator, review trigger, and release/narrowing criteria; and
- `open`, `contained`, `resolved`, or `superseded` state with complete lineage.

## 8. Current Enforcement Boundary

The reference runtime now:

- permits newly admitted negative evidence to lower RED posterior mass without
  counting duplicate content repeatedly;
- distinguishes RED veto state from posture and from expected-loss cost review;
- uses containment plus discrimination when ruin alone crosses the boundary but
  the cost gate does not justify escalation;
- tracks the structured RED-applicability signature rather than caller-supplied
  evidence IDs or free-text note churn, while recording explicit independence
  attestations when new evidence resets the reference dwell heuristic; and
- enters a latched RED-applicability review after the repeated-content dwell
  limit while keeping STILL blocked and the veto active. The reference
  controller does not silently execute ZeroBack; an explicit governed reframe or
  qualifying discriminator remains required.

Ambient-session replay now pins the manifest and policy identities, preserves
the RED/evidence checkpoint and exact packet lineage across commits and
restarts, and validates integrity digests for both the checkpoint and the full
stored packet-artifact list before restoration. Stateless operator packets carry
the cumulative governed trace and sealed checkpoint across iteration cycles and
refuse manifest or policy drift. The local-session SHA-256 bindings detect
corruption or one-sided alteration; they are not authenticated proof against an
attacker able to rewrite both stored content and its digest. Stateless packet
integrity uses the configured packet seal boundary.

The safety reference signal requires an explicit `critical_signal` value, so a
false value can lower posterior applicability. Clinical red flags are tri-state:
unassessed values remain likelihood-neutral, while an explicitly assessed-
absent red-flag set can lower posterior applicability. Lowering that posterior
is distinct from releasing a directly observed ruin latch, which requires the
qualified independent observation described above.

The inactive canonical-run implementation still carries only global
`unresolved_red_hazard_hashes`. It preserves them through ZeroBack and has no
governed assessment-supersession transition. That behavior remains fail-closed,
but it can leave a hazard indefinitely unresolvable within that run under the
current policy version. It must not be described as complete RED anti-capture
enforcement or activated as canonical authority until the versioned assessment,
scoped blocker derivation, transition, verifier, and regression proof exist.

## 9. Required Proof

Adoption-level proof must show:

1. disconfirming evidence can lower RED applicability without deleting history;
2. genuine ruin still blocks the named unsafe commitment;
3. repeated RED requires reflexive review rather than repeated escalation;
4. ZeroBack preserves the veto while reopening the frame;
5. a governed assessment can narrow or resolve applicability with evidence;
6. unrelated actions remain admissible when the veto is scoped;
7. safeguard burden and induced harm remain visible; and
8. public `/mvp` semantics, packet shape, and model-free boundary remain
   unchanged; declared dynamic fields such as `packet_id` and `created_at` are
   excluded from normalized equality checks.
