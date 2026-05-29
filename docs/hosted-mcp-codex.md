# Hosted MCP Codex Verification

Use this to verify the hosted NepsisCGN `/mcp` endpoint from a Codex-compatible
streamable-HTTP MCP config. The hosted endpoint exposes public discovery but
requires a Nepsis capability token for every tool call.

`/mvp remains frozen, public, deterministic, and model-free`. Do not route
`/mvp`, `POST /v1/mvp`, or `POST /api/engine/mvp` through a provider model or a
capability-token flow.

## Backend Token Hash

Generate a strong Nepsis capability token outside the repo, then configure only
its SHA-256 hash on the hosted backend:

```bash
NEPSIS_MCP_CAPABILITY_TOKEN_HASHES=operator-1:<sha256-of-capability-token>
```

Do not store the raw capability token in source control. MCP clients send the
raw token as `Authorization: Bearer <token>` when calling tools.

## Codex Config

Add the hosted MCP server to Codex:

```bash
codex mcp add nepsiscgn-hosted --url https://<hosted-nepsis-api>/mcp --bearer-token-env-var NEPSIS_MCP_CAPABILITY_TOKEN
```

Equivalent wrapped form:

```bash
codex mcp add nepsiscgn-hosted \
  --url https://<hosted-nepsis-api>/mcp \
  --bearer-token-env-var NEPSIS_MCP_CAPABILITY_TOKEN
```

This writes a Codex config entry like:

```toml
[mcp_servers.nepsiscgn-hosted]
url = "https://<hosted-nepsis-api>/mcp"
bearer_token_env_var = "NEPSIS_MCP_CAPABILITY_TOKEN"
```

## Verify

Run the verifier with the same config Codex uses:

```bash
NEPSIS_MCP_CAPABILITY_TOKEN=<raw-capability-token> \
  .venv/bin/python scripts/mcp-hosted-verify.py \
  --client codex \
  --config ~/.codex/config.toml \
  --server nepsiscgn-hosted
```

A passing run proves:

- `initialize` works without a capability token.
- `tools/list` works without a capability token.
- Authenticated `tools/call` can run `start_operator_packet`.
- The returned payload is a `nepsis.operator_packet`.

Expected output includes:

```json
{
  "ok": true,
  "initialized": {
    "name": "nepsis-cgn"
  },
  "operator": {
    "started_schema_id": "nepsis.operator_packet"
  }
}
```
