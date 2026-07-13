from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from nepsis_cgn.canonical_runs.store import (
    AdmissionDecision,
    AdmissionValidator,
    ArtifactInput,
    CanonicalRunStore,
    CanonicalRunStoreError,
    InvalidRequest,
)
from nepsis_cgn.canonical_runs.operator_disposition import (
    OPERATOR_DISPOSITION_ACTION_TYPE,
    OPERATOR_DISPOSITION_POLICY_HASH,
    OPERATOR_DISPOSITION_POLICY_VERSION,
    validate_model_candidate_transition,
)
from nepsis_cgn.canonical_runs.actualization import (
    CanonicalActualizationError,
    PERFORM_ZEROBACK_ACTION_TYPE,
    RELEASE_STILL_ACTION_TYPE,
    REQUEST_DECISION_COMMIT_ACTION_TYPE,
    normalize_requested_change,
)
from nepsis_cgn.contracts.canonical_json import canonical_bytes, canonical_hash
from nepsis_cgn.contracts.canonical_run import ActorContext, require_capability
from nepsis_cgn.verification.receipts import (
    sign_action_receipt,
    verify_action_receipt,
)


SERVICE_VERSION = "nepsis.canonical_run_service@0.1.0"
CONTEXT_MANIFEST_VERSION = "nepsis.context_manifest@0.1.0"
OPERATOR_VISIBLE_PROPOSAL_VERSION = "nepsis.operator_visible_proposal@0.1.0"
EXTERNAL_CODEX_REF_VERSION = "nepsis.external_codex_ref@0.1.0"
MODEL_CANDIDATE_VERSION = "nepsis.model_candidate@0.1.0"
RUN_SNAPSHOT_ATTESTATION_VERSION = "nepsis.run_snapshot_attestation@0.1.0"
ACTION_RECEIPT_VERSION = "nepsis.action_receipt@0.1.0"
CANONICAL_RUN_PROTECTED_EXPORT_VERSION = (
    "nepsis.canonical_run_protected_export@0.1.0"
)
GOVERNANCE_POLICY_DIFF_VERSION = "nepsis.governance_policy_diff@0.1.0"

_PROPOSAL_FIELDS = {
    "alternatives_summary",
    "evidence_refs",
    "hazards_summary",
    "operator_visible_proposal_schema_version",
    "proposal_text",
    "rationale_text",
    "requested_change",
}
_EXTERNAL_REF_REQUIRED_FIELDS = {
    "actor_id",
    "adapter_version",
    "capability",
    "capability_id",
    "created_at",
    "external_codex_ref_schema_version",
    "host_type",
    "model_configuration_epoch",
    "model_id",
    "operator_visible_proposal_hash",
    "provenance_class",
    "run_id",
    "thread_id",
    "tool_call_id",
    "turn_id",
}
_EXTERNAL_REF_OPTIONAL_FIELDS = {"account_fingerprint", "transcript_export_ref"}
_CONTEXT_FIELDS = {
    "active_hold",
    "context_manifest_schema_version",
    "data_classification",
    "denominator_collapse_active",
    "effective_policy_hash",
    "evidence_root_hash",
    "frame_root_hash",
    "generated_at",
    "generator",
    "manifest_id",
    "observation_root_hash",
    "operator_governance_profile_hash",
    "packet_projection_hash",
    "population_root_hash",
    "relevant_artifact_revisions",
    "remote_inference_authorized",
    "run_head_event_hash",
    "run_head_sequence",
    "run_id",
    "session_governance_snapshot_hash",
    "unresolved_contradiction_hashes",
    "unresolved_red_hazard_hashes",
}
_OPERATOR_CAPABILITIES = {
    "perform_zeroback",
    "release_still",
    "request_decision_commit",
    "submit_operator_disposition",
}
_VALIDATOR_POLICY_DOCUMENT = {
    "context_manifest": "exact_current_cgn_snapshot",
    "model_authority": "proposal_only",
    "operator_authority": "explicit_confirmed_action",
    "operator_disposition_policy_hash": OPERATOR_DISPOSITION_POLICY_HASH,
    "operator_disposition_policy_version": OPERATOR_DISPOSITION_POLICY_VERSION,
    "receipt": "post_commit_reread_ed25519",
    "version": SERVICE_VERSION,
}


class CanonicalRunServiceError(RuntimeError):
    """The service cannot safely bind or report the requested action."""


class ContextRefusal(CanonicalRunServiceError):
    """The supplied context is not the exact current CGN context artifact."""


@dataclass(frozen=True)
class ContextArtifact:
    artifact: Mapping[str, Any]
    artifact_hash: str


@dataclass(frozen=True)
class ServiceActionResult:
    receipt: Mapping[str, Any]
    replayed: bool


class CanonicalRunService:
    """Capability-separated service above the durable canonical-run store."""

    def __init__(
        self,
        *,
        store: CanonicalRunStore,
        private_key: Ed25519PrivateKey,
        trust_anchor: Mapping[str, Any],
    ) -> None:
        if not isinstance(store, CanonicalRunStore):
            raise CanonicalRunServiceError("CanonicalRunStore is required")
        if not isinstance(private_key, Ed25519PrivateKey):
            raise CanonicalRunServiceError("Ed25519PrivateKey is required")
        if "revoked_at" in trust_anchor:
            raise CanonicalRunServiceError(
                "a revoked trust anchor cannot initialize the active writer"
            )
        self._store = store
        self._private_key = private_key
        self._public_key: Ed25519PublicKey = private_key.public_key()
        self._trust_anchor = dict(trust_anchor)

    def create_run(
        self,
        *,
        actor: ActorContext,
        run_id: str,
        owner_id: str,
        created_at: str,
        idempotency_key: str,
        operator_governance_profile_hash: str,
        session_governance_snapshot_hash: str,
        effective_policy_hash: str,
        system_policy_bindings: list[Mapping[str, Any]],
        initial_packet_projection: Mapping[str, Any],
        initial_postcondition: Mapping[str, Any],
        fork_provenance: Mapping[str, Any] | None = None,
        fork_policy_diff_artifact: Mapping[str, Any] | None = None,
    ) -> ServiceActionResult:
        _require_operator_actor(actor, "create_run")
        if owner_id != actor.actor_id:
            raise CanonicalRunServiceError("run owner must match the operator actor")
        for field, value in (
            ("operator_governance_profile_hash", operator_governance_profile_hash),
            ("session_governance_snapshot_hash", session_governance_snapshot_hash),
            ("effective_policy_hash", effective_policy_hash),
        ):
            _hash(value, field)
        if not isinstance(initial_packet_projection, Mapping):
            raise CanonicalRunServiceError("initial packet projection must be an object")
        if "operator_proposal_state" in initial_packet_projection:
            raise CanonicalRunServiceError(
                "operator proposal state must originate in a recorded model candidate"
            )
        if not isinstance(initial_postcondition, Mapping):
            raise CanonicalRunServiceError("initial postcondition must be an object")
        normalized_fork, normalized_diff = _validate_fork_inputs(
            fork_provenance=fork_provenance,
            fork_policy_diff_artifact=fork_policy_diff_artifact,
            run_id=run_id,
            owner_id=owner_id,
            created_at=created_at,
            effective_policy_hash=effective_policy_hash,
        )
        result = self._store.create_run(
            run_id=_text(run_id, "run_id"),
            owner_id=_text(owner_id, "owner_id"),
            created_at=_text(created_at, "created_at"),
            actor=actor,
            capability_id=actor.capability_id,
            idempotency_key=_text(idempotency_key, "idempotency_key"),
            operator_governance_profile_hash=operator_governance_profile_hash,
            session_governance_snapshot_hash=session_governance_snapshot_hash,
            effective_policy_hash=effective_policy_hash,
            system_policy_bindings=system_policy_bindings,
            initial_packet_projection=dict(initial_packet_projection),
            initial_postcondition=dict(initial_postcondition),
            fork_provenance=normalized_fork,
            fork_policy_diff_artifact=normalized_diff,
        )
        return self._issue_postcommit_receipt(result=result, actor=actor)

    def read_snapshot(
        self, *, run_id: str, actor: ActorContext
    ) -> Mapping[str, Any]:
        require_capability(actor, "read_snapshot")
        snapshot = self._store.get_snapshot(run_id)
        if actor.provenance_class == "model":
            context = _context_manifest_from_snapshot(snapshot)
            return {
                "authority": "informational_only",
                "committed": False,
                "context_manifest": context,
                "context_manifest_hash": canonical_hash(context),
                "run_id": run_id,
            }
        return snapshot

    def build_context_manifest(
        self, *, run_id: str, actor: ActorContext
    ) -> ContextArtifact:
        require_capability(actor, "read_snapshot")
        snapshot = self._store.get_snapshot(run_id)
        artifact = _context_manifest_from_snapshot(snapshot)
        return ContextArtifact(artifact=artifact, artifact_hash=canonical_hash(artifact))

    def build_snapshot_attestation(
        self,
        *,
        run_id: str,
        actor: ActorContext,
        challenge_hash: str,
    ) -> Mapping[str, Any]:
        require_capability(actor, "read_snapshot")
        snapshot = self._store.get_snapshot(run_id)
        postcondition = dict(snapshot["postcondition"])
        unsigned = {
            "challenge_hash": _hash(challenge_hash, "challenge_hash"),
            "effective_policy_hash": snapshot["effective_policy_hash"],
            "head_event_hash": snapshot["head_event_hash"],
            "head_sequence": snapshot["head_sequence"],
            "issued_at": snapshot["head_created_at"],
            "operator_governance_profile_hash": snapshot[
                "operator_governance_profile_hash"
            ],
            "packet_projection_hash": postcondition["packet_projection_hash"],
            "postcondition_hash": canonical_hash(postcondition),
            "run_id": snapshot["run_id"],
            "run_snapshot_attestation_schema_version": (
                RUN_SNAPSHOT_ATTESTATION_VERSION
            ),
            "session_governance_snapshot_hash": snapshot[
                "session_governance_snapshot_hash"
            ],
            "validator_policy_hash": canonical_hash(_VALIDATOR_POLICY_DOCUMENT),
            "validator_policy_version": SERVICE_VERSION,
        }
        unsigned["attestation_id"] = f"attestation:{canonical_hash(unsigned)}"
        attestation = sign_action_receipt(
            unsigned,
            private_key=self._private_key,
            trust_anchor=self._trust_anchor,
            signing_at=str(unsigned["issued_at"]),
        )
        if not verify_action_receipt(
            attestation,
            public_key=self._public_key,
            trust_anchor=self._trust_anchor,
        ):
            raise CanonicalRunServiceError("snapshot attestation did not verify")
        return attestation

    def query_outcome(
        self,
        *,
        run_id: str,
        actor: ActorContext,
        idempotency_key: str,
    ) -> ServiceActionResult | None:
        require_capability(actor, "read_snapshot")
        result = self._store.get_outcome(
            run_id=run_id,
            actor_id=actor.actor_id,
            idempotency_key=_text(idempotency_key, "idempotency_key"),
        )
        if result is None:
            return None
        return self._issue_postcommit_receipt(result=result, actor=actor)

    def export_run(
        self, *, run_id: str, actor: ActorContext
    ) -> Mapping[str, Any]:
        require_capability(actor, "export_run")
        exported = self._store.export_run(run_id)
        receipts = [
            self._receipt_from_persisted_record(dict(outcome))
            for outcome in exported["outcomes"]
        ]
        protected = {
            **exported,
            "action_receipts": receipts,
            "protected_export_schema_version": (
                CANONICAL_RUN_PROTECTED_EXPORT_VERSION
            ),
            "receipt_trust_anchor": dict(self._trust_anchor),
        }
        return {
            **protected,
            "export_root_hash": canonical_hash(protected),
        }

    def build_external_codex_ref(
        self,
        *,
        actor: ActorContext,
        run_id: str,
        adapter_version: str,
        created_at: str,
        thread_id: str,
        turn_id: str,
        tool_call_id: str,
        model_id: str,
        model_configuration_epoch: str,
        operator_visible_proposal_hash: str,
        account_fingerprint: str | None = None,
        transcript_export_ref: str | None = None,
    ) -> dict[str, Any]:
        _require_model_actor(actor)
        record = {
            "actor_id": actor.actor_id,
            "adapter_version": _text(adapter_version, "adapter_version"),
            "capability": "submit_model_candidate",
            "capability_id": actor.capability_id,
            "created_at": _text(created_at, "created_at"),
            "external_codex_ref_schema_version": EXTERNAL_CODEX_REF_VERSION,
            "host_type": "codex_app_server",
            "model_configuration_epoch": _text(
                model_configuration_epoch, "model_configuration_epoch"
            ),
            "model_id": _text(model_id, "model_id"),
            "operator_visible_proposal_hash": _hash(
                operator_visible_proposal_hash,
                "operator_visible_proposal_hash",
            ),
            "provenance_class": "model",
            "run_id": _text(run_id, "run_id"),
            "thread_id": _text(thread_id, "thread_id"),
            "tool_call_id": _text(tool_call_id, "tool_call_id"),
            "turn_id": _text(turn_id, "turn_id"),
        }
        for field, value in (
            ("account_fingerprint", account_fingerprint),
            ("transcript_export_ref", transcript_export_ref),
        ):
            if value is not None:
                record[field] = _text(value, field)
        canonical_bytes(record)
        return record

    def submit_model_candidate(
        self,
        *,
        actor: ActorContext,
        context_manifest: Mapping[str, Any],
        operator_visible_proposal: Mapping[str, Any],
        external_codex_ref: Mapping[str, Any],
        created_at: str,
        idempotency_key: str,
        trusted_adapter_intent_id: str,
    ) -> ServiceActionResult:
        _require_model_actor(actor)
        supplied_context = _validate_context_manifest(context_manifest)
        context_hash = canonical_hash(supplied_context)

        proposal = _validate_proposal(operator_visible_proposal)
        requested_change = proposal["requested_change"]
        if (
            isinstance(requested_change, Mapping)
            and "base_event_hash" in requested_change
            and requested_change["base_event_hash"]
            != supplied_context["run_head_event_hash"]
        ):
            raise CanonicalRunServiceError(
                "requested_change base_event_hash does not match the exact context head"
            )
        proposal_hash = canonical_hash(proposal)
        external_ref = _validate_external_ref(
            external_codex_ref,
            actor=actor,
            run_id=str(supplied_context["run_id"]),
            operator_visible_proposal_hash=proposal_hash,
        )
        external_hash = canonical_hash(external_ref)

        candidate_payload = {
            "context_manifest_hash": context_hash,
            "external_codex_ref_hash": external_hash,
            "model_candidate_schema_version": MODEL_CANDIDATE_VERSION,
            "normalized_change": dict(proposal["requested_change"]),
            "operator_visible_proposal_hash": proposal_hash,
            "proposal_id": f"proposal:{proposal_hash}",
        }
        request_snapshot = _snapshot_from_context_manifest(supplied_context)
        request = _action_request(
            snapshot=request_snapshot,
            actor=actor,
            capability="submit_model_candidate",
            action_type="record_model_candidate",
            payload=candidate_payload,
            artifact_hashes=sorted((context_hash, proposal_hash, external_hash)),
            created_at=created_at,
            idempotency_key=idempotency_key,
            trusted_adapter_intent_id=trusted_adapter_intent_id,
            context_manifest_hash=context_hash,
            external_codex_ref_hash=external_hash,
            operator_visible_proposal_hash=proposal_hash,
        )
        existing = self._store.get_outcome(
            run_id=str(supplied_context["run_id"]),
            actor_id=actor.actor_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if (
                existing.record.get("request_hash") != canonical_hash(request)
                or existing.record.get("intent_hash") != request["intent_hash"]
            ):
                raise CanonicalRunServiceError(
                    "idempotency key was already used for different candidate bytes"
                )
            return self._issue_postcommit_receipt(result=existing, actor=actor)

        snapshot = self._store.get_snapshot(str(supplied_context["run_id"]))
        expected_context = _context_manifest_from_snapshot(snapshot)
        if supplied_context != expected_context:
            raise ContextRefusal(
                "context manifest is stale, incomplete, or not CGN-generated"
            )
        artifacts = (
            ArtifactInput(
                artifact_schema_version=CONTEXT_MANIFEST_VERSION,
                roles=("context_manifest",),
                artifact=supplied_context,
            ),
            ArtifactInput(
                artifact_schema_version=OPERATOR_VISIBLE_PROPOSAL_VERSION,
                roles=("operator_visible_proposal",),
                artifact=proposal,
            ),
            ArtifactInput(
                artifact_schema_version=EXTERNAL_CODEX_REF_VERSION,
                roles=("external_codex_ref",),
                artifact=external_ref,
            ),
        )

        def validate_locked_context(
            normalized_request: Mapping[str, Any], locked_snapshot: Mapping[str, Any]
        ) -> AdmissionDecision:
            if _context_manifest_from_snapshot(locked_snapshot) != supplied_context:
                raise ContextRefusal("context changed before canonical admission")
            if normalized_request["context_manifest_hash"] != context_hash:
                raise ContextRefusal("request context binding changed")
            return validate_model_candidate_transition(
                normalized_request, locked_snapshot
            )

        result = self._store.append_action(
            actor=actor,
            request=request,
            artifacts=artifacts,
            validator=validate_locked_context,
        )
        return self._issue_postcommit_receipt(result=result, actor=actor)

    def submit_operator_action(
        self,
        *,
        actor: ActorContext,
        capability: str,
        action_type: str,
        payload: Mapping[str, Any],
        confirmation: Mapping[str, Any],
        created_at: str,
        effective_policy_hash: str,
        expected_head_event_hash: str,
        expected_head_sequence: int,
        idempotency_key: str,
        operator_governance_profile_hash: str,
        session_governance_snapshot_hash: str,
        trusted_adapter_intent_id: str,
        validator: AdmissionValidator,
    ) -> ServiceActionResult:
        _require_operator_actor(actor, capability)
        if capability not in _OPERATOR_CAPABILITIES:
            raise CanonicalRunServiceError("unsupported operator capability")
        if not isinstance(payload, Mapping):
            raise CanonicalRunServiceError("operator payload must be an object")
        normalized_confirmation = _validate_confirmation(confirmation, created_at)
        run_id = payload.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            raise CanonicalRunServiceError("operator payload requires run_id")
        request_snapshot = {
            "effective_policy_hash": _hash(
                effective_policy_hash, "effective_policy_hash"
            ),
            "head_event_hash": _hash(
                expected_head_event_hash, "expected_head_event_hash"
            ),
            "head_sequence": _nonnegative_int(
                expected_head_sequence, "expected_head_sequence"
            ),
            "operator_governance_profile_hash": _hash(
                operator_governance_profile_hash,
                "operator_governance_profile_hash",
            ),
            "run_id": run_id,
            "session_governance_snapshot_hash": _hash(
                session_governance_snapshot_hash,
                "session_governance_snapshot_hash",
            ),
        }
        action_payload = dict(payload)
        artifact_hashes: list[str] = []
        operator_visible_proposal_hash: str | None = None
        if capability == "submit_operator_disposition":
            if action_type != OPERATOR_DISPOSITION_ACTION_TYPE:
                raise CanonicalRunServiceError(
                    "unsupported operator disposition action_type"
                )
            if set(action_payload) != {
                "disposition",
                "operator_visible_proposal_hash",
                "run_id",
            }:
                raise CanonicalRunServiceError(
                    "operator disposition payload has invalid fields"
                )
            if action_payload["disposition"] not in {"accept", "defer", "reject"}:
                raise CanonicalRunServiceError(
                    "operator disposition must be accept, defer, or reject"
                )
            operator_visible_proposal_hash = _hash(
                action_payload["operator_visible_proposal_hash"],
                "operator_visible_proposal_hash",
            )
            artifact_hashes = [operator_visible_proposal_hash]
        elif capability == "release_still":
            if action_type != RELEASE_STILL_ACTION_TYPE or set(
                action_payload
            ) != {"operator_visible_proposal_hash", "run_id"}:
                raise CanonicalRunServiceError(
                    "STILL release payload or action_type is invalid"
                )
            operator_visible_proposal_hash = _hash(
                action_payload["operator_visible_proposal_hash"],
                "operator_visible_proposal_hash",
            )
            _proposal_artifact(
                self._store,
                run_id=run_id,
                proposal_hash=operator_visible_proposal_hash,
            )
            artifact_hashes = [operator_visible_proposal_hash]
        elif capability == "request_decision_commit":
            if action_type != REQUEST_DECISION_COMMIT_ACTION_TYPE or set(
                action_payload
            ) != {
                "operator_visible_proposal_hash",
                "requested_change",
                "run_id",
            }:
                raise CanonicalRunServiceError(
                    "decision commit payload or action_type is invalid"
                )
            operator_visible_proposal_hash = _hash(
                action_payload["operator_visible_proposal_hash"],
                "operator_visible_proposal_hash",
            )
            proposal = _proposal_artifact(
                self._store,
                run_id=run_id,
                proposal_hash=operator_visible_proposal_hash,
            )
            try:
                requested_change = normalize_requested_change(
                    action_payload["requested_change"]
                )
                proposal_change = normalize_requested_change(
                    proposal["requested_change"]
                )
            except CanonicalActualizationError as exc:
                raise CanonicalRunServiceError(str(exc)) from exc
            if requested_change != proposal_change:
                raise CanonicalRunServiceError(
                    "decision commit requested_change does not match the proposal artifact"
                )
            action_payload["requested_change"] = requested_change
            artifact_hashes = [operator_visible_proposal_hash]
        elif capability == "perform_zeroback":
            if action_type != PERFORM_ZEROBACK_ACTION_TYPE or set(
                action_payload
            ) != {"replacement_frame_root_hash", "run_id"}:
                raise CanonicalRunServiceError(
                    "ZeroBack payload or action_type is invalid"
                )
            _hash(
                action_payload["replacement_frame_root_hash"],
                "replacement_frame_root_hash",
            )
        request = _action_request(
            snapshot=request_snapshot,
            actor=actor,
            capability=capability,
            action_type=action_type,
            payload=action_payload,
            artifact_hashes=artifact_hashes,
            created_at=created_at,
            idempotency_key=idempotency_key,
            trusted_adapter_intent_id=trusted_adapter_intent_id,
            operator_visible_proposal_hash=operator_visible_proposal_hash,
            operator_confirmation=normalized_confirmation,
        )
        existing = self._store.get_outcome(
            run_id=run_id,
            actor_id=actor.actor_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if (
                existing.record.get("request_hash") != canonical_hash(request)
                or existing.record.get("intent_hash") != request["intent_hash"]
            ):
                raise CanonicalRunServiceError(
                    "idempotency key was already used for different operator bytes"
                )
            return self._issue_postcommit_receipt(result=existing, actor=actor)
        result = self._store.append_action(
            actor=actor,
            request=request,
            validator=validator,
        )
        return self._issue_postcommit_receipt(result=result, actor=actor)

    def verify_receipt(self, receipt: Mapping[str, Any]) -> bool:
        return verify_action_receipt(
            receipt,
            public_key=self._public_key,
            trust_anchor=self._trust_anchor,
        )

    def _issue_postcommit_receipt(
        self, *, result: Any, actor: ActorContext
    ) -> ServiceActionResult:
        record = dict(result.record)
        persisted = self._store.get_outcome(
            run_id=str(record["run_id"]),
            actor_id=actor.actor_id,
            idempotency_key=str(record["idempotency_key"]),
        )
        if persisted is None or canonical_bytes(dict(persisted.record)) != canonical_bytes(
            record
        ):
            raise CanonicalRunServiceError("post-commit outcome reread mismatch")
        if not result.replayed:
            snapshot = self._store.get_snapshot(str(record["run_id"]))
            if (
                snapshot["head_event_hash"] != record["resulting_head_event_hash"]
                or snapshot["head_sequence"] != record["resulting_head_sequence"]
                or snapshot["postcondition"] != record["postcondition"]
            ):
                raise CanonicalRunServiceError("post-commit snapshot reread mismatch")

        receipt = self._receipt_from_persisted_record(record)
        return ServiceActionResult(receipt=receipt, replayed=bool(result.replayed))

    def _receipt_from_persisted_record(
        self, record: Mapping[str, Any]
    ) -> dict[str, Any]:
        persisted = self._store.get_outcome(
            run_id=str(record["run_id"]),
            actor_id=str(record["actor_id"]),
            idempotency_key=str(record["idempotency_key"]),
        )
        if persisted is None or canonical_bytes(dict(persisted.record)) != canonical_bytes(
            dict(record)
        ):
            raise CanonicalRunServiceError("persisted outcome reread mismatch")
        unsigned = {
            key: value for key, value in record.items() if key != "outcome_id"
        }
        unsigned.update(
            {
                "action_receipt_schema_version": ACTION_RECEIPT_VERSION,
                "receipt_id": f"receipt:{canonical_hash(record)}",
                "validator_policy_hash": canonical_hash(
                    _VALIDATOR_POLICY_DOCUMENT
                ),
                "validator_policy_version": SERVICE_VERSION,
                "verification_level": "writer_post_commit_reread",
            }
        )
        receipt = sign_action_receipt(
            unsigned,
            private_key=self._private_key,
            trust_anchor=self._trust_anchor,
            signing_at=str(record["issued_at"]),
        )
        if not self.verify_receipt(receipt):
            raise CanonicalRunServiceError("issued action receipt did not verify")
        return receipt


def _context_manifest_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    postcondition = dict(snapshot["postcondition"])
    packet_projection = dict(snapshot["packet_projection"])
    if postcondition["packet_projection_hash"] != canonical_hash(packet_projection):
        raise CanonicalRunServiceError("snapshot packet projection hash mismatch")
    context_state = packet_projection.get("context_state")
    if not isinstance(context_state, Mapping):
        raise CanonicalRunServiceError(
            "packet projection requires an explicit context_state"
        )
    required_state = {
        "data_classification",
        "denominator_collapse_active",
        "evidence_root_hash",
        "frame_root_hash",
        "observation_root_hash",
        "population_root_hash",
        "relevant_artifact_revisions",
        "remote_inference_authorized",
        "unresolved_contradiction_hashes",
        "unresolved_red_hazard_hashes",
    }
    if set(context_state) != required_state:
        raise CanonicalRunServiceError("packet context_state has invalid fields")
    manifest: dict[str, Any] = {
        "active_hold": postcondition["active_hold"],
        "context_manifest_schema_version": CONTEXT_MANIFEST_VERSION,
        "data_classification": context_state["data_classification"],
        "denominator_collapse_active": context_state[
            "denominator_collapse_active"
        ],
        "effective_policy_hash": snapshot["effective_policy_hash"],
        "evidence_root_hash": context_state["evidence_root_hash"],
        "frame_root_hash": context_state["frame_root_hash"],
        "generated_at": snapshot["head_created_at"],
        "generator": {
            "actor_id": f"validator:{SERVICE_VERSION}",
            "authority": "nepsis_cgn",
            "generator_version": SERVICE_VERSION,
            "provenance_class": "validator",
        },
        "observation_root_hash": context_state["observation_root_hash"],
        "operator_governance_profile_hash": snapshot[
            "operator_governance_profile_hash"
        ],
        "packet_projection_hash": postcondition["packet_projection_hash"],
        "population_root_hash": context_state["population_root_hash"],
        "relevant_artifact_revisions": list(
            context_state["relevant_artifact_revisions"]
        ),
        "remote_inference_authorized": context_state[
            "remote_inference_authorized"
        ],
        "run_head_event_hash": snapshot["head_event_hash"],
        "run_head_sequence": snapshot["head_sequence"],
        "run_id": snapshot["run_id"],
        "session_governance_snapshot_hash": snapshot[
            "session_governance_snapshot_hash"
        ],
        "unresolved_contradiction_hashes": list(
            context_state["unresolved_contradiction_hashes"]
        ),
        "unresolved_red_hazard_hashes": list(
            context_state["unresolved_red_hazard_hashes"]
        ),
    }
    manifest["manifest_id"] = f"manifest:{canonical_hash(manifest)}"
    return _validate_context_manifest(manifest)


def _validate_context_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    manifest = _exact_mapping(value, _CONTEXT_FIELDS, "context manifest")
    if manifest["context_manifest_schema_version"] != CONTEXT_MANIFEST_VERSION:
        raise ContextRefusal("unsupported context manifest version")
    if manifest["generator"] != {
        "actor_id": f"validator:{SERVICE_VERSION}",
        "authority": "nepsis_cgn",
        "generator_version": SERVICE_VERSION,
        "provenance_class": "validator",
    }:
        raise ContextRefusal("context manifest was not generated by CGN")
    for field in (
        "effective_policy_hash",
        "evidence_root_hash",
        "frame_root_hash",
        "observation_root_hash",
        "operator_governance_profile_hash",
        "packet_projection_hash",
        "population_root_hash",
        "run_head_event_hash",
        "session_governance_snapshot_hash",
    ):
        _hash(manifest[field], field)
    if isinstance(manifest["run_head_sequence"], bool) or not isinstance(
        manifest["run_head_sequence"], int
    ):
        raise ContextRefusal("context head sequence must be an integer")
    for field in (
        "active_hold",
        "denominator_collapse_active",
        "remote_inference_authorized",
    ):
        if not isinstance(manifest[field], bool):
            raise ContextRefusal(f"context {field} must be boolean")
    if manifest["data_classification"] not in {
        "operator_cleared_non_phi",
        "synthetic",
    }:
        raise ContextRefusal("context data classification is unsupported")
    for field in ("generated_at", "manifest_id", "run_id"):
        _text(manifest[field], field)
    for field in (
        "unresolved_contradiction_hashes",
        "unresolved_red_hazard_hashes",
    ):
        _sorted_unique_hashes(manifest[field], field)
    _validate_relevant_artifact_revisions(
        manifest["relevant_artifact_revisions"]
    )
    expected_id = f"manifest:{canonical_hash({key: value for key, value in manifest.items() if key != 'manifest_id'})}"
    if manifest["manifest_id"] != expected_id:
        raise ContextRefusal("context manifest_id mismatch")
    canonical_bytes(manifest)
    return manifest


def _snapshot_from_context_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "effective_policy_hash": manifest["effective_policy_hash"],
        "head_event_hash": manifest["run_head_event_hash"],
        "head_sequence": manifest["run_head_sequence"],
        "operator_governance_profile_hash": manifest[
            "operator_governance_profile_hash"
        ],
        "run_id": manifest["run_id"],
        "session_governance_snapshot_hash": manifest[
            "session_governance_snapshot_hash"
        ],
    }


def _validate_proposal(value: Mapping[str, Any]) -> dict[str, Any]:
    proposal = _exact_mapping(value, _PROPOSAL_FIELDS, "operator-visible proposal")
    if proposal["operator_visible_proposal_schema_version"] != OPERATOR_VISIBLE_PROPOSAL_VERSION:
        raise CanonicalRunServiceError("unsupported operator-visible proposal version")
    for field in (
        "alternatives_summary",
        "hazards_summary",
        "proposal_text",
        "rationale_text",
    ):
        _text(proposal[field], field)
    change = proposal["requested_change"]
    if not isinstance(change, Mapping) or not change:
        raise CanonicalRunServiceError("requested_change must be a non-empty object")
    proposal["requested_change"] = dict(change)
    proposal["evidence_refs"] = _sorted_unique_text(
        proposal["evidence_refs"], "evidence_refs"
    )
    canonical_bytes(proposal)
    return proposal


def _proposal_artifact(
    store: CanonicalRunStore, *, run_id: str, proposal_hash: str
) -> dict[str, Any]:
    try:
        row = store.get_artifact(run_id, proposal_hash)
    except (CanonicalRunStoreError, InvalidRequest) as exc:
        raise CanonicalRunServiceError(
            "operator-visible proposal artifact is unavailable"
        ) from exc
    if (
        row.get("artifact_schema_version") != OPERATOR_VISIBLE_PROPOSAL_VERSION
        or row.get("roles") != ["operator_visible_proposal"]
        or not isinstance(row.get("artifact"), Mapping)
    ):
        raise CanonicalRunServiceError(
            "operator-visible proposal artifact has invalid authority metadata"
        )
    proposal = _validate_proposal(row["artifact"])
    if canonical_hash(proposal) != proposal_hash:
        raise CanonicalRunServiceError(
            "operator-visible proposal artifact hash mismatch"
        )
    return proposal


def _validate_external_ref(
    value: Mapping[str, Any],
    *,
    actor: ActorContext,
    run_id: str,
    operator_visible_proposal_hash: str,
) -> dict[str, Any]:
    record = _closed_mapping(
        value,
        required=_EXTERNAL_REF_REQUIRED_FIELDS,
        optional=_EXTERNAL_REF_OPTIONAL_FIELDS,
        label="external Codex ref",
    )
    expected = {
        "actor_id": actor.actor_id,
        "capability": "submit_model_candidate",
        "capability_id": actor.capability_id,
        "external_codex_ref_schema_version": EXTERNAL_CODEX_REF_VERSION,
        "host_type": "codex_app_server",
        "operator_visible_proposal_hash": operator_visible_proposal_hash,
        "provenance_class": "model",
        "run_id": run_id,
    }
    for field, expected_value in expected.items():
        if record[field] != expected_value:
            raise CanonicalRunServiceError(f"external Codex ref {field} mismatch")
    for field in (
        "adapter_version",
        "created_at",
        "model_id",
        "model_configuration_epoch",
        "thread_id",
        "tool_call_id",
        "turn_id",
    ):
        _text(record[field], field)
    for field in _EXTERNAL_REF_OPTIONAL_FIELDS:
        if field in record:
            _text(record[field], field)
    canonical_bytes(record)
    return record


def _action_request(
    *,
    snapshot: Mapping[str, Any],
    actor: ActorContext,
    capability: str,
    action_type: str,
    payload: Mapping[str, Any],
    artifact_hashes: list[str],
    created_at: str,
    idempotency_key: str,
    trusted_adapter_intent_id: str,
    context_manifest_hash: str | None = None,
    external_codex_ref_hash: str | None = None,
    operator_visible_proposal_hash: str | None = None,
    operator_confirmation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_payload = dict(payload)
    request: dict[str, Any] = {
        "action_request_schema_version": "nepsis.action_request@0.1.0",
        "action_type": _text(action_type, "action_type"),
        "artifact_hashes": artifact_hashes,
        "capability": capability,
        "capability_id": actor.capability_id,
        "created_at": _text(created_at, "created_at"),
        "effective_policy_hash": snapshot["effective_policy_hash"],
        "expected_head_event_hash": snapshot["head_event_hash"],
        "expected_head_sequence": snapshot["head_sequence"],
        "idempotency_key": _text(idempotency_key, "idempotency_key"),
        "intent_hash": canonical_hash(
            {
                "action": action_type,
                **(
                    {
                        "capability": capability,
                        "operator_confirmation": dict(operator_confirmation),
                    }
                    if operator_confirmation is not None
                    else {}
                ),
                "payload": normalized_payload,
            }
        ),
        "operator_governance_profile_hash": snapshot[
            "operator_governance_profile_hash"
        ],
        "payload": normalized_payload,
        "payload_hash": canonical_hash(normalized_payload),
        "run_id": snapshot["run_id"],
        "session_governance_snapshot_hash": snapshot[
            "session_governance_snapshot_hash"
        ],
        "trusted_adapter_intent_id": _text(
            trusted_adapter_intent_id, "trusted_adapter_intent_id"
        ),
    }
    for field, value in (
        ("context_manifest_hash", context_manifest_hash),
        ("external_codex_ref_hash", external_codex_ref_hash),
        ("operator_visible_proposal_hash", operator_visible_proposal_hash),
    ):
        if value is not None:
            request[field] = value
    if operator_confirmation is not None:
        request["operator_confirmation"] = dict(operator_confirmation)
    return request


def _validate_confirmation(
    value: Mapping[str, Any], created_at: str
) -> dict[str, Any]:
    confirmation = _exact_mapping(
        value,
        {"confirmed", "confirmed_at", "consequence_acknowledged", "rationale"},
        "operator confirmation",
    )
    if confirmation["confirmed"] is not True:
        raise CanonicalRunServiceError("operator confirmation must be affirmative")
    if confirmation["consequence_acknowledged"] is not True:
        raise CanonicalRunServiceError("operator consequence acknowledgement is required")
    if confirmation["confirmed_at"] != created_at:
        raise CanonicalRunServiceError("confirmation timestamp must match action timestamp")
    _text(confirmation["rationale"], "rationale")
    return confirmation


def _validate_fork_inputs(
    *,
    fork_provenance: Mapping[str, Any] | None,
    fork_policy_diff_artifact: Mapping[str, Any] | None,
    run_id: str,
    owner_id: str,
    created_at: str,
    effective_policy_hash: str,
) -> tuple[dict[str, Any] | None, ArtifactInput | None]:
    del owner_id  # ownership is checked atomically against the predecessor store row
    if fork_provenance is None and fork_policy_diff_artifact is None:
        return None, None
    if fork_provenance is None or fork_policy_diff_artifact is None:
        raise CanonicalRunServiceError(
            "fork provenance and policy-diff artifact must be supplied together"
        )
    provenance = _exact_mapping(
        fork_provenance,
        {
            "fork_reason",
            "forked_from_run_id",
            "inherited_evidence_root_hashes",
            "parent_head_event_hash",
            "policy_diff_artifact_hash",
        },
        "fork provenance",
    )
    _text(provenance["fork_reason"], "fork_reason")
    parent_run_id = _text(
        provenance["forked_from_run_id"], "forked_from_run_id"
    )
    if parent_run_id == run_id:
        raise CanonicalRunServiceError(
            "fork predecessor and successor run_ids must differ"
        )
    _hash(provenance["parent_head_event_hash"], "parent_head_event_hash")
    _hash(provenance["policy_diff_artifact_hash"], "policy_diff_artifact_hash")
    provenance["inherited_evidence_root_hashes"] = _sorted_unique_hashes(
        provenance["inherited_evidence_root_hashes"],
        "inherited_evidence_root_hashes",
    )

    envelope = _exact_mapping(
        fork_policy_diff_artifact,
        {"artifact", "artifact_schema_version", "roles"},
        "fork policy-diff artifact envelope",
    )
    if envelope["artifact_schema_version"] != GOVERNANCE_POLICY_DIFF_VERSION:
        raise CanonicalRunServiceError(
            "fork policy-diff artifact version mismatch"
        )
    if envelope["roles"] != ["policy_diff"]:
        raise CanonicalRunServiceError(
            "fork policy-diff artifact must have only the policy_diff role"
        )
    artifact = _exact_mapping(
        envelope["artifact"],
        {
            "changes",
            "child_run_id",
            "fork_reason",
            "from_effective_policy_hash",
            "governance_policy_diff_schema_version",
            "operator_confirmation",
            "parent_run_id",
            "to_effective_policy_hash",
        },
        "governance policy diff",
    )
    if artifact["governance_policy_diff_schema_version"] != (
        GOVERNANCE_POLICY_DIFF_VERSION
    ):
        raise CanonicalRunServiceError("governance policy-diff version mismatch")
    expected = {
        "child_run_id": run_id,
        "fork_reason": provenance["fork_reason"],
        "parent_run_id": parent_run_id,
        "to_effective_policy_hash": effective_policy_hash,
    }
    for field, expected_value in expected.items():
        if artifact[field] != expected_value:
            raise CanonicalRunServiceError(
                f"governance policy-diff {field} mismatch"
            )
    from_hash = _hash(
        artifact["from_effective_policy_hash"], "from_effective_policy_hash"
    )
    _hash(artifact["to_effective_policy_hash"], "to_effective_policy_hash")
    _validate_confirmation(artifact["operator_confirmation"], created_at)
    raw_changes = artifact["changes"]
    if not isinstance(raw_changes, list):
        raise CanonicalRunServiceError(
            "governance policy-diff changes must be an array"
        )
    changes: list[dict[str, Any]] = []
    for raw in raw_changes:
        change = _exact_mapping(
            raw,
            {
                "comparison",
                "field_path",
                "prior_value_hash",
                "resulting_value_hash",
            },
            "governance policy change",
        )
        if change["comparison"] not in {"replaceable", "tighter"}:
            raise CanonicalRunServiceError(
                "governance policy change comparison is unsupported"
            )
        _text(change["field_path"], "field_path")
        _hash(change["prior_value_hash"], "prior_value_hash")
        _hash(change["resulting_value_hash"], "resulting_value_hash")
        if change["prior_value_hash"] == change["resulting_value_hash"]:
            raise CanonicalRunServiceError(
                "governance policy change must change the value hash"
            )
        changes.append(change)
    if changes != sorted(changes, key=lambda row: str(row["field_path"])) or len(
        {str(row["field_path"]) for row in changes}
    ) != len(changes):
        raise CanonicalRunServiceError(
            "governance policy changes must be sorted by unique field_path"
        )
    if (from_hash == effective_policy_hash) != (not changes):
        raise CanonicalRunServiceError(
            "governance policy-diff changes do not match its policy hashes"
        )
    artifact["changes"] = changes
    normalized = ArtifactInput(
        artifact_schema_version=GOVERNANCE_POLICY_DIFF_VERSION,
        roles=("policy_diff",),
        artifact=artifact,
    )
    if normalized.artifact_hash != provenance["policy_diff_artifact_hash"]:
        raise CanonicalRunServiceError(
            "fork policy-diff artifact hash mismatch"
        )
    canonical_bytes(provenance)
    canonical_bytes(artifact)
    return provenance, normalized


def _require_model_actor(actor: ActorContext) -> None:
    if not isinstance(actor, ActorContext) or actor.provenance_class != "model":
        raise CanonicalRunServiceError("model ActorContext is required")
    try:
        require_capability(actor, "submit_model_candidate")
    except PermissionError as exc:
        raise CanonicalRunServiceError(str(exc)) from exc


def _require_operator_actor(actor: ActorContext, capability: str) -> None:
    if not isinstance(actor, ActorContext) or actor.provenance_class != "operator":
        raise CanonicalRunServiceError("operator ActorContext is required")
    try:
        require_capability(actor, capability)
    except PermissionError as exc:
        raise CanonicalRunServiceError(str(exc)) from exc


def _mapping_run_id(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise ContextRefusal("context manifest must be an object")
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ContextRefusal("context manifest requires run_id")
    return run_id


def _exact_mapping(
    value: Mapping[str, Any], fields: set[str], label: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CanonicalRunServiceError(f"{label} has invalid fields")
    return dict(value)


def _closed_mapping(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalRunServiceError(f"{label} must be an object")
    fields = set(value)
    if required - fields or fields - required - optional:
        raise CanonicalRunServiceError(f"{label} has invalid fields")
    return dict(value)


def _sorted_unique_hashes(value: Any, field: str) -> list[str]:
    values = _sorted_unique_text(value, field)
    for item in values:
        _hash(item, field)
    return values


def _validate_relevant_artifact_revisions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise ContextRefusal("relevant_artifact_revisions must be an object array")
    normalized = [dict(row) for row in value]
    expected_order = sorted(
        normalized,
        key=lambda row: (
            str(row.get("role", "")),
            str(row.get("artifact_hash", "")),
            row.get("revision", -1),
        ),
    )
    if normalized != expected_order:
        raise ContextRefusal("relevant artifact revisions must be deterministically sorted")
    for row in normalized:
        if set(row) != {
            "artifact_hash",
            "artifact_schema_version",
            "revision",
            "role",
        }:
            raise ContextRefusal("relevant artifact revision has invalid fields")
        _hash(row["artifact_hash"], "artifact_hash")
        _text(row["artifact_schema_version"], "artifact_schema_version")
        _text(row["role"], "role")
        revision = row["revision"]
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ContextRefusal("artifact revision must be a non-negative integer")
    if len({canonical_hash(row) for row in normalized}) != len(normalized):
        raise ContextRefusal("relevant artifact revisions must be unique")
    return normalized


def _sorted_unique_text(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise CanonicalRunServiceError(f"{field} must be a string array")
    if value != sorted(set(value)):
        raise CanonicalRunServiceError(f"{field} must be sorted and unique")
    return list(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CanonicalRunServiceError(f"{field} must be non-empty text")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CanonicalRunServiceError(
            f"{field} must be a non-negative integer"
        )
    return value


def _hash(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise CanonicalRunServiceError(f"{field} must be a lowercase SHA-256 hash")
    return text


__all__ = [
    "ACTION_RECEIPT_VERSION",
    "CANONICAL_RUN_PROTECTED_EXPORT_VERSION",
    "CONTEXT_MANIFEST_VERSION",
    "EXTERNAL_CODEX_REF_VERSION",
    "GOVERNANCE_POLICY_DIFF_VERSION",
    "MODEL_CANDIDATE_VERSION",
    "OPERATOR_VISIBLE_PROPOSAL_VERSION",
    "RUN_SNAPSHOT_ATTESTATION_VERSION",
    "CanonicalRunService",
    "CanonicalRunServiceError",
    "ContextArtifact",
    "ContextRefusal",
    "ServiceActionResult",
]
