from __future__ import annotations

import hashlib

import pytest

from nepsis_cgn.contracts.canonical_json import (
    CanonicalJsonError,
    canonical_bytes,
    canonical_hash,
    canonical_json,
)


SEMANTIC_VALUE = {
    "patch_id": "patch_001",
    "target_path": "frame.text",
    "operation_type": "replace",
    "created_at": "2026-07-07T12:34:56.789Z",
    "operator_note": "Cafe\u0301 high-risk\nline",
    "amount_cents": 150,
    "tags": ["red", "blue"],
    "nested": {"zeta": "last", "alpha": "first"},
}

EXPECTED_CANONICAL = (
    '{"amount_cents":150,"created_at":"2026-07-07T12:34:56.789Z",'
    '"nested":{"alpha":"first","zeta":"last"},'
    '"operation_type":"replace","operator_note":"Café high-risk\\u000aline",'
    '"patch_id":"patch_001","tags":["red","blue"],"target_path":"frame.text"}'
)
EXPECTED_HASH = hashlib.sha256(EXPECTED_CANONICAL.encode("utf-8")).hexdigest()


def test_same_semantic_value_has_neutral_expected_bytes_and_hash() -> None:
    equivalent = {
        "target_path": "frame.text",
        "tags": ["red", "blue"],
        "operator_note": "Café high-risk\nline",
        "patch_id": "patch_001",
        "operation_type": "replace",
        "nested": {"alpha": "first", "zeta": "last"},
        "created_at": "2026-07-07T12:34:56.789Z",
        "amount_cents": 150,
    }

    assert canonical_json(SEMANTIC_VALUE) == EXPECTED_CANONICAL
    assert canonical_bytes(equivalent) == EXPECTED_CANONICAL.encode("utf-8")
    assert canonical_hash(equivalent) == EXPECTED_HASH


def test_mutation_changes_hash() -> None:
    modified = dict(SEMANTIC_VALUE)
    modified["amount_cents"] = 151
    assert canonical_hash(modified) != EXPECTED_HASH


@pytest.mark.parametrize(
    "value",
    [
        {"field": None},
        {"field": 1.5},
        {"field": 9007199254740992},
        {"field": -9007199254740992},
        {"amount": "1.50"},
        {"created_at": "2026-07-07T12:34:56.7Z"},
        {"café": "value"},
    ],
)
def test_rejects_values_outside_neutral_policy(value: dict[str, object]) -> None:
    with pytest.raises(CanonicalJsonError):
        canonical_json(value)
