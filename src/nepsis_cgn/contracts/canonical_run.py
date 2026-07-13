from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import re
from typing import Any

from .canonical_json import canonical_hash, canonical_json


CANONICAL_RUN_EVENT_VERSION = "nepsis.canonical_run_event@0.1.0"
CANONICAL_RUN_GENESIS_HASH = hashlib.sha256(
    b"nepsis.canonical_run.genesis@0.1.0"
).hexdigest()

_ACTOR_RE = re.compile(r"^(model|operator|validator|system):[a-z0-9._@-]+$")
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CAPABILITIES_BY_PROVENANCE = {
    "model": frozenset({"read_snapshot", "submit_model_candidate"}),
    "operator": frozenset(
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
    "validator": frozenset(
        {
            "append_validator_event",
            "export_run",
            "import_sealed_bundle",
            "read_snapshot",
            "verify_run",
        }
    ),
    "system": frozenset({"read_snapshot"}),
}


class CanonicalRunContractError(ValueError):
    pass


class CapabilityRefusal(PermissionError):
    pass


@dataclass(frozen=True)
class ActorContext:
    actor_id: str
    provenance_class: str
    capability_id: str
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.actor_id, str) or not _ACTOR_RE.fullmatch(
            self.actor_id
        ):
            raise CanonicalRunContractError("actor_id is malformed")
        actor_class = self.actor_id.split(":", 1)[0]
        if self.provenance_class != actor_class:
            raise CanonicalRunContractError(
                "actor_id prefix must match provenance_class"
            )
        if not isinstance(self.capability_id, str) or not self.capability_id:
            raise CanonicalRunContractError("capability_id is required")
        if not isinstance(self.capabilities, frozenset) or not self.capabilities:
            raise CanonicalRunContractError("capabilities must be a non-empty frozenset")
        allowed = _CAPABILITIES_BY_PROVENANCE.get(self.provenance_class)
        if allowed is None or not self.capabilities <= allowed:
            raise CanonicalRunContractError(
                "capability is not valid for the actor provenance class"
            )


def require_capability(actor_context: ActorContext, capability: str) -> None:
    if not isinstance(actor_context, ActorContext):
        raise CapabilityRefusal("trusted actor context is required")
    if capability not in actor_context.capabilities:
        raise CapabilityRefusal(
            f"actor {actor_context.actor_id} lacks capability {capability}"
        )


def build_event(
    *,
    run_id: str,
    sequence: int,
    event_type: str,
    created_at: str,
    actor_context: ActorContext,
    prev_event_hash: str,
    payload: dict[str, Any],
    caused_by_artifact_hashes: tuple[str, ...] = (),
    caused_by_event_hashes: tuple[str, ...] = (),
    idempotency_key: str | None = None,
    intent_hash: str | None = None,
    trusted_adapter_intent_id: str | None = None,
    context_manifest_hash: str | None = None,
) -> dict[str, Any]:
    _nonempty(run_id, "run_id")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise CanonicalRunContractError("sequence must be a non-negative integer")
    _nonempty(event_type, "event_type")
    _nonempty(created_at, "created_at")
    _hash(prev_event_hash, "prev_event_hash")
    if not isinstance(actor_context, ActorContext):
        raise CanonicalRunContractError("trusted actor context is required")
    if not isinstance(payload, dict):
        raise CanonicalRunContractError("payload must be an object")
    artifact_hashes = _sorted_hashes(
        caused_by_artifact_hashes, "caused_by_artifact_hashes"
    )
    event_hashes = _sorted_hashes(caused_by_event_hashes, "caused_by_event_hashes")

    envelope: dict[str, Any] = {
        "actor_id": actor_context.actor_id,
        "canonical_run_event_schema_version": CANONICAL_RUN_EVENT_VERSION,
        "caused_by_artifact_hashes": artifact_hashes,
        "caused_by_event_hashes": event_hashes,
        "created_at": created_at,
        "event_type": event_type,
        "payload_hash": canonical_hash(payload),
        "prev_event_hash": prev_event_hash,
        "provenance_class": actor_context.provenance_class,
        "run_id": run_id,
        "sequence": sequence,
    }
    for field, value in (
        ("context_manifest_hash", context_manifest_hash),
        ("idempotency_key", idempotency_key),
        ("intent_hash", intent_hash),
        ("trusted_adapter_intent_id", trusted_adapter_intent_id),
    ):
        if value is None:
            continue
        _nonempty(value, field)
        if field.endswith("_hash"):
            _hash(value, field)
        envelope[field] = value
    event_hash = canonical_hash(envelope)
    event = {**envelope, "payload": deepcopy(payload), "event_hash": event_hash}
    canonical_json(event)
    return event


def verify_event_chain(events: list[dict[str, Any]]) -> None:
    if not isinstance(events, list):
        raise CanonicalRunContractError("events must be an array")
    expected_prev = CANONICAL_RUN_GENESIS_HASH
    run_id = ""
    for expected_sequence, event in enumerate(events):
        if not isinstance(event, dict):
            raise CanonicalRunContractError("event must be an object")
        if event.get("canonical_run_event_schema_version") != CANONICAL_RUN_EVENT_VERSION:
            raise CanonicalRunContractError("unsupported canonical run event version")
        sequence = event.get("sequence")
        if isinstance(sequence, bool) or sequence != expected_sequence:
            raise CanonicalRunContractError(
                f"event sequence mismatch: expected {expected_sequence}"
            )
        event_run_id = event.get("run_id")
        if expected_sequence == 0:
            run_id = event_run_id
        if not isinstance(event_run_id, str) or not event_run_id or event_run_id != run_id:
            raise CanonicalRunContractError("run_id changed inside event chain")
        if event.get("prev_event_hash") != expected_prev:
            raise CanonicalRunContractError("prev_event_hash mismatch")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise CanonicalRunContractError("event payload is required")
        if canonical_hash(payload) != event.get("payload_hash"):
            raise CanonicalRunContractError("payload_hash mismatch")
        envelope = {
            key: deepcopy(value)
            for key, value in event.items()
            if key not in {"payload", "event_hash"}
        }
        if canonical_hash(envelope) != event.get("event_hash"):
            raise CanonicalRunContractError("event_hash mismatch")
        expected_prev = _hash(event.get("event_hash"), "event_hash")


def _sorted_hashes(values: tuple[str, ...], field: str) -> list[str]:
    if not isinstance(values, tuple):
        raise CanonicalRunContractError(f"{field} must be a tuple")
    result = sorted(set(values))
    if len(result) != len(values):
        raise CanonicalRunContractError(f"{field} must contain unique hashes")
    for value in result:
        _hash(value, field)
    return result


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CanonicalRunContractError(f"{field} must be a non-empty string")
    return value


def _hash(value: Any, field: str) -> str:
    text = _nonempty(value, field)
    if not _HASH_RE.fullmatch(text):
        raise CanonicalRunContractError(f"{field} must be a lowercase SHA-256 hash")
    return text


__all__ = [
    "CANONICAL_RUN_EVENT_VERSION",
    "CANONICAL_RUN_GENESIS_HASH",
    "ActorContext",
    "CanonicalRunContractError",
    "CapabilityRefusal",
    "build_event",
    "require_capability",
    "verify_event_chain",
]
