#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${NEPSIS_SITE_BASE_URL:-https://nepsis-cgn.vercel.app}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" - "$BASE_URL" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request


base_url = sys.argv[1].rstrip("/")


def request(path: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, str]:
    data = None
    headers = {"User-Agent": "nepsis-site-smoke/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


checks = [
    ("/", "GET", None, {200}),
    ("/mvp", "GET", None, {200}),
    ("/api/auth/session", "GET", None, {200}),
    ("/api/playground-nepsis", "GET", None, {200}),
    ("/api/engine/health", "GET", None, {200}),
    ("/api/engine/mvp", "POST", {"case_id": "jailing"}, {200}),
]

failed = False
for path, method, body, expected in checks:
    status, payload = request(path, method=method, body=body)
    ok = status in expected
    print(f"{method:4} {path:26} {status}")
    if not ok:
        failed = True
        print(payload[:500])
    if path == "/api/engine/mvp" and status == 200 and "nepsis.mvp_packet" not in payload:
        failed = True
        print("MVP response did not include nepsis.mvp_packet")

if failed:
    raise SystemExit(1)
PY
