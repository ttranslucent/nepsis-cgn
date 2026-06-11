# Codex Local MCP Demo

Use this as the smallest runnable Codex-mode demo for the OpenAI testing loop.
It proves the local setup, MCP handshake, and one concrete Nepsis tool flow from
this checkout without adding provider keys to NepsisCGN.

Boundary: `/mvp remains deterministic and model-free`. The local MCP server is
a sidecar tool path for Codex or another authenticated MCP host. ChatGPT web
does not run local stdio MCP servers.

## Copy-Paste Rehearsal

Terminal 1, from the repo root:

```bash
scripts/mvp-local.sh
```

Terminal 2, from the repo root:

```bash
NEPSIS_SITE_BASE_URL=http://127.0.0.1:3000 scripts/codex-mcp-demo.sh
```

The script checks `/api/status`, generates a temporary Codex-style stdio MCP
config for this checkout, then delegates the handshake and tool proof to:

```bash
scripts/mcp-local-verify.py --client codex --config "$CODEX_CONFIG" --server "$SERVER"
```

Expected proof:

- `/api/status` reports the frozen MVP as available and local MCP as stdio,
  with no model provider keys required.
- `initialize` and `tools/list` work through the configured stdio command.
- `health` reports `model_provider_keys_required=false`.
- `run_mvp` returns `nepsis.mvp_packet` for `case_id=jailing`.
- `start_operator_packet` begins a `nepsis.operator_packet`, and the verifier
  drives the stateless packet through `commit_iteration` to a
  `nepsis.operator_audit_packet`.

## Real Codex Config

To connect the installed local server to Codex CLI or the Codex IDE extension:

```bash
codex mcp add nepsiscgn -- /Users/trentthorn/Code/nepsiscgn/.venv/bin/nepsiscgn-mcp
codex mcp list
NEPSIS_SITE_BASE_URL=http://127.0.0.1:3000 NEPSIS_CODEX_CONFIG=~/.codex/config.toml scripts/codex-mcp-demo.sh
```

Use the temporary-config rehearsal first when you only need to prove this
checkout. Use `NEPSIS_CODEX_CONFIG=~/.codex/config.toml` when the object under
test is the real Codex host config.

## Host Prompt Smoke

After Codex reports the `nepsiscgn` MCP server as connected, use this prompt:

```text
Use only the NepsisCGN MCP server named nepsiscgn. First call run_mvp with
{"case_id":"jailing"}. Then start_operator_packet, inspect legal next tools,
and stop. Do not use a provider model to modify /mvp output.
```

This prompt intentionally stops after one deterministic MVP call and the first
operator packet transition. It is a harness proof, not a public `/mvp` redesign
and not a clinical workflow.
