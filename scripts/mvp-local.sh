#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$ROOT_DIR/nepsis-web"
BACKEND_BIN="$ROOT_DIR/.venv/bin/nepsiscgn-api-asgi"
NEXT_BIN="$WEB_DIR/node_modules/.bin/next"

BACKEND_PID=""
WEB_PID=""
SHUTTING_DOWN=0

fail() {
  printf 'mvp-local: %s\n' "$*" >&2
  exit 1
}

check_dependencies() {
  if [[ ! -x "$BACKEND_BIN" ]]; then
    cat >&2 <<EOF
mvp-local: missing backend entrypoint: .venv/bin/nepsiscgn-api-asgi

Run from the repo root:
  python3.11 -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -e '.[dev,api]'
EOF
    exit 1
  fi

  if [[ ! -x "$NEXT_BIN" ]]; then
    cat >&2 <<EOF
mvp-local: missing Next dependency: nepsis-web/node_modules/.bin/next

Run from the repo root:
  cd nepsis-web && npm ci
EOF
    exit 1
  fi

  command -v npm >/dev/null 2>&1 || fail "npm is required to start nepsis-web."
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
  printf '\nReceived %s; shutting down local MVP.\n' "$signal"
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
      printf 'Backend exited with status %s; shutting down local MVP.\n' "$backend_status"
      exit "$backend_status"
    fi

    if [[ -n "$WEB_PID" ]] && ! kill -0 "$WEB_PID" 2>/dev/null; then
      local web_status
      web_status="$(process_exit_status "$WEB_PID")"
      printf 'Web exited with status %s; shutting down local MVP.\n' "$web_status"
      exit "$web_status"
    fi

    sleep 1
  done
}

check_dependencies

trap cleanup EXIT
trap 'on_signal INT' INT
trap 'on_signal TERM' TERM

printf 'Starting NepsisCGN local MVP from %s\n' "$ROOT_DIR"
printf 'Backend: http://127.0.0.1:8787\n'
printf 'Web:     http://127.0.0.1:3000/mvp\n'
printf 'Ctrl-C stops backend and web.\n'

(
  cd "$ROOT_DIR"
  exec env NEPSIS_API_HOST=127.0.0.1 \
    NEPSIS_API_PORT=8787 \
    NEPSIS_API_ALLOW_ANON=true \
    "$BACKEND_BIN"
) &
BACKEND_PID=$!
printf 'Started backend (pid %s).\n' "$BACKEND_PID"

(
  cd "$WEB_DIR"
  exec env NEPSIS_API_BASE_URL=http://127.0.0.1:8787 \
    NEPSIS_ENGINE_ALLOW_ANON=true \
    NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true \
    NEXT_TELEMETRY_DISABLED=1 \
    npm run dev -- --hostname 127.0.0.1 --port 3000
) &
WEB_PID=$!
printf 'Started web (pid %s).\n' "$WEB_PID"

monitor_processes
