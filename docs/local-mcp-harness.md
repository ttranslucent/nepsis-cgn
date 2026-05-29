# Local MCP Harness

Use this when you want a model host you already pay for to call NepsisCGN
tools locally. The local harness starts the existing `nepsiscgn-mcp` stdio
entrypoint. NepsisCGN provides deterministic tools and stateless packet
transitions; the client owns model authentication and stores the returned
packet between calls.

`/mvp remains deterministic and model-free`. Do not wire `/mvp`,
`POST /v1/mvp`, or `POST /api/engine/mvp` to a provider model or a hosted key
flow. The MCP harness is a separate sidecar path for local or authenticated
operator clients.

## Prerequisites

From the repo root:

```bash
.venv/bin/python -m pip install -e '.[dev,api]'
test -x /Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp
```

If your checkout lives somewhere else, replace `/Users/trentthorn/Code/nepsiscgn`
in the snippets below with that absolute path.

## Codex / ChatGPT-Authenticated Codex

Codex CLI and the Codex IDE extension share `~/.codex/config.toml`. The
shortest reliable setup is:

```bash
codex mcp add nepsiscgn -- /Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp
```

Equivalent manual server entry:

```toml
[mcp_servers.nepsiscgn]
command = "/Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp"
args = []
cwd = "/Users/trentthorn/Code/nepsiscgn"
startup_timeout_sec = 10
tool_timeout_sec = 30
```

Then verify Codex sees it:

```bash
codex mcp list
.venv/bin/python scripts/mcp-local-verify.py --client codex --config ~/.codex/config.toml --server nepsiscgn
```

ChatGPT web does not run local stdio MCP servers. For ChatGPT developer mode,
use a hosted streaming HTTP or SSE MCP app/connector such as the backend `/mcp`
endpoint, not this local `nepsiscgn-mcp` process.

## Claude Code

Project-scoped install command:

```bash
claude mcp add --transport stdio --scope project nepsiscgn -- /Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp
```

Equivalent project `.mcp.json`:

```json
{
  "mcpServers": {
    "nepsiscgn": {
      "command": "/Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

Inside Claude Code, run:

```text
/mcp
```

## Gemini CLI

Add this to `~/.gemini/settings.json`, or to a project-local
`.gemini/settings.json` if you keep MCP config with the checkout:

```json
{
  "mcpServers": {
    "nepsiscgn": {
      "command": "/Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp",
      "args": [],
      "cwd": "/Users/trentthorn/Code/nepsiscgn",
      "timeout": 30000
    }
  }
}
```

Inside Gemini CLI, run:

```text
/mcp
```

## Verify From A Real Host Config

The verifier reads the same host config shape your client uses, launches the
configured stdio command, and makes MCP JSON-RPC calls through that process. It
does not call a provider model and does not create a backend session store.

Codex:

```bash
.venv/bin/python scripts/mcp-local-verify.py \
  --client codex \
  --config ~/.codex/config.toml \
  --server nepsiscgn
```

Claude Code project config:

```bash
.venv/bin/python scripts/mcp-local-verify.py \
  --client claude \
  --config .mcp.json \
  --server nepsiscgn
```

Gemini CLI:

```bash
.venv/bin/python scripts/mcp-local-verify.py \
  --client gemini \
  --config ~/.gemini/settings.json \
  --server nepsiscgn
```

A passing run proves:

- `initialize` and `tools/list` work from the configured stdio command.
- `run_mvp` returns a `nepsis.mvp_packet`.
- `health` reports `model_provider_keys_required=false`.
- The stateless operator flow can start, inspect, lock frame, run report, lock
  report, set threshold, and commit a `nepsis.operator_packet`.
- The packet lifecycle is packet-in/packet-out; the model host keeps the packet
  between calls.

Expected output includes:

```json
{
  "ok": true,
  "mvp": {
    "schema_id": "nepsis.mvp_packet",
    "model_free": true
  },
  "operator": {
    "started_schema_id": "nepsis.operator_packet",
    "last_commit_schema_id": "nepsis.operator_audit_packet"
  }
}
```

## Host Prompt Smoke

After the client reports the `nepsiscgn` MCP server as connected, use a direct
prompt like this:

```text
Use only the NepsisCGN MCP server named nepsiscgn. First call run_mvp with
{"case_id":"jailing"}. Then start an operator packet, inspect its legal next
tools, and stop. Do not use a provider model to modify /mvp output.
```
