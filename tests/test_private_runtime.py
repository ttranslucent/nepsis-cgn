from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest

from nepsis_cgn.canonical_runs.private_runtime import (
    PrivateRuntimeConfigurationError,
    PrivateRuntimeSettings,
    build_private_runtime_app,
    load_private_runtime_settings,
    validate_private_runtime_settings,
)
from nepsis_cgn.canonical_runs.profile_registry import GovernanceProfileRegistry
from nepsis_cgn.canonical_runs.store import CanonicalRunStore
from nepsis_cgn.canonical_runs.trust_anchor_registry import (
    ReceiptTrustAnchorRegistry,
)


def settings() -> PrivateRuntimeSettings:
    root = Path.home() / ".nepsis" / "canonical-test"
    return PrivateRuntimeSettings(
        enabled=True,
        bind_host="127.0.0.1",
        port=8789,
        canonical_store_path=root / "runs.sqlite",
        profile_store_path=root / "profiles.sqlite",
        trust_anchor_ledger_path=root / "receipt-anchor-events.sqlite",
        signing_key_path=root / "receipt-key.pem",
        signing_key_activated_at="2026-07-01T00:00:00.000Z",
        model_token="m" * 32,
        operator_token="o" * 32,
        validator_token="v" * 32,
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"enabled": False}, "disabled"),
        ({"bind_host": "0.0.0.0"}, "loopback"),
        ({"port": 0}, "port"),
        ({"operator_token": "short"}, "32"),
        ({"operator_token": "m" * 32}, "distinct"),
        ({"trust_anchor_ledger_path": settings().canonical_store_path}, "distinct"),
    ],
)
def test_runtime_settings_fail_closed(change: dict, message: str) -> None:
    with pytest.raises(PrivateRuntimeConfigurationError, match=message):
        validate_private_runtime_settings(replace(settings(), **change))


def test_environment_loader_requires_every_secret_and_path() -> None:
    with pytest.raises(PrivateRuntimeConfigurationError, match="STORE_PATH"):
        load_private_runtime_settings({})


def test_runtime_refuses_missing_trust_ledger_without_recreating_it() -> None:
    root = Path.home() / ".nepsis" / "pytest-private-runtime" / uuid.uuid4().hex
    ledger_path = root / "receipt-anchor-events.sqlite"
    configured = replace(settings(), trust_anchor_ledger_path=ledger_path)
    try:
        with pytest.raises(
            PrivateRuntimeConfigurationError, match="existing.*required"
        ):
            build_private_runtime_app(
                configured,
                store=CanonicalRunStore.in_memory(),
                profile_registry=GovernanceProfileRegistry.in_memory(),
                private_key=Ed25519PrivateKey.from_private_bytes(
                    bytes(range(1, 33))
                ),
            )
        assert not ledger_path.exists()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_injected_runtime_enables_private_actualization_without_public_mvp() -> None:
    app = build_private_runtime_app(
        settings(),
        store=CanonicalRunStore.in_memory(),
        profile_registry=GovernanceProfileRegistry.in_memory(),
        trust_anchor_registry=ReceiptTrustAnchorRegistry.in_memory(),
        private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33))),
    )
    http = TestClient(app)

    assert http.get("/v1/mvp").status_code == 404
    assert http.get("/openapi.json").status_code == 404
    assert http.get("/v1/operator-runs/run-missing/snapshot").status_code == 401
    authorized = http.get(
        "/v1/operator-runs/run-missing/snapshot",
        headers={"Authorization": f"Bearer {'m' * 32}"},
    )
    assert authorized.status_code == 404

    proposal_hash = "e" * 64
    disposition = http.post(
        "/v1/operator-runs/run-missing/operator-actions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={
            "action_type": "record_operator_disposition",
            "capability": "submit_operator_disposition",
            "capability_id": "capability:operator:local",
            "confirmation": {
                "confirmed": True,
                "confirmed_at": "2026-07-12T18:00:00.000Z",
                "consequence_acknowledged": True,
                "rationale": "Reviewed.",
            },
            "created_at": "2026-07-12T18:00:00.000Z",
            "effective_policy_hash": "a" * 64,
            "expected_head_event_hash": "b" * 64,
            "expected_head_sequence": 0,
            "idempotency_key": "operator-001",
            "operator_governance_profile_hash": "c" * 64,
            "payload": {
                "disposition": "defer",
                "operator_visible_proposal_hash": proposal_hash,
                "run_id": "run-missing",
            },
            "run_id": "run-missing",
            "session_governance_snapshot_hash": "d" * 64,
            "trusted_adapter_intent_id": "adapter-intent-001",
        },
    )
    assert disposition.status_code == 404

    incomplete_actualization = http.post(
        "/v1/operator-runs/run-missing/operator-actions",
        headers={"Authorization": f"Bearer {'o' * 32}"},
        json={
            "action_type": "release_still",
            "capability": "release_still",
            "capability_id": "capability:operator:local",
            "confirmation": {
                "confirmed": True,
                "confirmed_at": "2026-07-12T18:00:00.000Z",
                "consequence_acknowledged": True,
                "rationale": "Reviewed.",
            },
            "created_at": "2026-07-12T18:00:00.000Z",
            "run_id": "run-missing",
        },
    )
    assert incomplete_actualization.status_code == 400


def test_runtime_startup_pins_registry_and_refuses_revocation_or_replacement() -> None:
    registry = ReceiptTrustAnchorRegistry.in_memory()
    key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    app = build_private_runtime_app(
        settings(),
        store=CanonicalRunStore.in_memory(),
        profile_registry=GovernanceProfileRegistry.in_memory(),
        trust_anchor_registry=registry,
        private_key=key,
    )
    assert app.state.receipt_trust_anchor_registry.export_ledger()["status"] == (
        "active"
    )

    replacement_key = Ed25519PrivateKey.from_private_bytes(bytes(range(2, 34)))
    with pytest.raises(PrivateRuntimeConfigurationError, match="rotation is unsupported"):
        build_private_runtime_app(
            settings(),
            store=CanonicalRunStore.in_memory(),
            profile_registry=GovernanceProfileRegistry.in_memory(),
            trust_anchor_registry=registry,
            private_key=replacement_key,
        )

    anchor_event = registry.export_ledger()["events"][0]
    registry.revoke_active_anchor(
        expected_key_id=anchor_event["payload"]["trust_anchor"]["key_id"],
        revoked_at="2026-07-12T20:00:00.000Z",
        reason="Test revocation.",
        idempotency_key="runtime-revocation-001",
    )
    with pytest.raises(PrivateRuntimeConfigurationError, match="is revoked"):
        build_private_runtime_app(
            settings(),
            store=CanonicalRunStore.in_memory(),
            profile_registry=GovernanceProfileRegistry.in_memory(),
            trust_anchor_registry=registry,
            private_key=key,
        )
    registry.close()
