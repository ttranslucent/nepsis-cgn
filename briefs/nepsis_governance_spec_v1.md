# Nepsis Governance Spec v1 (Draft)

Date: 2026-02-28  
Status: Draft for implementation freeze  
Applies to: `nepsis_cgn` runtime sidecar and UI loop

## 1) Purpose

Nepsis governs reasoning under asymmetric loss by keeping two mandates separate:

- Blue mandate: maximize coherence and expected utility under modeled conditions.
- Red mandate: minimize catastrophic regret under uncertainty.

Nepsis is advisory-first in v1: warnings can block by default in UI, but users may continue with explicit override rationale.

## 2) Core Objects

### 2.1 FrameVersion (first-class, mutable)

Each iteration references one explicit frame version:

- `frame_id`, `frame_version`
- `text`, `objective_type`, `domain`, `time_horizon`
- `constraints_hard[]`, `constraints_soft[]`
- `priors[]`
- `costs` (`c_fp`, `c_fn`, optional `c_delay`)
- `rationale_for_change`

### 2.2 IterationPacket (runtime)

Single packet emitted per loop:

- `meta`: ids, lineage, timestamps, policy versions
- `priors_window`: frame + setup state
- `test_window`: call outputs + report edits + contradiction flags
- `posterior_window`: weights, metrics, recommendation
- `governance`: warning, triggers, user decision, overrides
- `carry_forward`: explicit persistence policy for next iteration

### 2.3 CanonicalRecord (audit)

Append-only archive artifact containing:

- final runtime packet snapshot
- replayable events
- invariant evaluations
- model/tool call hashes and references

## 3) State Machine

Lifecycle for one iteration:

1. `draft`
2. `called`
3. `reported`
4. `evaluated`
5. `committed`

Auxiliary postures:

- `mixture_mode`
- `collapse_mode`
- `red_override`
- `zeroback`

Transition rules:

- `CALL` moves `draft -> called` only from Priors window.
- `REPORT` moves `called -> reported` only from Test window.
- `EVALUATE` moves `reported -> evaluated` only from Posterior window.
- `COMMIT` moves `evaluated -> committed` when governance checks resolve.
- `ABDUCT` creates new `FrameVersion` and opens next iteration `draft`.
- `RESET_PRIORS` creates next iteration with carry-forward policy.

## 4) Mandatory Metrics

For each evaluate step:

- `contradiction_density` in `[0,1]`
- `posterior_entropy_norm` in `[0,1]`
- `top_margin = p1 - p2`
- `ruin_mass = sum(p_i for i in ruin_set)`
- `aux_assumption_load`
- `zeroback_count`
- `filter_ess` (if particle filter mode enabled)
- `hotspot_score` (if geometry module enabled)

Normalized entropy:

`H_norm = (-sum_i p_i * ln(p_i)) / ln(K)` for `K` active hypotheses.

## 5) Decision Math

### 5.1 Cost gate

`theta = c_fp / (c_fp + c_fn)`

Act/protect when:

`p_bad >= theta`

Expected losses:

- `loss_treat = (1 - p_bad) * c_fp`
- `loss_notreat = p_bad * c_fn`

### 5.2 Probability pipeline

Nepsis computes calibrated risk:

1. Construct feature score `s_t` from geometry + contradiction + consistency features.
2. Compute raw risk `p_raw = sigmoid(a + b * s_t)` or LR-based posterior.
3. Calibrate to `p_cal` (Platt or isotonic).
4. Temporal smoothing to `p_t` (EMA or 2-state filter).

`p_t` is the value used for governance gating.

### 5.3 Red/Blue separation

Do not merge into one scalar objective:

- Blue policy selects utility/coherence actions.
- Red policy gates catastrophic exposure.
- Arbitration combines policies into final recommendation and warning level.

## 6) Governance Postures

Advisory posture in v1:

- `green`: safe to continue.
- `yellow`: warning; recommend reframe/test.
- `red`: strong warning; recommend stop/reframe.

User controls in yellow/red:

1. `Stop and Reframe` (recommended)
2. `Continue Anyway` (requires `override_reason`)

Required governance fields:

- `mode` (`advisory`)
- `warning_level` (`green|yellow|red`)
- `trigger_codes[]`
- `recommended_action`
- `user_decision` (`stop|continue_override`)
- `override_reason` (nullable string)

## 7) Policy Table (v1 Defaults)

All thresholds are policy-configurable and versioned.

| Condition | Posture | Action |
|---|---|---|
| `ruin_mass >= tau_red` OR `p_t >= theta` | `red_override` | protect/escalate, defer collapse |
| `top_margin < eps_margin` AND `H_norm > h_high` | `mixture_mode` | maintain plurality, choose discriminator |
| `contradiction_density > c_high` for `N` iterations | `mixture_mode` | abduct/reframe, tighten or relax constraints |
| `p1 >= tau_collapse` AND `top_margin >= eps_collapse` AND `contradiction_density <= c_ok` for `N_stable` | `collapse_mode` | collapse to leading hypothesis |
| `mixture_mode` persists `> max_dwell_iters` | `anti_stall` | force discriminator action or safest policy |
| `zeroback_count > zeroback_limit` OR incoherent particle set | `zeroback` | reset priors via carry-forward policy |

