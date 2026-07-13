# Operator Governance Profile Contract

Version: `nepsis.operator_governance_profile@0.1.0`

Status: target-state governing contract for explicit, operator-owned governance
defaults and session-pinned effective policy. This contract is subordinate to
`nepsis.canonical_operator_run@0.1.0` and cannot weaken its system invariants.

## 1. Object Under Test

The object under test is whether an operator can personalize baseline
constraints, evidence posture, risk tolerance, and ruin criteria without:

- converting assistant memory into hidden authority;
- making RED, STILL, ZeroBack, audit, or commitment optional;
- relaxing a decision boundary after seeing an unwanted result;
- changing an existing session retroactively; or
- creating a policy language too broad to validate deterministically.

The product should feel configurable like an instrument while preserving the
laws that make the instrument trustworthy.

## 2. Three Visible Policy Layers

### 2.1 System constitution

The system constitution is locked and versioned. It includes:

- canonical truth comes only from the packet, artifacts, and audit chain;
- Codex and other models propose only;
- required operator disposition precedes deterministic commitment;
- RED precedes BLUE and ruin is non-compensatory;
- STILL, gate transitions, ZeroBack, sealing, and commitment are explicit legal
  actions;
- stale state, contradictions, denominator collapse, uncertainty, host loss,
  and refusal remain visible;
- no silent success, fallback, actor elevation, or cross-session rebinding;
- remote inference remains operator-authorized and limited to cleared non-PHI
  content without direct identifiers or secrets; and
- a profile cannot grant external-action authority to a model.

Every profile pins `constitution_version` and `constitution_hash`. A user or
session override cannot modify a constitutional field.

### 2.2 Operator profile

The operator profile is a reusable append-only revision containing standing
defaults. It is explicit, inspectable, and operator-owned. Codex may propose a
profile revision but cannot activate one.

### 2.3 Session governance snapshot

Session creation resolves the constitution, one active profile revision, and
eligible pre-genesis session overrides into an immutable effective-policy
snapshot. The session pins the profile revision/hash and effective-policy hash.

Later global profile revisions do not alter an open session. V0 does not permit
mid-session policy mutation. A requested change creates a new session fork when
allowed and preserves the original session and evidence.

## 3. Profile Identity and Lifecycle

Each immutable profile revision contains:

- `operator_governance_profile_schema_version`, containing the complete neutral
  object identifier;
- `profile_id`;
- monotonic `profile_revision`;
- constitution version/hash;
- creation timestamp;
- operator identity;
- parent profile revision/hash when applicable; and
- canonical artifact hash assigned over the immutable revision bytes.

Lifecycle is not hashed into the profile content artifact. Separate append-only
profile lifecycle events derive `draft`, `review_required`, `active`,
`superseded`, and `revoked`, including activation, supersession, and revocation
timestamps. Editing always creates a new immutable revision. At most one
revision of a profile is active for an operator at a time. Revocation prevents
new sessions from pinning the revision but does not alter sessions that already
pinned it.

Profile lifecycle actions use a private registry with expected profile-head
revision, idempotency key, and operator capability. Revision creation, lifecycle
event, active-profile projection, idempotency result, and receipt commit or roll
back atomically. Two concurrent activations targeting the same expected profile
head cannot both succeed.

## 4. V0 Operator Defaults

V0 is deliberately limited to typed fields with explicit comparison rules.

### 4.1 Governance defaults

- `clarification_budget`: integer from 0 through 5;
- `unresolved_optional_policy`: `hold` or `explicitly_defer`;
- `evidence_floor`: `operator_attestation`, `one_source`, or `corroborated`;
- `proposal_mode`: `one_at_a_time` or `grouped_low_risk`;
- `uncertainty_display`: `ranges`, `bands`, or `narrative_with_status`; and
- `data_scope`: a named scope no broader than the constitutional remote-data
  boundary.

### 4.2 Baseline constraints

Each baseline constraint records:

- stable constraint ID and label;
- strength: `soft`, `hard`, or `ruin`;
- applicability statement;
- evaluability definition;
- action on breach: `block`, `still`, or `zeroback`;
- override mode: `locked`, `tighten_only`, or `replaceable`; and
- rationale and source references.

A profile default seeds a new frame or session review. It does not silently
become a case-specific fact or mark itself satisfied.

