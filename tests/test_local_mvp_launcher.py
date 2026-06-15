from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mvp-local.sh"
OPERATOR_SCRIPT = ROOT / "scripts" / "operator-local.sh"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_local_mvp_launcher_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_local_mvp_launcher_uses_existing_entrypoints_and_demo_ports() -> None:
    text = _script_text()

    assert ".venv/bin/nepsiscgn-api-asgi" in text
    assert "NEPSIS_API_HOST=127.0.0.1" in text
    assert "NEPSIS_API_PORT=8787" in text
    assert "NEPSIS_API_ALLOW_ANON=true" in text
    assert "npm run dev -- --hostname 127.0.0.1 --port 3000" in text
    assert "NEPSIS_API_BASE_URL=http://127.0.0.1:8787" in text
    assert "NEPSIS_ENGINE_ALLOW_ANON=true" in text
    assert "NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true" in text
    assert "NEXT_TELEMETRY_DISABLED=1" in text
    assert "http://127.0.0.1:3000/mvp" in text


def test_local_mvp_launcher_declares_dependency_checks_and_cleanup() -> None:
    text = _script_text()

    assert "nepsis-web/node_modules/.bin/next" in text
    assert ".venv/bin/python -m pip install -e '.[dev,api]'" in text
    assert "cd nepsis-web && npm ci" in text
    assert "trap cleanup EXIT" in text
    assert "trap 'on_signal INT' INT" in text
    assert "trap 'on_signal TERM' TERM" in text
    assert "kill" in text
    assert "Ctrl-C stops backend and web" in text


def test_local_operator_launcher_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(OPERATOR_SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_local_operator_launcher_uses_private_operator_gates() -> None:
    text = OPERATOR_SCRIPT.read_text(encoding="utf-8")

    assert ".venv/bin/nepsiscgn-api-asgi" in text
    assert "NEPSIS_API_HOST=127.0.0.1" in text
    assert "NEPSIS_API_PORT=8787" in text
    assert "NEPSIS_API_ALLOW_ANON=false" in text
    assert 'NEPSIS_API_TOKEN="$LOCAL_API_TOKEN"' in text
    assert "NEPSIS_API_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000" in text
    assert "NEPSIS_API_BASE_URL=http://127.0.0.1:8787" in text
    assert "NEPSIS_LIVE_OPERATOR_ENABLED=true" in text
    assert "NEPSIS_ENGINE_ALLOW_ANON=false" in text
    assert "NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true" in text
    assert "NEPSIS_MODEL_ROUTES_ENABLED=true" in text
    assert 'NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET="$LOCAL_PROPOSAL_RECEIPT_SECRET"' in text
    assert "http://127.0.0.1:3000/operator" in text


def test_local_operator_launcher_does_not_impersonate_shared_operator_deployment() -> None:
    text = OPERATOR_SCRIPT.read_text(encoding="utf-8")

    assert "NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=false" in text
    assert "NEPSIS_DEPLOYMENT_MODE=" in text
    assert "NEXT_PUBLIC_NEPSIS_OPERATOR_SITE=false" in text
    assert "RESEND_API_KEY=" in text
    assert "NEPSIS_AUTH_FROM_EMAIL=" in text
    assert "operator@local.test" in text
    assert "Server model key required" in text


def test_local_launchers_do_not_enable_browser_provider_key_ingestion() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in [SCRIPT, OPERATOR_SCRIPT])

    assert "NEPSIS_BROWSER_MODEL_KEYS_ALLOWED" not in combined
