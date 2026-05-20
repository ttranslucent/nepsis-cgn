from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_render_blueprint_deploys_existing_asgi_entrypoint() -> None:
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "nepsiscgn-api-asgi" in text
    assert "NEPSIS_API_HOST" in text
    assert "0.0.0.0" in text
    assert "NEPSIS_API_PORT" in text
    assert "$PORT" in text
    assert "NEPSIS_API_TOKEN" in text
    assert "NEPSIS_API_ALLOW_ANON" in text
    assert 'value: "false"' in text
    assert "NEPSIS_API_ALLOWED_ORIGINS" in text
    assert "OPENAI_API_KEY" not in text
    assert "NEPSIS_OPENAI_API_KEY" not in text


def test_site_smoke_script_is_stdlib_python_and_has_expected_routes() -> None:
    script = ROOT / "scripts" / "site-smoke.sh"
    text = script.read_text(encoding="utf-8")
    syntax = subprocess.run(["bash", "-n", str(script)], cwd=ROOT, capture_output=True, text=True)

    assert syntax.returncode == 0, syntax.stderr
    assert "urllib.request" in text
    assert "curl" not in text
    assert "/api/engine/mvp" in text
    assert "/api/engine/health" in text
    assert "/api/auth/session" in text
    assert "/api/playground-nepsis" in text
    assert "/api/run-with-nepsis" in text
    assert "authenticated" in text
    assert "engineControlAllowed" in text
    assert "modelRoutesEnabled" in text
    assert "hasServerKey" in text
