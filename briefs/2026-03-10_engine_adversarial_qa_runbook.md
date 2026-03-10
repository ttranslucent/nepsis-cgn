# Engine Adversarial QA Runbook (2026-03-10)

## Goal

Run repeatable adversarial checks in `/engine` and compare UI gate behavior against canonical expected outcomes.

## Canonical Expected Output

Generated from:

`PYTHONPATH=src .venv/bin/python scripts/engine_adversarial_gate_snapshot.py`

Snapshot file:

`briefs/2026-03-10_engine_adversarial_gate_expected.json`

Canonical stage outcomes:

- `S1-vague-frame`: `frame=BLOCK`, `interpretation=BLOCK`, `threshold=BLOCK`
- `S2-contradiction-heavy`: `frame=PASS`, `interpretation=WARN`, `threshold=PASS`
- `S3-red-override-conflict`: `frame=PASS`, `interpretation=PASS`, `threshold=BLOCK`

## Environment

1. Start backend API:

```bash
NEPSIS_API_ALLOW_ANON=true PYTHONPATH=src .venv/bin/python -m nepsis_cgn.api.server --host 127.0.0.1 --port 8787
```

2. Start web app:

```bash
cd nepsis-web
NEPSIS_ENGINE_ALLOW_ANON=true npm run dev
```

3. Open:

`http://localhost:3000/engine`

4. Enable `DevTools` and `System Status` in the page header so gate statuses are visible.

## Scenario Script

### S1: Vague Frame (Underdefined Priors)

1. Click `New Workspace`.
2. In Frame stage set only:
   - Problem statement text: `Help?`
3. Leave catastrophic outcome, optimization goal, horizon, key uncertainty, and constraints empty.
4. Click `Lock Frame`.

Expected gate outcomes:

- `frame=BLOCK`
- `interpretation=BLOCK`
- `threshold=BLOCK`
- Frame check expectations:
  - `problem_statement=pass`
  - `catastrophic_outcome=block`
  - `optimization_goal=block`
  - `decision_horizon=block`
  - `key_uncertainty=block`
  - `constraint_structure=block`

### S2: Contradiction-Heavy Report

1. Complete Frame fields and lock frame.
2. In Interpretation stage input contradictory evidence lines:
   - `obs: signal strongly indicates escalation`
   - `obs: signal likely false positive`
   - `obs: team reports conflicting timelines`
3. Set contradiction status to `declared` and provide contradiction note.
4. Run `CALL + REPORT`.
5. In Threshold stage set:
   - Decision: `hold`
   - Hold rationale: `Gather one additional discriminator.`

Expected gate outcomes:

- `frame=PASS`
- `interpretation=WARN` (driven by high contradiction density)
- `threshold=PASS` (with explicit hold decision + rationale)
- Interpretation check expectations:
  - `contradictions_declared=pass`
  - `contradiction_density=warn`

### S3: Forced Red-Override Conflict

1. Complete Frame fields and lock frame.
2. In Interpretation stage include explicit risk tags and run evaluation:
   - `critical_signal: true`
   - `policy_violation: true`
3. In Threshold stage set:
   - Decision: `recommend`
   - Hold rationale: blank

Expected gate outcomes:

- `frame=PASS`
- `interpretation=PASS`
- `threshold=BLOCK`
- Threshold check expectations:
  - `decision_declared=pass`
  - `red_override_enforced=block`

Resolution check:

- Change decision to `hold` and add hold rationale.
- Expected: red-override block clears if other checks are satisfied.

## QA Log Template

- Date:
- Tester:
- Build/Commit:
- S1 observed gate statuses:
- S2 observed gate statuses:
- S3 observed gate statuses:
- Divergences from canonical expectations:
- Follow-up issues filed:
