from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import sqlite3
import uuid

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator
import pytest
from referencing import Registry, Resource

from nepsis_cgn.canonical_runs.trust_anchor_registry import (
    TRUST_ANCHOR_LIFECYCLE_EVENT_VERSION,
    ReceiptTrustAnchorRegistry,
    TrustAnchorRegistryError,
    TrustAnchorRevokedError,
)
from nepsis_cgn.contracts.canonical_json import canonical_hash, canonical_json
from nepsis_cgn.verification.receipts import build_trust_anchor


ROOT = Path(__file__).resolve().parents[1]
ACTIVATED_AT = "2026-07-01T00:00:00.000Z"
REVOKED_AT = "2026-07-12T20:00:00.000Z"
PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
OTHER_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(2, 34)))


@pytest.fixture
def ledger_path() -> Path:
    root = (
        Path.home()
        / ".nepsis"
        / "pytest-trust-anchor-ledgers"
        / uuid.uuid4().hex
    )
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root / "anchor-events.sqlite"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def anchor(*, activated_at: str = ACTIVATED_AT) -> dict[str, object]:
    return build_trust_anchor(
        PRIVATE_KEY.public_key(), activated_at=activated_at
    )


def test_activation_is_canonical_and_restart_verifies_identical_chain(
    ledger_path: Path,
) -> None:
    first = ReceiptTrustAnchorRegistry.initialize(ledger_path)
    active = first.ensure_active_anchor(anchor())
    before = first.export_ledger()
    first.close()

    restarted = ReceiptTrustAnchorRegistry.open_existing(ledger_path)
    reread = restarted.ensure_active_anchor(anchor())
    after = restarted.export_ledger()
    restarted.close()

    assert active == reread == anchor()
    assert before == after
    assert after["status"] == "active"
    assert len(after["events"]) == 1
    activation = after["events"][0]
    assert activation["event_type"] == "trust_anchor_activated"
    assert activation["payload"]["trust_anchor"] == anchor()
    assert activation["payload"]["trust_anchor_hash"] == canonical_hash(anchor())
    assert canonical_json(activation) == canonical_json(after["events"][0])
    _validate_event_schema(activation)


def test_existing_empty_ledger_refuses_missing_activation(ledger_path: Path) -> None:
    sqlite3.connect(ledger_path).close()
    with pytest.raises(TrustAnchorRegistryError, match="not explicitly initialized"):
        ReceiptTrustAnchorRegistry.open_existing(ledger_path)


def test_missing_ledger_is_not_recreated_on_restart(ledger_path: Path) -> None:
    registry = ReceiptTrustAnchorRegistry.initialize(ledger_path)
    registry.ensure_active_anchor(anchor())
    registry.close()
    ledger_path.unlink()

    with pytest.raises(TrustAnchorRegistryError, match="existing.*required"):
        ReceiptTrustAnchorRegistry.open_existing(ledger_path)

    assert not ledger_path.exists()


def test_explicit_initialization_refuses_existing_path(ledger_path: Path) -> None:
    registry = ReceiptTrustAnchorRegistry.initialize(ledger_path)
    registry.ensure_active_anchor(anchor())
    registry.close()

    with pytest.raises(TrustAnchorRegistryError, match="already exists"):
        ReceiptTrustAnchorRegistry.initialize(ledger_path)


def test_restart_refuses_key_or_activation_timestamp_mismatch(
    ledger_path: Path,
) -> None:
    registry = ReceiptTrustAnchorRegistry.initialize(ledger_path)
    registry.ensure_active_anchor(anchor())
    registry.close()

    restarted = ReceiptTrustAnchorRegistry.open_existing(ledger_path)
    replacement = build_trust_anchor(
        OTHER_PRIVATE_KEY.public_key(), activated_at=ACTIVATED_AT
    )
    with pytest.raises(TrustAnchorRegistryError, match="rotation is unsupported"):
        restarted.ensure_active_anchor(replacement)
    with pytest.raises(TrustAnchorRegistryError, match="activation timestamp"):
        restarted.ensure_active_anchor(
            anchor(activated_at="2026-07-02T00:00:00.000Z")
        )
    restarted.close()


def test_revocation_is_append_only_idempotent_and_blocks_future_startup(
    ledger_path: Path,
) -> None:
    registry = ReceiptTrustAnchorRegistry.initialize(ledger_path)
    active = registry.ensure_active_anchor(anchor())
    first = registry.revoke_active_anchor(
        expected_key_id=str(active["key_id"]),
        revoked_at=REVOKED_AT,
        reason="Local signing key custody is no longer trusted.",
        idempotency_key="revoke-local-anchor-001",
    )
    replay = registry.revoke_active_anchor(
        expected_key_id=str(active["key_id"]),
        revoked_at=REVOKED_AT,
        reason="Local signing key custody is no longer trusted.",
        idempotency_key="revoke-local-anchor-001",
    )
    exported = registry.export_ledger()
    registry.close()

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.event == first.event
    assert exported["status"] == "revoked"
    assert [event["event_type"] for event in exported["events"]] == [
        "trust_anchor_activated",
        "trust_anchor_revoked",
    ]
    _validate_event_schema(dict(first.event))

    restarted = ReceiptTrustAnchorRegistry.open_existing(ledger_path)
    with pytest.raises(TrustAnchorRevokedError, match="is revoked"):
        restarted.ensure_active_anchor(anchor())
    with pytest.raises(TrustAnchorRevokedError, match="already revoked"):
        restarted.revoke_active_anchor(
            expected_key_id=str(active["key_id"]),
            revoked_at="2026-07-12T21:00:00.000Z",
            reason="Different bytes must not replay.",
            idempotency_key="revoke-local-anchor-002",
        )
    restarted.close()


