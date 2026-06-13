#!/usr/bin/env python3
"""Scan for OpenAI key exposure and unsafe public-site env combinations."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SECRET_PATTERN = re.compile(r"sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}", re.IGNORECASE)
ENV_ASSIGNMENT_PATTERN = re.compile(
    r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$"
)
NEXT_PUBLIC_SENSITIVE_PATTERN = re.compile(
    r"^NEXT_PUBLIC_.*(?:OPENAI.*(?:KEY|TOKEN|SECRET)|API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE|CREDENTIAL)",
    re.IGNORECASE,
)

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".next",
    ".turbo",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "__pycache__",
}
TRUE_VALUES = {"1", "true", "yes", "y", "on"}
PUBLIC_SITE_FLAG = "NEXT_PUBLIC_NEPSIS_PUBLIC_SITE"
OPERATOR_MODE_FLAG = "NEPSIS_DEPLOYMENT_MODE"
OPERATOR_SITE_FLAG = "NEXT_PUBLIC_NEPSIS_OPERATOR_SITE"
UNSAFE_PUBLIC_FLAGS = {
    "NEPSIS_MODEL_ROUTES_ENABLED",
    "NEPSIS_ENGINE_ALLOW_ANON",
    "NEPSIS_AUTH_ALLOW_CODE_PREVIEW",
}
OPENAI_SERVER_KEY_NAMES = {"OPENAI_API_KEY", "NEPSIS_OPENAI_API_KEY"}


@dataclass(frozen=True)
class EnvAssignment:
    value: str
    line: int


@dataclass(frozen=True)
class Issue:
    path: Path
    line: int
    message: str


def _short_match(match: str) -> str:
    if len(match) <= 12:
        return match
    return f"{match[:6]}...{match[-4:]}"


def _list_staged_paths() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _list_all_paths() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--modified", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _walk_directory(base: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".git")]
        for name in files:
            if name.startswith(".git"):
                continue
            yield Path(root) / name


def _iter_files(paths: Iterable[str]) -> Iterable[Path]:
    for path in paths:
        p = Path(path)
        if not p.exists():
            continue
        if p.is_dir():
            yield from _walk_directory(p)
            continue
        yield p


def _should_scan(path: Path) -> bool:
    return not any(part in SKIP_DIRS for part in path.parts)


def _is_env_like_path(path: Path) -> bool:
    name = path.name
    return name.startswith(".env") or name.endswith(".env") or ".env." in name


def _normalize_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1].strip()
    return value


def _env_true(value: str | None) -> bool:
    return bool(value and value.strip().lower() in TRUE_VALUES)


def _file_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def _staged_file_text(path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f":{path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", errors="ignore")


def _collect_env_assignments(lines: list[str]) -> dict[str, EnvAssignment]:
    assignments: dict[str, EnvAssignment] = {}
    for lineno, line in enumerate(lines, start=1):
        match = ENV_ASSIGNMENT_PATTERN.match(line)
        if not match:
            continue
        name = match.group(1)
        assignments[name] = EnvAssignment(value=_normalize_env_value(match.group(2)), line=lineno)
    return assignments


def _scan_text(path: Path, text: str) -> list[Issue]:
    issues: list[Issue] = []
    lines = text.splitlines()

    for lineno, line in enumerate(lines, start=1):
        secret = SECRET_PATTERN.search(line)
        if secret:
            issues.append(
                Issue(
                    path=path,
                    line=lineno,
                    message=f"OpenAI key-like value ({_short_match(secret.group(0))}) must not be committed.",
                )
            )

    if not _is_env_like_path(path):
        return issues

    assignments = _collect_env_assignments(lines)
    for name, assignment in assignments.items():
        if NEXT_PUBLIC_SENSITIVE_PATTERN.search(name):
            issues.append(
                Issue(
                    path=path,
                    line=assignment.line,
                    message=f"{name} is browser-exposed; keep OpenAI keys and other secrets server-only.",
                )
            )

    public_site = assignments.get(PUBLIC_SITE_FLAG)
    node_env = assignments.get("NODE_ENV")
    public_mode = _env_true(public_site.value if public_site else None) or (
        node_env is not None and node_env.value.strip().lower() == "production"
    )
    if public_mode:
        public_context = (
            f"{PUBLIC_SITE_FLAG}=true"
            if public_site and _env_true(public_site.value)
            else "NODE_ENV=production"
        )
        for name in sorted(UNSAFE_PUBLIC_FLAGS):
            assignment = assignments.get(name)
            if assignment and _env_true(assignment.value):
                issues.append(
                    Issue(
                        path=path,
                        line=assignment.line,
                        message=f"{name}=true cannot be used when {public_context}.",
                    )
                )

        for name in sorted(OPENAI_SERVER_KEY_NAMES):
            assignment = assignments.get(name)
            if assignment and assignment.value.strip():
                issues.append(
                    Issue(
                        path=path,
                        line=assignment.line,
                        message=f"{name} must stay unset when {public_context}.",
                    )
                )

        cors = assignments.get("NEPSIS_API_ALLOWED_ORIGINS")
        if cors and _normalize_env_value(cors.value) == "*":
            issues.append(
                Issue(
                    path=path,
                    line=cors.line,
                    message=f"NEPSIS_API_ALLOWED_ORIGINS=* cannot be used when {public_context}.",
                )
            )

    deployment_mode = assignments.get(OPERATOR_MODE_FLAG)
    operator_site = assignments.get(OPERATOR_SITE_FLAG)
    operator_mode = (
        deployment_mode is not None and deployment_mode.value.strip().lower() == "operator"
    ) or _env_true(operator_site.value if operator_site else None)
    if operator_mode:
        operator_context = (
            f"{OPERATOR_MODE_FLAG}=operator"
            if deployment_mode is not None and deployment_mode.value.strip().lower() == "operator"
            else f"{OPERATOR_SITE_FLAG}=true"
        )
        preview = assignments.get("NEPSIS_AUTH_ALLOW_CODE_PREVIEW")
        if preview and _env_true(preview.value):
            issues.append(
                Issue(
                    path=path,
                    line=preview.line,
                    message=f"NEPSIS_AUTH_ALLOW_CODE_PREVIEW=true cannot be used when {operator_context}.",
                )
            )

        allowed_emails = assignments.get("NEPSIS_AUTH_ALLOWED_EMAILS")
        if not allowed_emails or not allowed_emails.value.strip():
            issues.append(
                Issue(
                    path=path,
                    line=deployment_mode.line if deployment_mode else operator_site.line if operator_site else 1,
                    message=f"NEPSIS_AUTH_ALLOWED_EMAILS must be set when {operator_context}.",
                )
            )

        cors = assignments.get("NEPSIS_API_ALLOWED_ORIGINS")
        if cors and _normalize_env_value(cors.value) == "*":
            issues.append(
                Issue(
                    path=path,
                    line=cors.line,
                    message=f"NEPSIS_API_ALLOWED_ORIGINS=* cannot be used when {operator_context}.",
                )
            )

        seal_secret = assignments.get("NEPSIS_OPERATOR_PACKET_SEAL_SECRET")
        if not seal_secret or not seal_secret.value.strip():
            issues.append(
                Issue(
                    path=path,
                    line=deployment_mode.line if deployment_mode else operator_site.line if operator_site else 1,
                    message=f"NEPSIS_OPERATOR_PACKET_SEAL_SECRET must be set when {operator_context}.",
                )
            )

        model_routes_enabled = assignments.get("NEPSIS_MODEL_ROUTES_ENABLED")
        receipt_secret = assignments.get("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET")
        if model_routes_enabled and _env_true(model_routes_enabled.value):
            if not receipt_secret or not receipt_secret.value.strip():
                issues.append(
                    Issue(
                        path=path,
                        line=model_routes_enabled.line,
                        message=(
                            "NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET must be set when "
                            "NEPSIS_MODEL_ROUTES_ENABLED=true in operator mode."
                        ),
                    )
                )

    return issues


def _scan_files(paths: Iterable[str]) -> list[Issue]:
    issues: list[Issue] = []
    for path in _iter_files(paths):
        if not _should_scan(path) or not path.is_file():
            continue
        text = _file_text(path)
        if text is not None:
            issues.extend(_scan_text(path, text))
    return issues


def _scan_staged(paths: Iterable[str]) -> list[Issue]:
    issues: list[Issue] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not _should_scan(path):
            continue
        text = _staged_file_text(raw_path)
        if text is not None:
            issues.extend(_scan_text(path, text))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan files for OpenAI secrets and unsafe public-site env combinations."
    )
    parser.add_argument("paths", nargs="*", help="Specific paths to scan.")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Scan staged files instead of the working tree.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Scan all tracked, modified, and untracked non-ignored files.",
    )
    args = parser.parse_args()

    if args.staged:
        issues = _scan_staged(_list_staged_paths())
    elif args.paths:
        issues = _scan_files(args.paths)
    elif args.all:
        issues = _scan_files(_list_all_paths())
    else:
        issues = _scan_files(["."])

    if not issues:
        return 0

    print("Potential unsafe OpenAI/public deployment configuration detected:")
    for issue in issues:
        print(f"- {issue.path}:{issue.line}: {issue.message}")
    print("Use server-only env vars for private keys and keep public MVP deployments model-free.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
