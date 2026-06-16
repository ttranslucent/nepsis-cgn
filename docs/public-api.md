# Public API Notes

The public website exposes only the deterministic MVP path to anonymous
visitors. Operator session APIs and model routes stay behind deployment auth.

## Public site setup

Use `nepsis-web/.env.public.example` for the frozen public `/mvp` deployment.
The public template belongs to the deterministic demo path: it enables
`NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true`, keeps `/operator` disabled, keeps
`NEPSIS_MODEL_ROUTES_ENABLED=false`, leaves provider keys unset, and disables
local-only preview codes and anonymous engine controls.

Do not mix in variables from `nepsis-web/.env.operator.example` on the public
site. Private operator deployments use a separate environment with real login
and live model routes; see [operator-runbook.md](operator-runbook.md#private-operator-deployment).

## Web Proxy

Use the Vercel web proxy for public-safe MVP runs:

```http
POST /api/engine/mvp
Content-Type: application/json

{"case_id":"jailing"}
```

Supported `case_id` values are `jailing` and `clinical`. The public page runs
those fixed cases without a visitor query box. Direct proxy callers may include
optional `input_text` for deterministic packet-builder compatibility; the
response is the frozen v0.3 `nepsis.mvp_packet` shape and is not a live model
response.

If the backend is not configured, the web UI shows a public-safe status message
and `POST /api/engine/mvp` serves bundled frozen v0.3 packets for the canonical
`jailing` and `clinical` cases. The fallback packet includes
`fallback_source` and `fallback_reason`; `backend_unconfigured` means the public
site is intentionally using the bundled deterministic packet because
`NEPSIS_API_BASE_URL` is absent, not because a model or hidden engine path ran
silently. `/status` still reports the backend as unconfigured so operators know
the FastAPI service remains to be deployed.

## MVP Packet Semantics

The v0.1.7 MVP packet keeps legacy hypothesis `likelihood` fields for
compatibility, but those values are support-only. RED/threshold standing lives
in `post_constraint_standing` and `action_priority`, while `evaluation_axes`
keeps support separate from action priority.

STILL commitment readiness keeps the compatibility `status` field and adds
explicit `zeroback_triggered`, `effective_action`, and `co_trigger_statuses`
fields so ZeroBack is visible even when legacy readiness remains
`retessellate`.

`contradiction_monitor.contradiction_density` is a demo-only scalar summary.
Use `density_channels` and each contradiction's `level` and `status` when
inspecting whether object-level, meta-level, or action-threshold contradictions
are open or resolved inside the packet.

The Jailing/Jingall case is a hard RED demo. It assumes `JINGALL` is the
authoritative source token, shows rejection of the fluent `JAILING`
normalization, and records source-token verification as a next-cycle
obligation. It does not demonstrate detection of the harder variant where the
source token itself is corrupted and `JAILING` is true.

## Direct FastAPI

Direct backend access is for operators and trusted web proxies:

```http
POST /v1/mvp
Authorization: Bearer <NEPSIS_API_TOKEN>
Content-Type: application/json

{"case_id":"jailing"}
```

Do not open the broader `/v1/sessions/*` API publicly unless auth, ownership,
storage, and rate limits have been reviewed for that deployment.

## Live Operator Path

The product-facing live path is `/operator`, not `/mvp`. It reuses the existing
engine session runtime and remains signed-in. Hosted live model assistance is
private and disabled by default; if a separate operator deployment enables
routes such as `POST /api/operator/model`, model output is advisory draft input
for operator review, not a commitment or packet substitute.

Public demo deployments should keep `/operator` gated and model routes disabled.
Private operator deployments must configure backend auth, exact-email OTP
allowlisting, login email delivery, rate limits, token caps, and server-side
model credentials before enabling live model routes.

## MCP Endpoint

The backend HTTP MCP endpoint is:

```http
POST /mcp
Content-Type: application/json
```

Unauthenticated discovery methods:

- `initialize`
- `tools/list`

Hosted tool calls require a Nepsis capability token:

```http
Authorization: Bearer <nepsis-capability-token>
```

or:

```http
X-Nepsis-Capability-Token: <nepsis-capability-token>
```

Configure tokens as hashes only:

```bash
NEPSIS_MCP_CAPABILITY_TOKEN_HASHES=operator-1:<sha256-of-capability-token>
```

Protected tools:

- `run_mvp`
- `get_mvp_schema`
- `health`
- `get_routes`
- `start_operator_packet`
- `get_session_state`
- `lock_frame`
- `run_report`
- `lock_report`
- `set_threshold_decision`
- `commit_iteration`
- `abandon_packet`

`start_operator_packet` creates a `nepsis.operator_packet` v2 object. Each
operator transition receives the current packet and returns the next packet.
Out-of-order calls return `nepsis.phase_rejection`; `commit_iteration` requires
the packet trace to prove the prior frame, report, lock, and threshold gates.

Remote MCP logs should record request id, token id, tool, status, latency, and a
packet hash only. Packet bodies, prompts, and provider keys are not logged by
default.

MCP clients should authenticate to their own model provider separately. NepsisCGN
does not proxy visitor OpenAI, Claude, or Gemini accounts through the public web
site, and stateless MCP tools do not create backend session files or packet
stores. Future Supabase invites should approve who can log in to private
operator surfaces; they should not store raw model-provider API keys.

To prove hosted Codex connectivity end to end, configure Codex with a
streamable-HTTP MCP server and run `scripts/mcp-hosted-verify.py`. See
[hosted-mcp-codex.md](hosted-mcp-codex.md).

## Public MVP Provenance Views

The `/mvp` page may render provenance-oriented topology, audit, and lineage
views for stakeholder review. These are browser-side views over the canonical
`nepsis.mvp_packet` response.

The provenance views do not add public API fields, do not require login, do not
call provider models, and do not create runtime engine sessions. The raw
telemetry and JSON packet remain available from the same page through the
`Audit` result view.
