# Public MVP v0.4 Triad Design

## Goal

Release a new deterministic public MVP packet set that reflects the current
NepsisCGN harness without turning `/mvp` into a live runtime, authenticated
operator path, or model-backed query surface.

Public MVP v0.4 presents three curated cases:

- `jailing`: JINGALL/JAILING toy proof of hard source-constraint preservation.
- `sea_ivdu`: revised spinal epidural abscess case showing medical RED
  preservation from a decisive risk feature.
- `wirecard`: financial authority-suppression case for unverifiable cash.

## Non-Negotiable Boundaries

- `/mvp`, `POST /v1/mvp`, and `POST /api/engine/mvp` remain public,
  deterministic, login-free, and model-free.
- Public v0.4 does not accept free-form benchmark cases.
- Private/operator benchmark cases remain in
  `data/private_demo_cases/authority_suppressed_red_channel.json` and
  `/private-demo`.
- Public medical language must not claim diagnosis, treatment advice, or
  autonomous clinical decision support.
- Public financial language must not claim investment, accounting, or legal
  advice.
- The public packet is a proof artifact. The packet, not model output, remains
  the object under test.

## Case Set

### JINGALL/JAILING

Purpose: demonstrate that RED preserves hard source constraints even when a
fluent candidate collapses to a plausible but wrong token.

Expected behavior:

- RED identifies `JINGALL` as the governed source token.
- BLUE may explain why `JAILING` is plausible, but cannot override the source
  constraint.
- STILL and audit events show RED-before-BLUE ordering.
- Final output rejects `JAILING` and preserves `JINGALL`.

### Revised SEA

Purpose: demonstrate that one decisive risk feature can prevent benign closure.

Public scenario:

> 40s male with non-radicular back pain and history of drug use disorder
> including intravenous use.

Expected behavior:

- RED keeps spinal epidural abscess active because intravenous use is a decisive
  risk feature.
- Lack of radicular pain, neurologic deficit, fever, labs, or imaging in the
  initial story does not close RED.
- Closure requires MRI-level evaluation or a definitive alternative explanation.
- Public copy says "MRI-level evaluation is required to close RED" rather than
  "the diagnosis is SEA" or "medical advice."

### Wirecard

Purpose: demonstrate authority suppression and unverifiable-cash governance in
a financial setting.

Expected behavior:

- RED identifies unverifiable cash as the governing hazard.
- Auditor language, market confidence, management assurance, and reported
  balances do not close RED.
- Closure requires independently verifiable bank/custodian evidence or a
  definitive alternative.
- Public copy frames the case as governance/audit proof, not financial advice.

## Packet Shape

The public packet should remain `schema_id: "nepsis.mvp_packet"` and bump
`schema_version` from the current `0.1.7` to `0.2.0`.

Each case should expose:

- `case_id`
- `case_label`
- `scenario`
- `red_channel`
- `blue_channel`
- `still_checkpoints`
- `audit_trace`
- `state_feedback`
- `final_output`
- `limitations`

The implementation may add a compact `public_release` or `release` block to
make the v0.4 posture explicit, as long as existing public topology and raw
packet views remain stable.

## UI Behavior

The public `/mvp` page should expose exactly the three public cases above in its
case selector.

The page copy should say:

- "Public MVP v0.4"
- "Deterministic packet proof"
- "Model-free deterministic run"
- "No login or API key required"

It should not say or imply:

- live model reasoning on `/mvp`
- clinical diagnosis
- medical recommendation
- financial advice
- private benchmark execution

## Fallback Packets

`nepsis-web/src/data/mvpPackets.json` must be regenerated from the canonical
Python packet builder after implementation. The bundled fallback should match
the backend packet builder for all three public cases.

## Testing

Tests must prove:

- `tests/test_mvp_packet.py` covers the v0.4 schema version and all three public
  case ids.
- The revised SEA case keeps RED open from intravenous-use risk even without
  fever, neurologic deficit, labs, or imaging.
- The Wirecard case keeps RED open until independent cash verification.
- The public web fallback packets match the canonical builder.
- The public `/mvp` Playwright flow can run all three cases without login or
  model keys.
- Public deployment artifact tests still reject model-assist or operator-model
  calls on `/mvp`.

## Out Of Scope

- Live model calls on `/mvp`.
- Free-form public medical or finance prompts.
- Publishing all private-demo benchmark cases.
- Router/ingress governance runtime implementation.
- Authenticated/private-demo UI changes.
- Changing `/private-demo`, operator packet runtime, or benchmark runner
  semantics except where tests need to confirm the boundary.
