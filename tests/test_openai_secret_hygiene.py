from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_openai_secrets.py"


def run_scan(*paths: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *[str(path) for path in paths]],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def fake_openai_key() -> str:
    return "sk-proj-" + ("A" * 28)


def test_scan_blocks_hardcoded_openai_key_and_masks_value(tmp_path: Path) -> None:
    leaked = fake_openai_key()
    target = tmp_path / "route.ts"
    target.write_text(f'const apiKey = "{leaked}";\n', encoding="utf-8")

    result = run_scan(target)

    assert result.returncode == 1
    assert "OpenAI key-like value" in result.stdout
    assert str(target) in result.stdout
    assert leaked not in result.stdout


def test_scan_blocks_browser_public_openai_env_names(tmp_path: Path) -> None:
    target = tmp_path / ".env.production"
    target.write_text("NEXT_PUBLIC_OPENAI_API_KEY=placeholder\n", encoding="utf-8")

    result = run_scan(target)

    assert result.returncode == 1
    assert "NEXT_PUBLIC_OPENAI_API_KEY" in result.stdout
    assert "browser-exposed" in result.stdout


def test_scan_blocks_deprecated_browser_model_key_flag(tmp_path: Path) -> None:
    target = tmp_path / ".env.local"
    target.write_text("NEPSIS_BROWSER_MODEL_KEYS_ALLOWED=true\n", encoding="utf-8")

    result = run_scan(target)

    assert result.returncode == 1
    assert "NEPSIS_BROWSER_MODEL_KEYS_ALLOWED is deprecated" in result.stdout


def test_scan_blocks_bad_public_site_env_combinations(tmp_path: Path) -> None:
    target = tmp_path / ".env.production"
    target.write_text(
        textwrap.dedent(
            """
            NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true
            NEPSIS_MODEL_ROUTES_ENABLED=true
            NEPSIS_ENGINE_ALLOW_ANON=true
            NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true
            OPENAI_API_KEY=from-secret-manager
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = run_scan(target)

    assert result.returncode == 1
    assert "NEPSIS_MODEL_ROUTES_ENABLED=true cannot be used when NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true" in result.stdout
    assert "NEPSIS_ENGINE_ALLOW_ANON=true cannot be used when NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true" in result.stdout
    assert "NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true cannot be used when NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true" in result.stdout
    assert "OPENAI_API_KEY must stay unset when NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=true" in result.stdout


def test_scan_blocks_bad_operator_auth_env_combinations(tmp_path: Path) -> None:
    target = tmp_path / ".env.operator"
    target.write_text(
        textwrap.dedent(
            """
            NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=false
            NEPSIS_DEPLOYMENT_MODE=operator
            NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true
            NEPSIS_MODEL_ROUTES_ENABLED=true
            NEPSIS_AUTH_SECRET=from-secret-manager
            RESEND_API_KEY=from-secret-manager
            NEPSIS_AUTH_FROM_EMAIL=login@operator.example
            NEPSIS_API_ALLOWED_ORIGINS=*
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = run_scan(target)

    assert result.returncode == 1
    assert "NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true cannot be used when NEPSIS_DEPLOYMENT_MODE=operator" in result.stdout
    assert "NEPSIS_AUTH_ALLOWED_EMAILS must be set when NEPSIS_DEPLOYMENT_MODE=operator" in result.stdout
    assert "NEPSIS_API_ALLOWED_ORIGINS=* cannot be used when NEPSIS_DEPLOYMENT_MODE=operator" in result.stdout
    assert "NEPSIS_OPERATOR_PACKET_SEAL_SECRET must be set when NEPSIS_DEPLOYMENT_MODE=operator" in result.stdout
    assert (
        "NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET must be set when NEPSIS_MODEL_ROUTES_ENABLED=true in operator mode"
        in result.stdout
    )


def test_scan_requires_proposal_receipt_secret_for_truthy_operator_model_routes(tmp_path: Path) -> None:
    target = tmp_path / ".env.operator"
    target.write_text(
        textwrap.dedent(
            """
            NEXT_PUBLIC_NEPSIS_PUBLIC_SITE=false
            NEPSIS_DEPLOYMENT_MODE=operator
            NEPSIS_MODEL_ROUTES_ENABLED=1
            NEPSIS_AUTH_ALLOWED_EMAILS=operator@example.com
            NEPSIS_AUTH_SECRET=from-secret-manager
            RESEND_API_KEY=from-secret-manager
            NEPSIS_AUTH_FROM_EMAIL=login@operator.example
            NEPSIS_OPERATOR_PACKET_SEAL_SECRET=from-secret-manager
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    result = run_scan(target)

    assert result.returncode == 1
    assert (
        "NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET must be set when NEPSIS_MODEL_ROUTES_ENABLED=true in operator mode"
        in result.stdout
    )


def test_current_web_env_examples_pass_secret_hygiene_scan() -> None:
    result = run_scan(
        ROOT / "nepsis-web" / ".env.example",
        ROOT / "nepsis-web" / ".env.public.example",
        ROOT / "nepsis-web" / ".env.operator.example",
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_commit_hook_runs_secret_hygiene_checker() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "scripts/check_openai_secrets.py --staged" in config