## 8) “Why Not Converging” Codes

Nepsis must always emit machine and human-readable reasons:

- `CONSTRAINT_CONFLICT`
- `HIGH_ENTROPY_NO_DISCRIMINATOR`
- `AUX_LOAD_ACCUMULATION`
- `MARGIN_COLLAPSE`
- `HOTSPOT_APPROACH`
- `RECURRENCE_PATTERN`
- `DATA_QUALITY_GAP`

Each code includes:

- `evidence`
- `affected_ids[]`
- `recommended_next_test`

## 9) Carry-Forward Policy (Reset without amnesia)

Reset is policy-driven, not wipe-all:

- facts/observations: `keep|decay|drop`
- contradictions: `keep|drop`
- priors: `keep|decay|reset`
- failed hypotheses: archive as negative evidence
- discriminators/tests: `keep|drop`
- constraints:
  - hard: `keep|drop`
  - soft: `keep|relax|drop`

Default v1 reset:

- keep facts + contradictions + discriminators
- reset or decay priors
- preserve hard constraints
- relax soft constraints one step

## 10) Exposure-Weighted Auditing

Track cumulative governance exposure:

- `irreversible_decision_count`
- `accepted_uncertainty_mass`
- `coupling_density`
- `time_to_detection_latency`

Rolling audits (windowed):

- false negatives (missed red interventions)
- false positives (unnecessary friction)
- calibration drift (`Brier`, `ECE`)

Threshold updates:

- monotone, capped delta per update
- evidence-gated (no single-incident changes)
- versioned in `policy_version`

## 11) Geometry and Hotspot Hooks (Optional v1, active v1.1+)

Hotspot object schema:

- `hotspot_id`
- `centroid`
- `covariance`
- `tau_membership`
- `empirical_risk`
- `registry_version`
- `provenance`

Runtime checks:

- hotspot distance / membership
- approach velocity
- margin collapse rate
- trajectory instability

Emit event codes:

- `HOTSPOT_APPROACH`
- `HOTSPOT_ENTRY`
- `MARGIN_COLLAPSE`
- `TRAJECTORY_INSTABILITY`

## 12) Packet Contract (Reference JSON shape)

```json
{
  "meta": {
    "packet_id": "...",
    "session_id": "...",
    "iteration": 0,
    "parent_packet_id": null,
    "frame_lineage_id": "...",
    "policy_version": "gov-v1.0.0",
    "calibration_version": "cal-v1.0.0",
    "registry_version": "hotspot-v1.0.0"
  },
  "frame_version": {
    "frame_id": "...",
    "frame_version": 1,
    "text": "...",
    "objective_type": "decide",
    "constraints_hard": [],
    "constraints_soft": [],
    "costs": { "c_fp": 1.0, "c_fn": 10.0 }
  },
  "metrics": {
    "p_bad": 0.22,
    "theta": 0.09,
    "contradiction_density": 0.31,
    "posterior_entropy_norm": 0.64,
    "top_margin": 0.05,
    "ruin_mass": 0.28,
    "aux_assumption_load": 1.8,
    "filter_ess": 42
  },
  "governance": {
    "mode": "advisory",
    "warning_level": "red",
    "trigger_codes": ["MARGIN_COLLAPSE", "HIGH_ENTROPY_NO_DISCRIMINATOR"],
    "recommended_action": "abduct",
    "user_decision": "continue_override",
    "override_reason": "Need one more discriminator before reframe."
  },
  "carry_forward": {
    "facts": "keep",
    "contradictions": "keep",
    "priors": "decay",
    "constraints": { "hard": "keep", "soft": "relax" },
    "tests": "keep"
  }
}
```

## 13) Implementation Checklist

### v1 required

- three-window workflow with stage isolation
- explicit promote/commit actions
- state machine enforcement
- deterministic policy table evaluation
- advisory warnings with override reason capture
- frame timeline (`v1 -> v2 -> v3...`) with rationale diffs
- runtime and canonical packet outputs

### v1.1 recommended

- hotspot registry + trajectory features
- calibrated hotspot risk integration
- anti-stall discriminator optimizer
- exposure-weighted governance dashboards

## 14) Non-Negotiable Invariants

- Red can pre-empt Blue; Blue cannot suppress Red.
- No collapse when mixture-mode triggers are active unless explicit override is logged.
- Every recommendation must be reproducible from packet state + policy/calibration versions.
- Every override must include rationale and actor.
- Reset never deletes canonical history.