Hard and ruin constraints are always `locked`. A soft constraint may be
`tighten_only` only when its named comparator is defined below; otherwise it is
`replaceable` and may change only through a new profile revision or pre-genesis
session preparation.

### 4.3 Risk dimensions

Risk is multidimensional and cannot be collapsed into one aggregate score. V0
supports:

- `human_harm`;
- `data_security_privacy`;
- `legal_authority_commitment`;
- `operational_recoverability`;
- `resource_financial_loss`; and
- `epistemic_integrity`.

Each configured dimension records:

- maximum tolerated severity from 0 through 3;
- loss posture: `balanced`, `downside_weighted`, or `ruin_averse`;
- evidence requirement: `standard`, `elevated`, or `strict`;
- reversibility requirement: `none`, `preferred`, or `required`;
- evaluability definition; and
- default response when tolerance is exceeded.

Severity meanings are:

- `0`: no identified material exposure;
- `1`: limited and readily reversible;
- `2`: material but credibly recoverable;
- `3`: severe or difficult to reverse; and
- `4`: ruin-level, catastrophic, or irrecoverable.

Severity 4 is constitutionally non-waivable and always produces RED plus the
configured hold/block/ZeroBack response regardless of profile tolerance. An
unknown applicable dimension at plausible severity 3 or 4 produces a hold, not
a passing score.

### 4.4 Ruin criteria

Each ruin criterion records:

- stable ruin ID, category, and concrete unwanted outcome;
- applicability statement;
- evaluability definition;
- whether it is constitutionally protected and therefore non-waivable;
- response: `block`, `still`, or `zeroback`;
- actions made inadmissible when triggered;
- override mode; and
- rationale and source references.

Any applicable unresolved ruin criterion enters RED regardless of aggregate
utility or normalized probability. BLUE cannot trade it away.

Every ruin criterion is constitutionally protected, non-waivable, and
`locked`; the profile may add criteria or tighten their responses but cannot
remove or relax a system criterion.

## 5. Evaluability

Every constraint, risk dimension, or ruin criterion uses exactly one
evaluability type:

### 5.1 `deterministic_boolean`

The validator can compute pass/fail from a supported criterion reference.
Failure blocks according to the configured response.

### 5.2 `ordinal_evidence`

The item records severity 0 through 4, confidence (`unknown`, `low`, `medium`,
or `high`), evidence references, and rationale. A model may propose the
assessment; an operator must disposition it before it affects governed state.

### 5.3 `operator_attestation`

The criterion cannot be inferred. It supplies a concrete operator question and
requires an explicit answer plus rationale.

Untyped free text cannot satisfy a validator gate or receive `verified` status.
`unknown` is a valid value and remains visible.

## 6. Override Modes and Ordering

Each configurable field declares one override mode:

- `locked`: any override is refused;
- `tighten_only`: an override must be strictly safer under a deterministic
  field-specific comparison; and
- `replaceable`: V0 permits replacement only for clarification budget and the
  unresolved-optional policy before session genesis.

Comparison uses the pinned
`nepsis.governance_comparator_policy@0.1.0` and its canonical hash. V0 defines
only these relations:

| Field | Safer direction |
|---|---|
| `maximum_tolerated_severity` | Lower integer is stricter. |
| `evidence_floor` | `operator_attestation < one_source < corroborated`. |
| `evidence_requirement` | `standard < elevated < strict`. |
| `reversibility_requirement` | `none < preferred < required`. |
| `loss_posture` | `balanced < downside_weighted < ruin_averse`. |
| `data_scope` | A named scope is stricter only when its allowed-data set is a proper subset. |
| constraint/ruin set | Adding a criterion is stricter; removal is a relaxation. |
| response | No global order; an explicit criterion-specific comparator is required. |

`proposal_mode`, `uncertainty_display`, and presentation preferences are
unordered and therefore `replaceable`, not `tighten_only`. Clarification budget
and unresolved-optional policy are also `replaceable`; their consequence is
shown rather than described as inherently safer. Any unlisted or incomparable
change is refused rather than guessed.

V0 session overrides are declared before genesis and contain:

- override ID and target path;
- operation and proposed value;
- rationale and consequence acknowledgement;
- operator identity and timestamp; and
- comparison result against the inherited value.

