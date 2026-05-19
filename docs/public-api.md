# Public API Notes

The public website exposes only the deterministic MVP path to anonymous
visitors. Operator session APIs and model routes stay behind deployment auth.

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

## MCP Endpoint

The backend HTTP MCP endpoint is:

```http
POST /mcp
Content-Type: application/json
```

Public tools:

- `run_mvp`
- `get_mvp_schema`
- `health`

Protected tools:

- `get_routes` when backend auth is enabled

MCP clients should authenticate to their own model provider separately. NepsisCGN
does not proxy visitor OpenAI, Claude, or Gemini accounts through the public web
site.
