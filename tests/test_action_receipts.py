from __future__ import annotations

from copy import deepcopy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from nepsis_cgn.contracts.canonical_json import canonical_bytes
from nepsis_cgn.verification.receipts import (
    ACTION_RECEIPT_ALGORITHM,
    ActionReceiptError,
    action_receipt_signing_bytes,
    build_trust_anchor,
    export_public_key,
    key_id_for_public_key,
    sign_action_receipt,
    validate_trust_anchor,
    verify_action_receipt,
)


PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
PUBLIC_KEY = PRIVATE_KEY.public_key()
OTHER_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(33, 65)))

ACTIVATED_AT = "2026-07-01T00:00:00.000Z"
SIGNED_AT = "2026-07-12T18:00:00.000Z"
REVOKED_AT = "2026-08-01T00:00:00.000Z"


def _receipt() -> dict[str, object]:
    return {
        "action_receipt_schema_version": "nepsis.action_receipt@0.1.0",
        "action_id": "action_001",
        "run_id": "run_001",
        "sequence": 7,
        "outcome": "accepted",
        "event_hash": "a" * 64,
    }


def _anchor(*, revoked_at: str | None = None) -> dict[str, object]:
    return build_trust_anchor(
        PUBLIC_KEY,
        activated_at=ACTIVATED_AT,
        revoked_at=revoked_at,
    )


def test_signs_neutral_canonical_bytes_and_verifies_with_public_key() -> None:
    receipt = _receipt()
    anchor = _anchor()

    signed = sign_action_receipt(
        receipt,
        private_key=PRIVATE_KEY,
        trust_anchor=anchor,
        signing_at=SIGNED_AT,
    )

    assert "signature" not in receipt
    assert signed["signature"]["algorithm"] == ACTION_RECEIPT_ALGORITHM
    assert signed["signature"]["key_id"] == key_id_for_public_key(PUBLIC_KEY)
    assert anchor["public_key"] == export_public_key(PUBLIC_KEY)
    assert action_receipt_signing_bytes(signed) == canonical_bytes(
        {key: value for key, value in signed.items() if key != "signature"}
    )
    assert verify_action_receipt(signed, public_key=PUBLIC_KEY, trust_anchor=anchor)


def test_semantically_equal_receipts_produce_the_same_signature() -> None:
    left = _receipt()
    right = {key: left[key] for key in reversed(left)}
    anchor = _anchor()

    signed_left = sign_action_receipt(
        left,
        private_key=PRIVATE_KEY,
        trust_anchor=anchor,
        signing_at=SIGNED_AT,
    )
    signed_right = sign_action_receipt(
        right,
        private_key=PRIVATE_KEY,
        trust_anchor=anchor,
        signing_at=SIGNED_AT,
    )

    assert signed_left["signature"] == signed_right["signature"]


def test_tamper_unknown_algorithm_and_key_mismatch_fail_closed() -> None:
    anchor = _anchor()
    signed = sign_action_receipt(
        _receipt(),
        private_key=PRIVATE_KEY,
        trust_anchor=anchor,
        signing_at=SIGNED_AT,
    )

    tampered = deepcopy(signed)
    tampered["outcome"] = "refused"
    assert not verify_action_receipt(
        tampered, public_key=PUBLIC_KEY, trust_anchor=anchor
    )

    unknown_algorithm = deepcopy(signed)
    unknown_algorithm["signature"]["algorithm"] = "ed448"
    assert not verify_action_receipt(
        unknown_algorithm, public_key=PUBLIC_KEY, trust_anchor=anchor
    )

    key_mismatch = deepcopy(signed)
    key_mismatch["signature"]["key_id"] = key_id_for_public_key(
        OTHER_PRIVATE_KEY.public_key()
    )
    assert not verify_action_receipt(
        key_mismatch, public_key=PUBLIC_KEY, trust_anchor=anchor
    )
    assert not verify_action_receipt(
        signed,
        public_key=OTHER_PRIVATE_KEY.public_key(),
        trust_anchor=anchor,
    )


def test_anchor_activation_and_revocation_are_evaluated_at_signing_time() -> None:
    anchor = _anchor(revoked_at=REVOKED_AT)

    with pytest.raises(ActionReceiptError, match="not active"):
        sign_action_receipt(
            _receipt(),
            private_key=PRIVATE_KEY,
            trust_anchor=anchor,
            signing_at="2026-06-30T23:59:59.999Z",
        )

    signed = sign_action_receipt(
        _receipt(),
        private_key=PRIVATE_KEY,
        trust_anchor=anchor,
        signing_at=SIGNED_AT,
    )
    assert verify_action_receipt(signed, public_key=PUBLIC_KEY, trust_anchor=anchor)

    revoked_receipt = sign_action_receipt(
        _receipt(),
        private_key=PRIVATE_KEY,
        trust_anchor=_anchor(),
        signing_at=REVOKED_AT,
    )
    assert not verify_action_receipt(
        revoked_receipt,
        public_key=PUBLIC_KEY,
        trust_anchor=anchor,
    )
    with pytest.raises(ActionReceiptError, match="revoked"):
        sign_action_receipt(
            _receipt(),
            private_key=PRIVATE_KEY,
            trust_anchor=anchor,
            signing_at=REVOKED_AT,
        )


def test_trust_anchor_rejects_unknown_algorithm_and_key_id_mismatch() -> None:
    anchor = _anchor()

    unknown_algorithm = deepcopy(anchor)
    unknown_algorithm["algorithm"] = "ed448"
    with pytest.raises(ActionReceiptError, match="algorithm mismatch"):
        validate_trust_anchor(unknown_algorithm, signing_at=SIGNED_AT)

    key_mismatch = deepcopy(anchor)
    key_mismatch["key_id"] = "ed25519:" + "0" * 64
    with pytest.raises(ActionReceiptError, match="key_id mismatch"):
        validate_trust_anchor(key_mismatch, signing_at=SIGNED_AT)


def test_signing_key_must_match_explicit_trust_anchor() -> None:
    with pytest.raises(ActionReceiptError, match="signing key"):
        sign_action_receipt(
            _receipt(),
            private_key=OTHER_PRIVATE_KEY,
            trust_anchor=_anchor(),
            signing_at=SIGNED_AT,
        )
