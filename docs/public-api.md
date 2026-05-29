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

Supported `case_id` values are `jailing` and `clinical`. Include optional
`input_text` to run a visitor query through the selected deterministic MVP
scaffold. The response is the frozen v0.3 `nepsis.mvp_packet` shape and is not a
live model response.

If the backend is not configured, the web UI shows a public-safe status message
and `POST /api/engine/mvp` serves bundled frozen v0.3 packets for the canonical
`jailing` and `clinical` cases. `/status` still reports the backend as
unconfigured so operators know the FastAPI service remains to be deployed.

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
stores.

To prove hosted Codex connectivity end to end, configure Codex with a
streamable-HTTP MCP server and run `scripts/mcp-hosted-verify.py`. See
[hosted-mcp-codex.md](hosted-mcp-codex.md).

## Public MVP Visual Topology Mode

The `/mvp` page may render a Visual Topology Mode for stakeholder review. This
is a browser-side view over the canonical `nepsis.mvp_packet` response.

Visual Topology Mode does not add public API fields, does not require login,
does not call provider models, and does not create runtime engine sessions. The
raw telemetry and JSON packet remain available from the same page through the
`Full View` result view.
