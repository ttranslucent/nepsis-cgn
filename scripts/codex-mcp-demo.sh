#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${NEPSIS_PYTHON:-$ROOT_DIR/.venv/bin/python}"
SERVER="${NEPSIS_MCP_SERVER:-nepsiscgn}"
SITE_BASE_URL="${NEPSIS_SITE_BASE_URL:-}"
CODEX_CONFIG="${NEPSIS_CODEX_CONFIG:-}"
TMP_DIR=""
PROOF_PATH=""

section() {
  printf '\n== %s ==\n' "$1"
}

fail() {
  printf 'codex-mcp-demo: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  elif [[ -n "$PROOF_PATH" && -f "$PROOF_PATH" ]]; then
    rm -f "$PROOF_PATH"
  fi
}

trap cleanup EXIT

if [[ ! -x "$PYTHON" ]]; then
  cat >&2 <<EOF
codex-mcp-demo: missing Python interpreter: $PYTHON

Run from the repo root:
  python3.11 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e '.[dev,api]'
EOF
  exit 1
fi

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

section "Checkout"
BRANCH="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
COMMIT="$(git -C "$ROOT_DIR" rev-parse --short HEAD 2>/dev/null || true)"
printf 'repo:   %s\n' "$ROOT_DIR"
printf 'branch: %s\n' "${BRANCH:-unknown}"
printf 'commit: %s\n' "${COMMIT:-unknown}"
if [[ "${BRANCH:-}" != "main" ]]; then
  printf 'warning: next-week demo rehearsal should run from main.\n' >&2
fi

section "Setup"
"$PYTHON" -c 'import nepsis_cgn.core.mvp, nepsis_cgn.mcp.stdio'
printf 'python import ok: nepsis_cgn.core.mvp, nepsis_cgn.mcp.stdio\n'

if [[ -n "$SITE_BASE_URL" ]]; then
  section "/api/status"
  "$PYTHON" - "$SITE_BASE_URL" <<'PY'
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
url = f"{base}/api/status"

try:
    with urllib.request.urlopen(url, timeout=10) as response:
        status = response.status
        payload = json.loads(response.read().decode("utf-8"))
except Exception as exc:
    raise SystemExit(f"/api/status check failed at {url}: {exc}") from exc

if status != 200:
    raise SystemExit(f"/api/status returned HTTP {status}")
if not isinstance(payload, dict):
    raise SystemExit("/api/status did not return a JSON object")

mvp = payload.get("mvp") if isinstance(payload.get("mvp"), dict) else {}
mcp = payload.get("mcp") if isinstance(payload.get("mcp"), dict) else {}
local = mcp.get("local") if isinstance(mcp.get("local"), dict) else {}
protected_tools = set(mcp.get("protectedTools") or [])

if mvp.get("available") is not True:
    raise SystemExit("/api/status did not report the frozen MVP as available")
if mvp.get("noLoginRequired") is not True:
    raise SystemExit("/api/status did not report no-login MVP access")
if local.get("available") is not True or local.get("transport") != "stdio":
    raise SystemExit("/api/status did not report local stdio MCP availability")
if local.get("modelKeysRequired") is not False:
    raise SystemExit("/api/status reported model keys required for local MCP")
missing = {"run_mvp", "start_operator_packet"} - protected_tools
if missing:
    raise SystemExit(f"/api/status missing protected MCP tools: {sorted(missing)}")

print(
    "/api/status ok: "
    f"mvp.available={mvp.get('available')} "
    f"mcp.local.transport={local.get('transport')} "
    "protectedTools include run_mvp,start_operator_packet"
)
PY
else
  printf 'skipped /api/status; set NEPSIS_SITE_BASE_URL=http://127.0.0.1:3000 after starting scripts/mvp-local.sh\n'
fi

section "Codex MCP config"
if [[ -z "$CODEX_CONFIG" ]]; then
  TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/nepsis-codex-mcp-demo.XXXXXX")"
  CODEX_CONFIG="$TMP_DIR/codex-config.toml"
  PROOF_PATH="$TMP_DIR/proof.json"
  cat > "$CODEX_CONFIG" <<EOF
[mcp_servers.$SERVER]
command = "$PYTHON"
args = ["-m", "nepsis_cgn.mcp.stdio"]
cwd = "$ROOT_DIR"
startup_timeout_sec = 10
tool_timeout_sec = 30

[mcp_servers.$SERVER.env]
PYTHONPATH = "$ROOT_DIR/src"
NEPSIS_API_STORE_PATH = "$TMP_DIR/mcp-sessions.json"
EOF
  printf 'generated temporary Codex stdio config: %s\n' "$CODEX_CONFIG"
else
  CODEX_CONFIG="${CODEX_CONFIG/#\~/$HOME}"
  [[ -f "$CODEX_CONFIG" ]] || fail "Codex config not found: $CODEX_CONFIG"
  PROOF_PATH="$(mktemp "${TMPDIR:-/tmp}/nepsis-codex-mcp-proof.XXXXXX.json")"
  printf 'using Codex config: %s\n' "$CODEX_CONFIG"
fi

section "Handshake and tool flow"
"$PYTHON" "$ROOT_DIR/scripts/mcp-local-verify.py" \
  --client codex \
  --config "$CODEX_CONFIG" \
  --server "$SERVER" | tee "$PROOF_PATH"

section "Concrete flow summary"
"$PYTHON" - "$PROOF_PATH" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    proof = json.load(handle)

if proof.get("ok") is not True:
    raise SystemExit("MCP proof did not return ok=true")

mvp = proof.get("mvp", {})
operator = proof.get("operator", {})
events = operator.get("phase_events", [])
required_events = [
    "LOCK_FRAME",
    "RUN_REPORT",
    "LOCK_REPORT",
    "SET_THRESHOLD_DECISION",
    "COMMIT_ITERATION",
]
if mvp.get("schema_id") != "nepsis.mvp_packet" or mvp.get("case_id") != "jailing":
    raise SystemExit("run_mvp proof did not return the jailing MVP packet")
if operator.get("started_schema_id") != "nepsis.operator_packet":
    raise SystemExit("start_operator_packet proof did not return nepsis.operator_packet")
if operator.get("last_commit_schema_id") != "nepsis.operator_audit_packet":
    raise SystemExit("operator commit proof did not return nepsis.operator_audit_packet")
if events != required_events:
    raise SystemExit(f"operator phase events changed: {events}")

print("run_mvp: nepsis.mvp_packet case_id=jailing model_free=true")
print("start_operator_packet -> commit_iteration: nepsis.operator_audit_packet")
print("phase_events: " + ",".join(events))
PY

section "Codex host prompt"
cat <<'EOF'
Use only the NepsisCGN MCP server named nepsiscgn. First call run_mvp with
{"case_id":"jailing"}. Then start_operator_packet, inspect legal next tools,
and stop. Do not use a provider model to modify /mvp output.
EOF
