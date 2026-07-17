from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import os
from pathlib import Path
import re
import secrets
import shlex
import tempfile
from typing import Iterable, Mapping, Sequence

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nepsis_cgn.canonical_runs.private_runtime import (
    PrivateRuntimeSettings,
    validate_private_runtime_settings,
)
from nepsis_cgn.canonical_runs.profile_registry import GovernanceProfileRegistry
from nepsis_cgn.canonical_runs.store import CanonicalRunStore
from nepsis_cgn.canonical_runs.trust_anchor_registry import (
    ReceiptTrustAnchorRegistry,
)
from nepsis_cgn.contracts.canonical_json import canonical_json
from nepsis_cgn.verification.receipts import build_trust_anchor

DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_PORT = 8789
DEFAULT_PROFILE_ID = "nepsismc-local"
_PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class PrivateRuntimeInitializationError(RuntimeError):
    """The requested private-runtime state root cannot be initialized safely."""


@dataclass(frozen=True)
class PrivateRuntimeInitialization:
    state_root: Path
    runtime_environment_path: Path
    mc_profile_environment_path: Path
    trust_anchor_path: Path


def initialize_private_runtime(
    state_root: str | Path,
    *,
    bind_host: str = DEFAULT_BIND_HOST,
    port: int = DEFAULT_PORT,
    profile_id: str = DEFAULT_PROFILE_ID,
) -> PrivateRuntimeInitialization:
    """Create one new, durable private-runtime state root without overwrite semantics."""

    root = _validated_new_state_root(state_root)
    host = _validated_loopback_host(bind_host)
    port_value = _validated_port(port)
    profile_id_value = _validated_profile_id(profile_id)

    paths = {
        "canonical_store": root / "canonical-runs.sqlite",
        "profile_store": root / "governance-profiles.sqlite",
        "trust_anchor_ledger": root / "receipt-trust-anchor.sqlite",
        "signing_key": root / "receipt-signing-key.pem",
        "trust_anchor": root / "receipt-trust-anchor.json",
        "runtime_environment": root / "cgn-runtime.env",
        "mc_profile_environment": root / "mc-profile.env",
    }
    created_root = False
    try:
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        created_root = True
        os.chmod(root, 0o700)

        activated_at = _utc_millisecond_timestamp()
        private_key = Ed25519PrivateKey.generate()
        private_key_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        _write_new_file(paths["signing_key"], private_key_bytes, mode=0o600)

        trust_anchor = build_trust_anchor(
            private_key.public_key(), activated_at=activated_at
        )
        _write_new_file(
            paths["trust_anchor"],
            canonical_json(trust_anchor).encode("utf-8"),
            mode=0o600,
        )

        model_token, operator_token, profile_token, validator_token = _distinct_tokens()
        settings = PrivateRuntimeSettings(
            enabled=True,
            bind_host=host,
            port=port_value,
            canonical_store_path=paths["canonical_store"],
            profile_store_path=paths["profile_store"],
            trust_anchor_ledger_path=paths["trust_anchor_ledger"],
            signing_key_path=paths["signing_key"],
            signing_key_activated_at=activated_at,
            model_token=model_token,
            operator_token=operator_token,
            profile_token=profile_token,
            validator_token=validator_token,
        )
        validate_private_runtime_settings(settings)

        run_store = CanonicalRunStore.open(paths["canonical_store"])
        run_store.close()
        profile_store = GovernanceProfileRegistry.open(paths["profile_store"])
        profile_store.close()
        anchor_registry = ReceiptTrustAnchorRegistry.initialize(
            paths["trust_anchor_ledger"]
        )
        try:
            active_anchor = anchor_registry.ensure_active_anchor(trust_anchor)
            exported_registry = anchor_registry.export_ledger()
        finally:
            anchor_registry.close()
        if active_anchor != trust_anchor or exported_registry.get("status") != "active":
            raise PrivateRuntimeInitializationError(
                "receipt trust anchor did not become active"
            )

        for database_path in (
            paths["canonical_store"],
            paths["profile_store"],
            paths["trust_anchor_ledger"],
        ):
            os.chmod(database_path, 0o600)

        runtime_environment = {
            "NEPSIS_CANONICAL_RUNS_ENABLED": "1",
            "NEPSIS_CANONICAL_RUNS_BIND_HOST": host,
            "NEPSIS_CANONICAL_RUNS_PORT": str(port_value),
            "NEPSIS_CANONICAL_RUNS_STORE_PATH": str(paths["canonical_store"]),
            "NEPSIS_GOVERNANCE_PROFILE_STORE_PATH": str(paths["profile_store"]),
            "NEPSIS_RECEIPT_TRUST_ANCHOR_LEDGER_PATH": str(
                paths["trust_anchor_ledger"]
            ),
            "NEPSIS_CANONICAL_RUNS_SIGNING_KEY_PATH": str(paths["signing_key"]),
            "NEPSIS_CANONICAL_RUNS_SIGNING_KEY_ACTIVATED_AT": activated_at,
            "NEPSIS_CANONICAL_RUNS_MODEL_TOKEN": model_token,
            "NEPSIS_CANONICAL_RUNS_OPERATOR_TOKEN": operator_token,
            "NEPSIS_CANONICAL_RUNS_PROFILE_TOKEN": profile_token,
            "NEPSIS_CANONICAL_RUNS_VALIDATOR_TOKEN": validator_token,
        }
        mc_profile_environment = {
            "NEPSISMC_RUNTIME_MODE": "legacy",
            "NEPSISMC_CGN_PROFILE_BASE_URL": _loopback_base_url(host, port_value),
            "NEPSISMC_CGN_PROFILE_ID": profile_id_value,
            "NEPSISMC_CGN_PROFILE_OPERATOR_TOKEN": profile_token,
        }
        _write_new_file(
            paths["runtime_environment"],
            _environment_bytes(runtime_environment),
            mode=0o600,
        )
        _write_new_file(
            paths["mc_profile_environment"],
            _environment_bytes(mc_profile_environment),
            mode=0o600,
        )
    except BaseException as exc:
        if created_root:
            _cleanup_created_root(root, paths.values())
        if isinstance(exc, PrivateRuntimeInitializationError):
            raise
        raise PrivateRuntimeInitializationError(
            "private runtime initialization failed; no existing state was modified"
        ) from exc

    return PrivateRuntimeInitialization(
        state_root=root,
        runtime_environment_path=paths["runtime_environment"],
        mc_profile_environment_path=paths["mc_profile_environment"],
        trust_anchor_path=paths["trust_anchor"],
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Initialize one new loopback-only NepsisCGN private-runtime state root."
        )
    )
    parser.add_argument(
        "--state-root",
        required=True,
        help="Absolute, non-temporary path that does not already exist.",
    )
    parser.add_argument("--bind-host", default=DEFAULT_BIND_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--profile-id", default=DEFAULT_PROFILE_ID)
    args = parser.parse_args(argv)
    try:
        result = initialize_private_runtime(
            args.state_root,
            bind_host=args.bind_host,
            port=args.port,
            profile_id=args.profile_id,
        )
    except (PrivateRuntimeInitializationError, ValueError) as exc:
        parser.error(str(exc))
    print(f"Private runtime initialized: {result.state_root}")
    print(f"CGN runtime environment: {result.runtime_environment_path}")
    print(f"MC profile environment: {result.mc_profile_environment_path}")
    print(f"Public receipt trust anchor: {result.trust_anchor_path}")
    print("Receipt trust-anchor registry status: active")


def _validated_new_state_root(value: str | Path) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise PrivateRuntimeInitializationError("state root must be an absolute path")
    if candidate.exists() or candidate.is_symlink():
        raise PrivateRuntimeInitializationError("state root already exists")
    root = candidate.resolve(strict=False)
    temporary_roots = {
        Path(tempfile.gettempdir()).resolve(strict=False),
        Path("/tmp").resolve(strict=False),
        Path("/var/tmp").resolve(strict=False),
    }
    if any(
        root == temporary or temporary in root.parents for temporary in temporary_roots
    ):
        raise PrivateRuntimeInitializationError(
            "state root cannot use the temporary directory"
        )
    if not root.parent.is_dir():
        raise PrivateRuntimeInitializationError(
            "state root parent must be an existing directory"
        )
    return root


def _validated_loopback_host(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise PrivateRuntimeInitializationError(
            "bind host must be a literal loopback IP address"
        ) from exc
    if not address.is_loopback:
        raise PrivateRuntimeInitializationError(
            "bind host must be a literal loopback IP address"
        )
    return str(address)


def _validated_port(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise PrivateRuntimeInitializationError("port must be from 1 through 65535")
    return value


def _validated_profile_id(value: str) -> str:
    if not isinstance(value, str) or not _PROFILE_ID_RE.fullmatch(value):
        raise PrivateRuntimeInitializationError(
            "profile ID must contain 1-128 letters, digits, dots, underscores, or hyphens"
        )
    return value


def _utc_millisecond_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _distinct_tokens() -> tuple[str, str, str, str]:
    tokens: list[str] = []
    while len(tokens) < 4:
        candidate = secrets.token_hex(32)
        if candidate not in tokens:
            tokens.append(candidate)
    return tokens[0], tokens[1], tokens[2], tokens[3]


def _loopback_base_url(host: str, port: int) -> str:
    rendered_host = f"[{host}]" if ":" in host else host
    return f"http://{rendered_host}:{port}"


def _environment_bytes(values: Mapping[str, str]) -> bytes:
    rows = [f"{name}={shlex.quote(value)}" for name, value in values.items()]
    return ("\n".join(rows) + "\n").encode("utf-8")


def _write_new_file(path: Path, content: bytes, *, mode: int) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.chmod(path, mode)


def _cleanup_created_root(root: Path, paths: Iterable[Path]) -> None:
    cleanup_paths = set(paths)
    for database_path in (
        root / "canonical-runs.sqlite",
        root / "governance-profiles.sqlite",
        root / "receipt-trust-anchor.sqlite",
    ):
        cleanup_paths.add(Path(f"{database_path}-wal"))
        cleanup_paths.add(Path(f"{database_path}-shm"))
        cleanup_paths.add(Path(f"{database_path}-journal"))
    for path in cleanup_paths:
        try:
            if path.is_file() or path.is_symlink():
                path.unlink()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass


__all__ = [
    "DEFAULT_BIND_HOST",
    "DEFAULT_PORT",
    "DEFAULT_PROFILE_ID",
    "PrivateRuntimeInitialization",
    "PrivateRuntimeInitializationError",
    "initialize_private_runtime",
    "main",
]
