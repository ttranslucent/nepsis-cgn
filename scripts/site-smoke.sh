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


failed = False


def check(path: str, *, method: str = "GET", body: dict | None = None, expected: set[int] | None = None) -> tuple[int, str]:
    global failed
    expected = expected or {200}
    status, payload = request(path, method=method, body=body)
    ok = status in expected
    print(f"{method:4} {path:26} {status}")
    if not ok:
        failed = True
        print(payload[:500])
    return status, payload


def as_json(path: str, payload: str) -> dict:
    global failed
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        failed = True
        print(f"{path} did not return JSON: {exc}")
        return {}
    if not isinstance(data, dict):
        failed = True
        print(f"{path} JSON response was not an object")
        return {}
    return data


check("/")
check("/mvp")
check("/login")
check("/engine")

status_code, payload = check("/api/status")
if status_code == 200:
    data = as_json("/api/status", payload)
    mvp = data.get("mvp") if isinstance(data.get("mvp"), dict) else {}
    auth = data.get("auth") if isinstance(data.get("auth"), dict) else {}
    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    if mvp.get("schemaId") != "nepsis.mvp_packet" or not mvp.get("available"):
        failed = True
        print("/api/status did not report the frozen MVP as available")
    if mvp.get("noLoginRequired") is not True:
        failed = True
        print("/api/status did not report no-login MVP access")
    if auth.get("previewCodesEnabled") is not False:
        failed = True
        print("/api/status did not report disabled public preview codes")
    if auth.get("emailConfigured") is False and auth.get("operatorLoginReady") is not False:
        failed = True
        print("/api/status reported operator login ready without email delivery")
    if models.get("enabled") is not False or models.get("hasServerOpenAiKey") is not False:
        failed = True
        print("/api/status did not report model routes disabled without server provider keys")

status_code, payload = check("/api/auth/session")
if status_code == 200:
    data = as_json("/api/auth/session", payload)
    if data.get("authenticated") is not False:
        failed = True
        print("/api/auth/session unexpectedly reported an authenticated visitor")
    if data.get("engineControlAllowed") is not False:
        failed = True
        print("/api/auth/session unexpectedly allowed anonymous engine controls")

status_code, payload = check("/api/playground-nepsis")
if status_code == 200:
    data = as_json("/api/playground-nepsis", payload)
    if data.get("modelRoutesEnabled") is not False:
        failed = True
        print("/api/playground-nepsis did not report disabled model routes")
    if data.get("hasServerKey") is not False:
        failed = True
        print("/api/playground-nepsis reported a server provider key on the public site")

check("/api/playground-nepsis", method="POST", body={"prompt": "smoke", "packId": "jailing_jingall"}, expected={403})
check("/api/run-with-nepsis", method="POST", body={"prompt": "smoke"}, expected={403})
check("/api/engine/health")

status_code, payload = check("/api/engine/mvp", method="POST", body={"case_id": "jailing"})
if status_code == 200 and "nepsis.mvp_packet" not in payload:
    failed = True
    print("MVP response did not include nepsis.mvp_packet")

if failed:
    raise SystemExit(1)
PY
