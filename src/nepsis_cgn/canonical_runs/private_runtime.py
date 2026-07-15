from __future__ import annotations

from dataclasses import dataclass
import hmac
import os
from pathlib import Path
import stat
from typing import Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nepsis_cgn.canonical_runs.private_api import (
    PrivateOperatorRunConfig,
    create_private_operator_run_app,
    validate_private_operator_run_config,
)
from nepsis_cgn.canonical_runs.profile_registry import GovernanceProfileRegistry
from nepsis_cgn.canonical_runs.operator_disposition import (
    OPERATOR_DISPOSITION_ACTION_TYPE,
    validate_operator_disposition,
)
from nepsis_cgn.canonical_runs.actualization import (
    PERFORM_ZEROBACK_ACTION_TYPE,
    RELEASE_STILL_ACTION_TYPE,
    REQUEST_DECISION_COMMIT_ACTION_TYPE,
    validate_decision_commit,
    validate_release_still,
    validate_zeroback,
)
from nepsis_cgn.canonical_runs.service import CanonicalRunService
from nepsis_cgn.canonical_runs.store import CanonicalRunStore
from nepsis_cgn.canonical_runs.trust_anchor_registry import (
    ReceiptTrustAnchorRegistry,
    TrustAnchorRegistryError,
)
from nepsis_cgn.contracts.canonical_run import ActorContext
from nepsis_cgn.verification.receipts import build_trust_anchor


@dataclass(frozen=True)
class PrivateRuntimeSettings:
    enabled: bool
    bind_host: str
    port: int
    canonical_store_path: Path
    profile_store_path: Path
    trust_anchor_ledger_path: Path
    signing_key_path: Path
    signing_key_activated_at: str
    model_token: str
    operator_token: str
    validator_token: str


class PrivateRuntimeConfigurationError(ValueError):
    pass


def load_private_runtime_settings(
    environment: Mapping[str, str] | None = None,
) -> PrivateRuntimeSettings:
    values = dict(os.environ if environment is None else environment)
    settings = PrivateRuntimeSettings(
        enabled=values.get("NEPSIS_CANONICAL_RUNS_ENABLED") == "1",
        bind_host=values.get("NEPSIS_CANONICAL_RUNS_BIND_HOST", "127.0.0.1"),
        port=_port(values.get("NEPSIS_CANONICAL_RUNS_PORT", "8789")),
        canonical_store_path=Path(
            _required(values, "NEPSIS_CANONICAL_RUNS_STORE_PATH")
        ).expanduser(),
        profile_store_path=Path(
            _required(values, "NEPSIS_GOVERNANCE_PROFILE_STORE_PATH")
        ).expanduser(),
        trust_anchor_ledger_path=Path(
            _required(values, "NEPSIS_RECEIPT_TRUST_ANCHOR_LEDGER_PATH")
        ).expanduser(),
        signing_key_path=Path(
            _required(values, "NEPSIS_CANONICAL_RUNS_SIGNING_KEY_PATH")
        ).expanduser(),
        signing_key_activated_at=_required(
            values, "NEPSIS_CANONICAL_RUNS_SIGNING_KEY_ACTIVATED_AT"
        ),
        model_token=_required(values, "NEPSIS_CANONICAL_RUNS_MODEL_TOKEN"),
        operator_token=_required(values, "NEPSIS_CANONICAL_RUNS_OPERATOR_TOKEN"),
        validator_token=_required(values, "NEPSIS_CANONICAL_RUNS_VALIDATOR_TOKEN"),
    )
    validate_private_runtime_settings(settings)
    return settings


def validate_private_runtime_settings(settings: PrivateRuntimeSettings) -> None:
    try:
        validate_private_operator_run_config(
            PrivateOperatorRunConfig(
                enabled=settings.enabled,
                bind_host=settings.bind_host,
                durable_store_path=settings.canonical_store_path,
            )
        )
        validate_private_operator_run_config(
            PrivateOperatorRunConfig(
                enabled=settings.enabled,
                bind_host=settings.bind_host,
                durable_store_path=settings.profile_store_path,
            )
        )
        validate_private_operator_run_config(
            PrivateOperatorRunConfig(
                enabled=settings.enabled,
                bind_host=settings.bind_host,
                durable_store_path=settings.trust_anchor_ledger_path,
            )
        )
    except ValueError as exc:
        raise PrivateRuntimeConfigurationError(str(exc)) from exc
    if not 1 <= settings.port <= 65535:
        raise PrivateRuntimeConfigurationError("port must be from 1 through 65535")
    durable_paths = {
        settings.canonical_store_path.resolve(strict=False),
        settings.profile_store_path.resolve(strict=False),
        settings.trust_anchor_ledger_path.resolve(strict=False),
    }
    if len(durable_paths) != 3:
        raise PrivateRuntimeConfigurationError(
            "canonical, profile, and trust-anchor registries require distinct database paths"
        )
    if settings.trust_anchor_ledger_path.resolve(
        strict=False
    ) == settings.signing_key_path.resolve(strict=False):
        raise PrivateRuntimeConfigurationError(
            "trust-anchor ledger and signing key require distinct paths"
        )
    tokens = (
        settings.model_token,
        settings.operator_token,
        settings.validator_token,
    )
    if any(len(token) < 32 for token in tokens):
        raise PrivateRuntimeConfigurationError(
            "private capability tokens must contain at least 32 characters"
        )
    if len(set(tokens)) != len(tokens):
        raise PrivateRuntimeConfigurationError(
            "model, operator, and validator tokens must be distinct"
        )


