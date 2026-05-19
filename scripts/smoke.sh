#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
CREATE_VENV=1
if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  :
elif [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
  CREATE_VENV=0
else
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info < (3, 11):
    raise SystemExit("NepsisCGN requires Python >=3.11")
PY

if [[ "$CREATE_VENV" == "1" ]]; then
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[dev,api]'
.venv/bin/python -m pytest -q

cd nepsis-web
npm ci
npm run lint
npm run build