def test_sqlite_guards_update_and_delete(ledger_path: Path) -> None:
    registry = ReceiptTrustAnchorRegistry.initialize(ledger_path)
    registry.ensure_active_anchor(anchor())
    registry.close()

    raw = sqlite3.connect(ledger_path)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        raw.execute(
            "UPDATE receipt_trust_anchor_events SET event_hash = ? WHERE sequence = 0",
            ("0" * 64,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        raw.execute("DELETE FROM receipt_trust_anchor_events WHERE sequence = 0")
    raw.close()


def test_restart_detects_noncanonical_or_hash_tamper(ledger_path: Path) -> None:
    registry = ReceiptTrustAnchorRegistry.initialize(ledger_path)
    registry.ensure_active_anchor(anchor())
    event = registry.export_ledger()["events"][0]
    registry.close()

    raw = sqlite3.connect(ledger_path)
    raw.execute("DROP TRIGGER receipt_trust_anchor_events_no_update")
    raw.execute(
        "UPDATE receipt_trust_anchor_events SET event_json = ? WHERE sequence = 0",
        (json.dumps(event, indent=2),),
    )
    raw.execute(
        """
        CREATE TRIGGER receipt_trust_anchor_events_no_update
        BEFORE UPDATE ON receipt_trust_anchor_events
        BEGIN
            SELECT RAISE(ABORT, 'receipt trust-anchor events are append-only');
        END
        """
    )
    raw.commit()
    raw.close()

    with pytest.raises(TrustAnchorRegistryError, match="bytes are not canonical"):
        ReceiptTrustAnchorRegistry.open_existing(ledger_path)


def test_restart_probes_guards_instead_of_trusting_trigger_names(
    ledger_path: Path,
) -> None:
    registry = ReceiptTrustAnchorRegistry.initialize(ledger_path)
    registry.ensure_active_anchor(anchor())
    registry.close()

    raw = sqlite3.connect(ledger_path)
    raw.execute("DROP TRIGGER receipt_trust_anchor_events_no_update")
    raw.execute(
        """
        CREATE TRIGGER receipt_trust_anchor_events_no_update
        BEFORE UPDATE ON receipt_trust_anchor_events
        BEGIN
            SELECT 1;
        END
        """
    )
    raw.commit()
    raw.close()

    with pytest.raises(TrustAnchorRegistryError, match="update guard is missing"):
        ReceiptTrustAnchorRegistry.open_existing(ledger_path)


def test_second_valid_activation_is_refused_as_unsupported_rotation(
    ledger_path: Path,
) -> None:
    registry = ReceiptTrustAnchorRegistry.initialize(ledger_path)
    registry.ensure_active_anchor(anchor())
    first_event = registry.export_ledger()["events"][0]
    registry.close()

    replacement = build_trust_anchor(
        OTHER_PRIVATE_KEY.public_key(), activated_at=ACTIVATED_AT
    )
    replacement_hash = canonical_hash(replacement)
    payload = {
        "activation_id": f"anchor-activation:{replacement_hash}",
        "action_receipt_trust_anchor_activation_schema_version": (
            "nepsis.action_receipt_trust_anchor_activation@0.1.0"
        ),
        "trust_anchor": replacement,
        "trust_anchor_hash": replacement_hash,
    }
    envelope = {
        "actor_id": "system:nepsis.receipt_trust_anchor_registry@0.1.0",
        "created_at": ACTIVATED_AT,
        "event_type": "trust_anchor_activated",
        "idempotency_key": payload["activation_id"],
        "payload_hash": canonical_hash(payload),
        "prev_event_hash": first_event["event_hash"],
        "provenance_class": "system",
        "sequence": 1,
        "trust_anchor_lifecycle_event_schema_version": (
            TRUST_ANCHOR_LIFECYCLE_EVENT_VERSION
        ),
    }
    second_event = {
        **envelope,
        "event_hash": canonical_hash(envelope),
        "payload": payload,
    }
    raw = sqlite3.connect(ledger_path)
    raw.execute(
        """
        INSERT INTO receipt_trust_anchor_events
            (sequence, event_hash, event_json)
        VALUES (?, ?, ?)
        """,
        (1, second_event["event_hash"], canonical_json(second_event)),
    )
    raw.commit()
    raw.close()

    with pytest.raises(TrustAnchorRegistryError, match="rotation is unsupported"):
        ReceiptTrustAnchorRegistry.open_existing(ledger_path)


def test_lifecycle_export_is_a_copy_not_a_mutable_registry_view() -> None:
    registry = ReceiptTrustAnchorRegistry.in_memory()
    registry.ensure_active_anchor(anchor())
    exported = registry.export_ledger()
    mutated = deepcopy(exported)
    mutated["events"][0]["payload"]["trust_anchor"]["key_id"] = "forged"

    assert registry.export_ledger() == exported
    registry.close()


def _validate_event_schema(event: dict[str, object]) -> None:
    path = (
        ROOT
        / "interop"
        / "schemas"
        / "nepsis.action_receipt_trust_anchor_lifecycle_event@0.1.0.schema.json"
    )
    schema = json.loads(path.read_text(encoding="utf-8"))
    anchor_schema = json.loads(
        (
            ROOT
            / "interop"
            / "schemas"
            / "nepsis.action_receipt_trust_anchor@0.1.0.schema.json"
        ).read_text(encoding="utf-8")
    )
    registry = Registry().with_resource(
        anchor_schema["$id"], Resource.from_contents(anchor_schema)
    )
    Draft202012Validator(schema, registry=registry).validate(event)
