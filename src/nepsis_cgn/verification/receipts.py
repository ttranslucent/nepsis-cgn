from __future__ import annotations

import base64
import binascii
import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from nepsis_cgn.contracts.canonical_json import CanonicalJsonError, canonical_bytes


ACTION_RECEIPT_ALGORITHM = "ed25519"
TRUST_ANCHOR_SCHEMA_VERSION = "nepsis.action_receipt_trust_anchor@0.1.0"

_SIGNATURE_FIELDS = {"algorithm", "key_id", "value"}
_TRUST_ANCHOR_REQUIRED_FIELDS = {
    "action_receipt_trust_anchor_schema_version",
    "algorithm",
    "key_id",
    "public_key",
    "activated_at",
}
_TRUST_ANCHOR_OPTIONAL_FIELDS = {"revoked_at"}


class ActionReceiptError(ValueError):
    """Raised when a receipt or trust anchor is not safe to use."""


def key_id_for_public_key(public_key: Ed25519PublicKey) -> str:
    """Derive the stable key identifier from the raw Ed25519 public key."""

    raw_public_key = _raw_public_key(public_key)
    return f"ed25519:{hashlib.sha256(raw_public_key).hexdigest()}"


def export_public_key(public_key: Ed25519PublicKey) -> str:
    """Export a raw Ed25519 public key as canonical unpadded base64url."""

    return _encode_base64url(_raw_public_key(public_key))


def build_trust_anchor(
    public_key: Ed25519PublicKey,
    *,
    activated_at: str,
    revoked_at: str | None = None,
) -> dict[str, Any]:
    """Build and structurally validate an explicit trust-anchor record."""

    record: dict[str, Any] = {
        "action_receipt_trust_anchor_schema_version": TRUST_ANCHOR_SCHEMA_VERSION,
        "algorithm": ACTION_RECEIPT_ALGORITHM,
        "key_id": key_id_for_public_key(public_key),
        "public_key": export_public_key(public_key),
        "activated_at": activated_at,
    }
    if revoked_at is not None:
        record["revoked_at"] = revoked_at
    validate_trust_anchor(record, signing_at=activated_at)
    return record


def validate_trust_anchor(
    trust_anchor: Mapping[str, Any],
    *,
    signing_at: str,
) -> None:
    """Validate anchor structure and whether it authorized one signing time."""

    if not isinstance(trust_anchor, Mapping):
        raise ActionReceiptError("trust anchor must be an object")
    fields = set(trust_anchor)
    missing = _TRUST_ANCHOR_REQUIRED_FIELDS - fields
    unknown = fields - _TRUST_ANCHOR_REQUIRED_FIELDS - _TRUST_ANCHOR_OPTIONAL_FIELDS
    if missing:
        raise ActionReceiptError(
            f"trust anchor missing required fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise ActionReceiptError(
            f"trust anchor has unknown fields: {', '.join(sorted(unknown))}"
        )
    if (
        trust_anchor.get("action_receipt_trust_anchor_schema_version")
        != TRUST_ANCHOR_SCHEMA_VERSION
    ):
        raise ActionReceiptError("trust anchor schema version mismatch")
    if trust_anchor.get("algorithm") != ACTION_RECEIPT_ALGORITHM:
        raise ActionReceiptError("trust anchor algorithm mismatch")

    public_key = _public_key_from_export(trust_anchor.get("public_key"))
    expected_key_id = key_id_for_public_key(public_key)
    if trust_anchor.get("key_id") != expected_key_id:
        raise ActionReceiptError("trust anchor key_id mismatch")

    activated_at = _parse_timestamp(trust_anchor.get("activated_at"), "activated_at")
    evaluated_at = _parse_timestamp(signing_at, "signing_at")
    if evaluated_at < activated_at:
        raise ActionReceiptError("trust anchor was not active at signing time")

    revoked_value = trust_anchor.get("revoked_at")
    if revoked_value is not None:
        revoked_at = _parse_timestamp(revoked_value, "revoked_at")
        if revoked_at <= activated_at:
            raise ActionReceiptError("trust anchor revoked_at must follow activated_at")
        if evaluated_at >= revoked_at:
            raise ActionReceiptError("trust anchor was revoked at signing time")

    try:
        canonical_bytes(dict(trust_anchor))
    except CanonicalJsonError as exc:
        raise ActionReceiptError(f"trust anchor is not canonical: {exc}") from exc


def public_key_from_trust_anchor(
    trust_anchor: Mapping[str, Any],
) -> Ed25519PublicKey:
    """Load the pinned public key after validating the neutral anchor record."""

    if not isinstance(trust_anchor, Mapping):
        raise ActionReceiptError("trust anchor must be an object")
    activated_at = trust_anchor.get("activated_at")
    validate_trust_anchor(trust_anchor, signing_at=str(activated_at))
    return _public_key_from_export(trust_anchor.get("public_key"))