Outcomes are closed:

- a locked, constitutional, hard, or ruin relaxation or incomparable change is
  `refused`;
- an active-session change to an operator-owned replaceable default is
  `fork_required`;
- a valid pre-genesis replacement or deterministic tightening is `accepted`.

A fork may relax only an operator-owned, constitutionally replaceable default
through a new profile revision; constitutionally protected, hard, or ruin rules
remain locked. The fork displays the complete effective-policy diff, keeps the
prior run immutable, and requires elevated operator confirmation. A model
cannot approve or activate its own proposed relaxation.

## 7. Effective-Policy Derivation

Session creation deterministically:

1. validates schema and referenced versions/hashes;
2. loads the locked system constitution;
3. loads one active operator profile revision;
4. validates eligible pre-genesis overrides by override mode;
5. refuses relaxation or incomparable protected changes;
6. flattens the effective policy with source annotations per field;
7. canonicalizes and hashes the effective policy; and
8. pins constitution, profile, override, and effective-policy hashes in genesis.

Invalid configuration blocks session creation. It does not fall back to an
earlier profile or unconfigured defaults.

The effective snapshot records, for each field, whether it came from
`system_locked`, `operator_profile`, or `session_override`.

## 8. Authority and Audit

- Only an operator capability may create, activate, supersede, or revoke a
  profile revision.
- Profile registry requests carry expected profile-head revision, idempotency
  key, canonical intent hash, and operator rationale where required.
- Codex may submit a profile candidate into a separate review queue; it cannot
  modify a profile from the active decision thread.
- Profile review records the proposal artifact, origin thread/turn/model,
  exact diff, affected scope, rationale, and operator disposition.
- Profile changes do not mutate packet state.
- Session creation records the pinned profile and effective-policy hashes.
- Refused overrides and required forks produce truthful receipts.
- Raw hashes and receipts remain inspectable but are not the primary user
  interface.

## 9. User Interface Contract

The profile surface uses three explicit sections:

1. **System constitution** — locked and read-only.
2. **My defaults** — editable through versioned profile revision.
3. **This session** — effective snapshot and pre-genesis scoped overrides.

Every value is labeled `System locked`, `My default`, or `Session override`.
Before activation or fork, the UI shows current value, proposed value, effective
value, source, consequence, and affected sessions.

The main decision workspace keeps active frame constraints, RED hazards, STILL,
and ZeroBack status visible. They are not hidden under profile settings or
styled as tone/mood preferences.

Profile review leads with the human-readable claim and its effect. Technical
hashes, run IDs, and provenance live under audit disclosure.

## 10. Acceptance Tests

V0 must prove:

1. one active profile revision can seed a new session;
2. identical inputs derive byte-identical effective policy and hash;
3. constitution fields refuse all overrides;
4. a deterministic tightening is accepted and pinned;
5. a locked, protected, hard, or ruin relaxation/incomparable change is refused;
6. an active-session change to a replaceable operator default returns
   `fork_required`;
7. an active session is unaffected by a later profile revision or revocation;
8. every supported comparator and incomparable pair has a golden test;
9. concurrent activation and retry preserve one active revision and one outcome;
10. untyped free text cannot satisfy a gate;
11. operator attestation remains unanswered until an explicit operator action;
12. unknown plausible severe risk creates a hold;
13. severity 4 and one ruin criterion block BLUE regardless of utility;
14. a model-authored profile proposal cannot activate itself;
15. profile and session receipts survive export and detached verification; and
16. public `/mvp` output and behavior remain unchanged.

The smallest proof fixture contains one active profile, one valid tightening,
one refused relaxation, one required fork, and one ruin-triggered RED hold.

## 11. Deliberate V0 Non-Goals

- autonomous learning, promotion, or hidden cross-session memory;
- mid-session policy mutation;
- multi-user roles or organization policy hierarchy;
- a natural-language policy interpreter;
- arbitrary predicates, JSON Patch, inheritance, or a general policy DSL;
- probabilistic ruin calculation or an aggregate risk score;
- automatic relaxation from model confidence;
- profile-controlled tool or external-action authority;
- clinical, legal, or financial compliance certification;
- assistant tone, mood, persona, or style preferences; and
- remote policy synchronization or PKI.
