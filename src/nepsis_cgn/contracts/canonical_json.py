from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any


class CanonicalJsonError(ValueError):
    """Raised when a value cannot be represented by the neutral policy."""


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")
_DECIMAL_STRING_RE = re.compile(r"^[+-]?\d+\.\d+$")
_JS_SAFE_INTEGER_MAX = 9007199254740991
_JS_SAFE_INTEGER_MIN = -9007199254740991

CANONICAL_JSON_VERSION = "nepsis.canonical_json@0.1.0"

_CANONICAL_JSON_POLICY_DOCUMENT = {
    "version": CANONICAL_JSON_VERSION,
    "encoding": "utf_8",
    "unicode_normalization": "nfc",
    "key_rule": "ascii_snake_case_byte_order",
    "escaping": "minimal_required_json_escapes_u_four_lowercase_hex",
    "nulls": "banned",
    "floats": "banned",
    "decimal_strings": "banned",
    "timestamp_format": "yyyy_mm_ddthh_mm_ss_mmmz",
}


def canonical_json(value: Any) -> str:
    return _emit(value, key=None)


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_json_policy_hash() -> str:
    return canonical_hash(_CANONICAL_JSON_POLICY_DOCUMENT)


def _emit(value: Any, *, key: str | None) -> str:
    if value is None:
        raise CanonicalJsonError("null values are not canonical")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if value < _JS_SAFE_INTEGER_MIN or value > _JS_SAFE_INTEGER_MAX:
            raise CanonicalJsonError("integer exceeds JavaScript safe integer range")
        return str(value)
    if isinstance(value, float):
        raise CanonicalJsonError("floats are not canonical")
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if _is_timestamp_key(key) and not _TIMESTAMP_RE.match(normalized):
            raise CanonicalJsonError("timestamp must use YYYY-MM-DDTHH:MM:SS.mmmZ")
        if _DECIMAL_STRING_RE.match(normalized):
            raise CanonicalJsonError("decimal strings are not canonical")
        return f'"{_escape_string(normalized)}"'
    if isinstance(value, list):
        return "[" + ",".join(_emit(item, key=None) for item in value) + "]"
    if isinstance(value, dict):
        return _emit_object(value)
    raise CanonicalJsonError(
        f"unsupported canonical JSON value: {type(value).__name__}"
    )


def _emit_object(value: dict[Any, Any]) -> str:
    rows: list[tuple[bytes, str, Any]] = []
    for raw_key, item in value.items():
        if not isinstance(raw_key, str):
            raise CanonicalJsonError("object keys must be ASCII snake_case strings")
        key = unicodedata.normalize("NFC", raw_key)
        if not _KEY_RE.match(key) or not key.isascii():
            raise CanonicalJsonError("object keys must be ASCII snake_case")
        if item is None:
            raise CanonicalJsonError("null values are not canonical")
        rows.append((key.encode("ascii"), key, item))
    rows.sort(key=lambda row: row[0])
    parts = [f'"{key}":{_emit(item, key=key)}' for _, key, item in rows]
    return "{" + ",".join(parts) + "}"


def _escape_string(value: str) -> str:
    out: list[str] = []
    for char in value:
        codepoint = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif codepoint <= 0x1F:
            out.append(f"\\u{codepoint:04x}")
        else:
            out.append(char)
    return "".join(out)


def _is_timestamp_key(key: str | None) -> bool:
    return bool(key and key.endswith("_at"))