def build_private_runtime_app(
    settings: PrivateRuntimeSettings,
    *,
    store: CanonicalRunStore | None = None,
    profile_registry: GovernanceProfileRegistry | None = None,
    trust_anchor_registry: ReceiptTrustAnchorRegistry | None = None,
    private_key: Ed25519PrivateKey | None = None,
):
    validate_private_runtime_settings(settings)
    resolved_store = store or CanonicalRunStore.open(settings.canonical_store_path)
    resolved_profiles = profile_registry or GovernanceProfileRegistry.open(
        settings.profile_store_path
    )
    resolved_key = private_key or _load_private_key(settings.signing_key_path)
    try:
        configured_anchor = build_trust_anchor(
            resolved_key.public_key(),
            activated_at=settings.signing_key_activated_at,
        )
    except ValueError as exc:
        raise PrivateRuntimeConfigurationError(str(exc)) from exc
    try:
        resolved_anchor_registry = (
            trust_anchor_registry
            or ReceiptTrustAnchorRegistry.open_existing(
                settings.trust_anchor_ledger_path
            )
        )
    except TrustAnchorRegistryError as exc:
        raise PrivateRuntimeConfigurationError(str(exc)) from exc
    try:
        anchor = resolved_anchor_registry.ensure_active_anchor(configured_anchor)
    except (TrustAnchorRegistryError, ValueError) as exc:
        raise PrivateRuntimeConfigurationError(str(exc)) from exc
    service = CanonicalRunService(
        store=resolved_store,
        private_key=resolved_key,
        trust_anchor=anchor,
    )
    actors = (
        (
            settings.model_token,
            ActorContext(
                actor_id="model:codex-app-server",
                provenance_class="model",
                capability_id="capability:model:codex-app-server",
                capabilities=frozenset(
                    {"read_snapshot", "submit_model_candidate"}
                ),
            ),
        ),
        (
            settings.operator_token,
            ActorContext(
                actor_id="operator:local",
                provenance_class="operator",
                capability_id="capability:operator:local",
                capabilities=frozenset(
                    {
                        "create_run",
                        "export_run",
                        "perform_zeroback",
                        "read_snapshot",
                        "release_still",
                        "request_decision_commit",
                        "revise_operator_profile",
                        "submit_operator_disposition",
                    }
                ),
            ),
        ),
        (
            settings.validator_token,
            ActorContext(
                actor_id="validator:detached-local",
                provenance_class="validator",
                capability_id="capability:validator:detached-local",
                capabilities=frozenset(
                    {"export_run", "read_snapshot", "verify_run"}
                ),
            ),
        ),
    )

    def resolve_token(token: str) -> ActorContext | None:
        for expected, actor in actors:
            if hmac.compare_digest(token, expected):
                return actor
        return None

    def resolve_operator_validator(capability: str, action_type: str):
        if (
            capability == "submit_operator_disposition"
            and action_type == OPERATOR_DISPOSITION_ACTION_TYPE
        ):
            return validate_operator_disposition
        if capability == "release_still" and action_type == RELEASE_STILL_ACTION_TYPE:
            return validate_release_still
        if (
            capability == "perform_zeroback"
            and action_type == PERFORM_ZEROBACK_ACTION_TYPE
        ):
            return validate_zeroback
        if (
            capability == "request_decision_commit"
            and action_type == REQUEST_DECISION_COMMIT_ACTION_TYPE
        ):
            return validate_decision_commit
        return None

    app = create_private_operator_run_app(
        service=service,
        resolve_token=resolve_token,
        resolve_operator_validator=resolve_operator_validator,
        config=PrivateOperatorRunConfig(
            enabled=settings.enabled,
            bind_host=settings.bind_host,
            durable_store_path=settings.canonical_store_path,
        ),
        profile_registry=resolved_profiles,
    )
    app.state.receipt_trust_anchor_registry = resolved_anchor_registry
    return app


def main() -> None:
    settings = load_private_runtime_settings()
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover
        raise PrivateRuntimeConfigurationError(
            "uvicorn is required for the private canonical-run runtime"
        ) from exc
    uvicorn.run(
        build_private_runtime_app(settings),
        host=settings.bind_host,
        port=settings.port,
        access_log=False,
    )


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    if not path.is_absolute() or not path.is_file():
        raise PrivateRuntimeConfigurationError(
            "signing key path must be an existing absolute file"
        )
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PrivateRuntimeConfigurationError(
            "signing key permissions must deny group and other access"
        )
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, TypeError, ValueError) as exc:
        raise PrivateRuntimeConfigurationError("signing key is unreadable") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise PrivateRuntimeConfigurationError("signing key must be Ed25519")
    return key


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value:
        raise PrivateRuntimeConfigurationError(f"{name} is required")
    return value


def _port(value: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise PrivateRuntimeConfigurationError("port must be an integer") from exc


__all__ = [
    "PrivateRuntimeConfigurationError",
    "PrivateRuntimeSettings",
    "build_private_runtime_app",
    "load_private_runtime_settings",
    "main",
    "validate_private_runtime_settings",
]
