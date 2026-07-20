# V3 Packet Orchestration Kernel

V3 is a packet-native orchestration kernel for host-model-driven reasoning.
NepsisCGN does not run subagents, store hidden subagent memory, or create
server-side model output for this path. A host model drafts layer artifacts;
NepsisCGN validates, seals, gates, and finalizes only packet-visible state.

## Stateless Rollback Policy

V3 first pass uses pure stateless packet mode.

- HMAC detects tampering: if any sealed packet-visible field changes, the next
  transition rejects the packet.
- TTL detects expiration: packets older than `expires_at` reject on inspect or
  transition.
- HMAC does not detect rollback by itself. An older, previously valid packet can
  still fork the run until it expires.
- `abandon_v3_orchestration` emits an abandoned packet, but does not globally
  invalidate older active packets in pure stateless mode.

This is intentional for V3. A visible run-head ledger can be added later if
rollback prevention becomes necessary, but that would no longer be purely
packet-run-only.

## Seal Secret Requirement

V3 stateless packets require a stable HMAC seal secret. Set
`NEPSIS_V3_PACKET_SEAL_SECRET` for V3 packet use. If the deployment
intentionally shares the operator packet seal key, `NEPSIS_OPERATOR_PACKET_SEAL_SECRET`
is accepted as a fallback.

Do not rely on process-local development secrets for V3. A packet created in
one MCP or Python process must be inspectable by a later process using the same
configured secret; otherwise the packet is not a portable artifact.

## Layer Order

The fixed layer order is:

```text
intake -> red -> manifold -> blue -> still -> synthesis -> audit
```

Only the current layer may receive a proposal. A proposal never advances state.
A lock advances state only when the current proposal is valid and the user lock
assertion is bound to that exact proposal hash.

## Shared Layer Contract

Every layer artifact carries the same packet-visible contract fields:

- `goal_scope`
- `red_triggers`
- `blue_opportunity_space`
- `constraints`
- `manifold_match_mismatch`
- `still_blockers`
- `unresolved_questions`
- `audit_notes`
- `proposed_status`
- `lock_eligibility`

Each field must use one of these explicit states:

- `unknown`
- `none_found`
- `not_applicable`
- `present`

Each field also carries `items` and `rationale`. Empty arrays are allowed for
`unknown`, `none_found`, and `not_applicable`; `present` requires at least one
item. Silent empty arrays do not mean safe or complete.

## User Lock Binding

`lock_v3_layer` requires a lock assertion:

```json
{
  "asserted": true,
  "assertion_text": "I explicitly lock the red layer.",
  "proposal_hash": "sha256:...",
  "lock_nonce": "..."
}
```

The assertion locks a specific proposed artifact hash, not the layer in the
abstract. The packet stores the locked artifact, artifact hash, and assertion
hashes. It does not store raw capability tokens or provider credentials.

## Finalization

`finalize_v3_orchestration` requires every layer to be locked. The final
response packet is generated only from locked artifacts and includes:

- risk
- ruin
- win
- recommendations
- unresolved questions
- audit trace
- lineage hashes

BLUE wins cannot erase RED ruin. A recommendation with unresolved ruin blocks
finalization until the artifact is revised and locked again through a valid
packet branch.

The governing target is that RED ruin cannot erase the best-supported
explanation merely because its consequence is severe. Before V3 can be treated
as RED-authoritative, a future versioned RED artifact contract must follow the
[RED authority and anti-capture contract](red-authority-contract.md): keep
applicability falsifiable, scope blocked actions, expose safeguard burden, and
name a safe discriminator plus release or narrowing criteria. Repeated locking
of the same unresolved RED claim without evidence or scope change is a capture
signal, not additional confirmation.

The current V3 validator does not require those richer fields. It validates the
existing RED section (`triggers`, `ruin_paths`, `constraints`, and
`safety_blockers`) and the shared layer contract. Current proposal validation,
locking, and sealing therefore must not be described as full RED anti-capture
enforcement or typed action-scoped enforcement; the richer lifecycle remains an
adoption requirement.
