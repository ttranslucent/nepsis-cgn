from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator
import pytest

from nepsis_cgn.canonical_runs.import_pilot import (
    ImportConflict,
    ImportPilotError,
    ImportPilotStore,
    _require_sealed_subject,
)
from nepsis_cgn.contracts.canonical_json import canonical_bytes
from nepsis_cgn.contracts.canonical_run import ActorContext
from nepsis_cgn.verification.receipts import build_trust_anchor


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "interop" / "golden" / "nepsis.interop_bundle@0.2.0.json"
IMPORTED_AT = "2026-07-12T18:00:00.000Z"
PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
ANCHOR = build_trust_anchor(
    PRIVATE_KEY.public_key(), activated_at="2026-07-01T00:00:00.000Z"
)


def bundle() -> dict:
    value = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def actor() -> ActorContext:
    return ActorContext(
        actor_id="validator:mc-import-pilot",
        provenance_class="validator",
        capability_id="cap-import-pilot",
        capabilities=frozenset({"import_sealed_bundle"}),
    )


def test_verified_sealed_bundle_import_is_immutable_and_replay_stable() -> None:
    store = ImportPilotStore.in_memory(
        private_key=PRIVATE_KEY, trust_anchor=ANCHOR
    )
    first = store.import_sealed_bundle(
        bundle=bundle(),
        actor=actor(),
        idempotency_key="import-001",
        imported_at=IMPORTED_AT,
    )
    replay = store.import_sealed_bundle(
        bundle=bundle(),
        actor=actor(),
        idempotency_key="import-001",
        imported_at=IMPORTED_AT,
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert canonical_bytes(dict(first.receipt)) == canonical_bytes(
        dict(replay.receipt)
    )
    assert first.receipt["read_only"] is True
    assert first.receipt["source_session_id"] == "session_markdown_golden"
    assert store.verify_receipt(first.receipt)
    schema = json.loads(
        (
            ROOT
            / "interop"
            / "schemas"
            / "nepsis.import_receipt@0.1.0.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(dict(first.receipt))
    imported = store.get_import("session_markdown_golden")
    assert imported["status"] == "read_only"
    assert imported["receipt"] == first.receipt
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        store._db.execute(
            "UPDATE mc_sealed_imports SET status = 'read_only'"
        )


def test_restart_and_new_delivery_key_return_the_same_signed_receipt(
    tmp_path: Path,
) -> None:
    path = tmp_path / "import-pilot.sqlite"
    first_store = ImportPilotStore.open(
        path, private_key=PRIVATE_KEY, trust_anchor=ANCHOR
    )
    first = first_store.import_sealed_bundle(
        bundle=bundle(),
        actor=actor(),
        idempotency_key="import-before-restart",
        imported_at=IMPORTED_AT,
    )
    first_store.close()

    reopened = ImportPilotStore.open(
        path, private_key=PRIVATE_KEY, trust_anchor=ANCHOR
    )
    replay = reopened.import_sealed_bundle(
        bundle=bundle(),
        actor=actor(),
        idempotency_key="import-after-restart",
        imported_at=IMPORTED_AT,
    )
    assert replay.replayed is True
    assert replay.receipt == first.receipt
    reopened.close()


def test_idempotency_conflict_and_non_import_actor_fail_closed() -> None:
    store = ImportPilotStore.in_memory(
        private_key=PRIVATE_KEY, trust_anchor=ANCHOR
    )
    store.import_sealed_bundle(
        bundle=bundle(),
        actor=actor(),
        idempotency_key="import-conflict",
        imported_at=IMPORTED_AT,
    )
    with pytest.raises(ImportConflict):
        store.import_sealed_bundle(
            bundle=bundle(),
            actor=actor(),
            idempotency_key="import-conflict",
            imported_at="2026-07-12T18:00:01.000Z",
        )

    operator = ActorContext(
        actor_id="operator:local",
        provenance_class="operator",
        capability_id="cap-operator",
        capabilities=frozenset({"read_snapshot"}),
    )
    with pytest.raises(ImportPilotError, match="import-service"):
        store.import_sealed_bundle(
            bundle=bundle(),
            actor=operator,
            idempotency_key="operator-import",
            imported_at=IMPORTED_AT,
        )


def test_partial_or_unsealed_subject_is_refused_before_persistence() -> None:
    partial = deepcopy(bundle()["subject"])
    partial["profile"] = "integrity_only"
    partial["guarantee_level"] = "integrity_only"
    partial["redacted_sequences"] = [4]
    with pytest.raises(ImportPilotError, match="full reconstruction"):
        _require_sealed_subject(partial)

    active = deepcopy(bundle()["subject"])
    active["phase_projection"]["projected_phase"] = "decision_ready"
    with pytest.raises(ImportPilotError, match="exported"):
        _require_sealed_subject(active)
