#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$ROOT_DIR/nepsis-web"
PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
BACKEND_BIN="$ROOT_DIR/.venv/bin/nepsiscgn-api-asgi"
NEXT_BIN="$WEB_DIR/node_modules/.bin/next"

BACKEND_PID=""
WEB_PID=""
SHUTTING_DOWN=0

fail() {
  printf 'operator-local: %s\n' "$*" >&2
  exit 1
}

check_dependencies() {
  if [[ ! -x "$BACKEND_BIN" ]]; then
    cat >&2 <<EOF
operator-local: missing backend entrypoint: .venv/bin/nepsiscgn-api-asgi

Run from the repo root:
  python3.11 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e '.[dev,api]'
EOF
    exit 1
  fi

  if [[ ! -x "$NEXT_BIN" ]]; then
    cat >&2 <<EOF
operator-local: missing Next dependency: nepsis-web/node_modules/.bin/next

Run from the repo root:
  cd nepsis-web && npm ci
EOF
    exit 1
  fi

  command -v npm >/dev/null 2>&1 || fail "npm is required to start nepsis-web."
}

local_secret() {
  "$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(32))'
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM

  if [[ "$SHUTTING_DOWN" == "0" ]]; then
    SHUTTING_DOWN=1
  fi

  if [[ -n "${WEB_PID:-}" ]] && kill -0 "$WEB_PID" 2>/dev/null; then
    printf 'Stopping web (pid %s)...\n' "$WEB_PID"
    terminate_tree "$WEB_PID"
  fi

  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    printf 'Stopping backend (pid %s)...\n' "$BACKEND_PID"
    terminate_tree "$BACKEND_PID"
  fi

  if [[ -n "${WEB_PID:-}" ]]; then
    wait "$WEB_PID" 2>/dev/null || true
  fi
  if [[ -n "${BACKEND_PID:-}" ]]; then
    wait "$BACKEND_PID" 2>/dev/null || true
  fi

  return "$status"
}

terminate_tree() {
  local pid="$1"
  local child

  while IFS= read -r child; do
    if [[ -n "$child" ]]; then
      terminate_tree "$child"
    fi
  done < <(pgrep -P "$pid" 2>/dev/null || true)

  kill "$pid" 2>/dev/null || true
}

on_signal() {
  local signal="$1"
  printf '\nReceived %s; shutting down local operator demo.\n' "$signal"
  if [[ "$signal" == "TERM" ]]; then
    exit 143
  fi
  exit 130
}

process_exit_status() {
  local pid="$1"
  local status=0
  set +e
  wait "$pid"
  status=$?
  set -e
  printf '%s' "$status"
}

monitor_processes() {
  while true; do
    if [[ -n "$BACKEND_PID" ]] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      local backend_status
      backend_status="$(process_exit_status "$BACKEND_PID")"
      printf 'Backend exited with status %s; shutting down local operator demo.\n' "$backend_status"
      exit "$backend_status"
    fi

    if [[ -n "$WEB_PID" ]] && ! kill -0 "$WEB_PID" 2>/dev/null; then
      local web_status
      web_status="$(process_exit_status "$WEB_PID")"
      printf 'Web exited with status %s; shutting down local operator demo.\n' "$web_status"
      exit "$web_status"
    fi

    sleep 1
  done
}

check_dependencies

LOCAL_API_TOKEN="${NEPSIS_API_TOKEN:-$(local_secret)}"
LOCAL_AUTH_SECRET="${NEPSIS_AUTH_SECRET:-$(local_secret)}"
LOCAL_PACKET_SEAL_SECRET="${NEPSIS_OPERATOR_PACKET_SEAL_SECRET:-$(local_secret)}"
LOCAL_PROPOSAL_RECEIPT_SECRET="${NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET:-$(local_secret)}"
LOCAL_ALLOWED_EMAILS="${NEPSIS_AUTH_ALLOWED_EMAILS:-operator@local.test}"

trap cleanup EXIT
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM

printf 'Starting NepsisCGN local private operator demo from %s\n' "$ROOT_DIR"
printf 'Backend: http://127.0.0.1:8787\n'
printf 'Web:     http://127.0.0.1:3000/operator\n'
printf 'Status:  http://127.0.0.1:3000/status\n'
printf 'Login:   use an allowlisted email; default is operator@local.test. The local preview code appears on /login.\n'
if [[ -z "${OPENAI_API_KEY:-}${NEPSIS_OPENAI_API_KEY:-}" ]]; then
  printf 'Model:   no server-side OPENAI_API_KEY/NEPSIS_OPENAI_API_KEY is set; model assist will report "Server model key required".\n'
else
  printf 'Model:   server-side OpenAI key detected in the shell environment.\n'
fi
printf 'Ctrl-C stops backend and web.\n'

(
  cd "$ROOT_DIR"
  exec env NEPSIS_API_HOST=127.0.0.1 \
    NEPSIS_API_PORT=8787 \
    NEPSIS_API_ALLOW_ANON=false \
    NEPSIS_API_TOKEN="$LOCAL_API_TOKEN" \
    NEPSIS_API_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000 \
    NEPSIS_OPERATOR_PACKET_SEAL_SECRET="$LOCAL_PACKET_SEAL_SECRET" \
    "$BACKEND_BIN"
) &
BACKEND_PID=$!
printf 'Started backend (pid %s).\n' "$BACKEND_PID"

(
  cd "$WEB_DIR"
  exec env NEPSIS_API_BASE_URL=http://127.0.0.1:8787 \
    NEPSIS_API_TOKEN="$LOCAL_API_TOKEN" \
    NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=false \
    NEPSIS_DEPLOYMENT_MODE= \
    NEXT_PUBLIC_NEPSIS_OPERATOR_SITE=false \
    NEPSIS_LIVE_OPERATOR_ENABLED=true \
    NEPSIS_ENGINE_ALLOW_ANON=false \
    NEPSIS_AUTH_SECRET="$LOCAL_AUTH_SECRET" \
    NEPSIS_AUTH_ALLOWED_EMAILS="$LOCAL_ALLOWED_EMAILS" \
    NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true \
    RESEND_API_KEY= \
    NEPSIS_AUTH_FROM_EMAIL= \
    NEPSIS_MODEL_ROUTES_ENABLED=true \
    NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET="$LOCAL_PROPOSAL_RECEIPT_SECRET" \
    OPENAI_MODEL="${OPENAI_MODEL:-gpt-4.1-mini}" \
    OPENAI_API_URL="${OPENAI_API_URL:-https://api.openai.com/v1/responses}" \
    OPENAI_API_KEY="${OPENAI_API_KEY:-}" \
    NEPSIS_OPENAI_API_KEY="${NEPSIS_OPENAI_API_KEY:-}" \
    NEXT_TELEMETRY_DISABLED=1 \
    npm run dev -- --hostname 127.0.0.1 --port 3000
) &
WEB_PID=$!
printf 'Started web (pid %s).\n' "$WEB_PID"

monitor_processes