def action_receipt_signing_bytes(receipt: Mapping[str, Any]) -> bytes:
    """Return neutral canonical receipt bytes without the signature block."""

    if not isinstance(receipt, Mapping):
        raise ActionReceiptError("action receipt must be an object")
    unsigned = {key: deepcopy(value) for key, value in receipt.items() if key != "signature"}
    try:
        return canonical_bytes(unsigned)
    except CanonicalJsonError as exc:
        raise ActionReceiptError(f"action receipt is not canonical: {exc}") from exc


def sign_action_receipt(
    receipt: Mapping[str, Any],
    *,
    private_key: Ed25519PrivateKey,
    trust_anchor: Mapping[str, Any],
    signing_at: str,
) -> dict[str, Any]:
    """Sign a receipt only when the explicit trust anchor authorizes the key."""

    if not isinstance(receipt, Mapping):
        raise ActionReceiptError("action receipt must be an object")
    if "signature" in receipt:
        raise ActionReceiptError("action receipt is already signed")
    existing_signing_at = receipt.get("signed_at")
    if existing_signing_at is not None and existing_signing_at != signing_at:
        raise ActionReceiptError("action receipt signed_at mismatch")

    public_key = private_key.public_key()
    validate_trust_anchor(trust_anchor, signing_at=signing_at)
    if trust_anchor.get("key_id") != key_id_for_public_key(public_key):
        raise ActionReceiptError("signing key does not match trust anchor")
    if trust_anchor.get("public_key") != export_public_key(public_key):
        raise ActionReceiptError("signing public key does not match trust anchor")

    signed_receipt = deepcopy(dict(receipt))
    signed_receipt["signed_at"] = signing_at
    signature = private_key.sign(action_receipt_signing_bytes(signed_receipt))
    signed_receipt["signature"] = {
        "algorithm": ACTION_RECEIPT_ALGORITHM,
        "key_id": key_id_for_public_key(public_key),
        "value": _encode_base64url(signature),
    }
    return signed_receipt


def verify_action_receipt(
    receipt: Mapping[str, Any],
    *,
    public_key: Ed25519PublicKey,
    trust_anchor: Mapping[str, Any],
) -> bool:
    """Verify signature, public key, key ID, and anchor status fail closed."""

    try:
        if not isinstance(receipt, Mapping):
            return False
        signature = receipt.get("signature")
        if not isinstance(signature, Mapping) or set(signature) != _SIGNATURE_FIELDS:
            return False
        if signature.get("algorithm") != ACTION_RECEIPT_ALGORITHM:
            return False
        expected_key_id = key_id_for_public_key(public_key)
        if signature.get("key_id") != expected_key_id:
            return False
        signing_at = receipt.get("signed_at")
        if not isinstance(signing_at, str):
            return False
        validate_trust_anchor(trust_anchor, signing_at=signing_at)
        if trust_anchor.get("key_id") != expected_key_id:
            return False
        if trust_anchor.get("public_key") != export_public_key(public_key):
            return False

        signature_bytes = _decode_base64url(signature.get("value"), expected_length=64)
        public_key.verify(signature_bytes, action_receipt_signing_bytes(receipt))
        return True
    except (
        ActionReceiptError,
        CanonicalJsonError,
        InvalidSignature,
        TypeError,
        ValueError,
        binascii.Error,
    ):
        return False


def _raw_public_key(public_key: Ed25519PublicKey) -> bytes:
    if not isinstance(public_key, Ed25519PublicKey):
        raise ActionReceiptError("public_key must be an Ed25519 public key")
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _public_key_from_export(value: Any) -> Ed25519PublicKey:
    raw_public_key = _decode_base64url(value, expected_length=32)
    try:
        return Ed25519PublicKey.from_public_bytes(raw_public_key)
    except ValueError as exc:
        raise ActionReceiptError("trust anchor public_key is invalid") from exc


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_base64url(value: Any, *, expected_length: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise ActionReceiptError("base64url value must be a non-empty string")
    try:
        raw = base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, binascii.Error) as exc:
        raise ActionReceiptError("base64url value is invalid") from exc
    if len(raw) != expected_length or _encode_base64url(raw) != value:
        raise ActionReceiptError("base64url value has invalid length or encoding")
    return raw


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise ActionReceiptError(f"{field} must be a UTC timestamp string")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ActionReceiptError(
            f"{field} must use YYYY-MM-DDTHH:MM:SS.mmmZ"
        ) from exc
    if len(value) != 24:
        raise ActionReceiptError(f"{field} must use exactly three fractional digits")
    return parsed.replace(tzinfo=timezone.utc)


__all__ = [
    "ACTION_RECEIPT_ALGORITHM",
    "TRUST_ANCHOR_SCHEMA_VERSION",
    "ActionReceiptError",
    "action_receipt_signing_bytes",
    "build_trust_anchor",
    "export_public_key",
    "key_id_for_public_key",
    "public_key_from_trust_anchor",
    "sign_action_receipt",
    "validate_trust_anchor",
    "verify_action_receipt",
]
