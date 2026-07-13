from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest

from nepsis_cgn.canonical_runs.private_api import (
    PrivateOperatorRunConfig,
    ServiceActionResult,
    create_private_operator_run_app,
    validate_private_operator_run_config,
)
from nepsis_cgn.canonical_runs.profile_registry import GovernanceProfileRegistry
from nepsis_cgn.canonical_runs.actualization import (
    CANONICAL_ACTUALIZATION_POLICY_BINDING,
    PERFORM_ZEROBACK_ACTION_TYPE,
    RELEASE_STILL_ACTION_TYPE,
    REQUEST_DECISION_COMMIT_ACTION_TYPE,
    validate_decision_commit,
    validate_release_still,
    validate_zeroback,
)
from nepsis_cgn.canonical_runs.operator_disposition import (
    OPERATOR_DISPOSITION_POLICY_BINDING,
    validate_operator_disposition,
)
from nepsis_cgn.canonical_runs.service import (
    CanonicalRunService as RealCanonicalRunService,
    ContextArtifact,
)
from nepsis_cgn.canonical_runs.store import (
    AdmissionDecision,
    CanonicalRunStore,
)
from nepsis_cgn.contracts.canonical_json import canonical_hash
from nepsis_cgn.contracts.canonical_run import ActorContext
from nepsis_cgn.verification.canonical_run_export import (
    verify_protected_canonical_run_export,
)
from nepsis_cgn.verification.receipts import build_trust_anchor


RUN_ID = "run-001"
ZEROBACK_RUN_ID = "run-zeroback"


def model_actor() -> ActorContext:
    return ActorContext(
        actor_id="model:codex",
        provenance_class="model",
        capability_id="cap-model",
        capabilities=frozenset({"read_snapshot", "submit_model_candidate"}),
    )


def operator_actor() -> ActorContext:
    return ActorContext(
        actor_id="operator:local",
        provenance_class="operator",
        capability_id="cap-operator",
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
    )


def validator_actor() -> ActorContext:
    return ActorContext(
        actor_id="validator:detached",
        provenance_class="validator",
        capability_id="cap-validator",
        capabilities=frozenset({"export_run", "read_snapshot"}),
    )


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.outcome: ServiceActionResult | None = ServiceActionResult(
            receipt={
                "action_receipt_schema_version": "nepsis.action_receipt@0.1.0",
                "receipt_id": "receipt-001",
                "signature": {"value": "signed-value"},
            },
            replayed=True,
        )

    def _record(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))

    def create_run(self, **kwargs: Any) -> ServiceActionResult:
        self._record("create_run", **kwargs)
        assert self.outcome is not None
        return self.outcome

    def read_snapshot(
        self, *, run_id: str, actor: ActorContext
    ) -> Mapping[str, Any]:
        self._record("read_snapshot", run_id=run_id, actor=actor)
        return {"head_sequence": 4, "run_id": run_id}

    def build_context_manifest(
        self, *, run_id: str, actor: ActorContext
    ) -> ContextArtifact:
        self._record("build_context_manifest", run_id=run_id, actor=actor)
        artifact = {
            "context_manifest_schema_version": "nepsis.context_manifest@0.1.0",
            "run_id": run_id,
        }
        return ContextArtifact(
            artifact=artifact,
            artifact_hash="a" * 64,
        )

    def build_snapshot_attestation(
        self,
        *,
        run_id: str,
        actor: ActorContext,
        challenge_hash: str,
    ) -> Mapping[str, Any]:
        self._record(
            "build_snapshot_attestation",
            run_id=run_id,
            actor=actor,
            challenge_hash=challenge_hash,
        )
        return {
            "challenge_hash": challenge_hash,
            "run_id": run_id,
            "signature": {"algorithm": "ed25519"},
        }

    def submit_model_candidate(self, **kwargs: Any) -> ServiceActionResult:
        self._record("submit_model_candidate", **kwargs)
        assert self.outcome is not None
        return self.outcome

    def submit_operator_action(self, **kwargs: Any) -> ServiceActionResult:
        self._record("submit_operator_action", **kwargs)
        assert self.outcome is not None
        return self.outcome

    def query_outcome(
        self,
        *,
        run_id: str,
        actor: ActorContext,
        idempotency_key: str,
    ) -> ServiceActionResult | None:
        self._record(
            "query_outcome",
            run_id=run_id,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        return self.outcome

    def export_run(
        self, *, run_id: str, actor: ActorContext
    ) -> Mapping[str, Any]:
        self._record("export_run", run_id=run_id, actor=actor)
        return {
            "events": [],
            "export_schema_version": "nepsis.canonical_run_store_export@0.1.0",
            "run": {"run_id": run_id},
        }


def resolver(token: str) -> ActorContext | None:
    return {
        "model-token": model_actor(),
        "operator-token": operator_actor(),
        "validator-token": validator_actor(),
    }.get(token)


def config(**changes: Any) -> PrivateOperatorRunConfig:
    values = {
        "bind_host": "127.0.0.1",
        "durable_store_path": Path.home() / ".nepsis" / "canonical-runs.db",
        "enabled": True,
    }
    values.update(changes)
    return PrivateOperatorRunConfig(**values)


def client(service: FakeService | None = None) -> tuple[TestClient, FakeService]:
    fake = service or FakeService()
    app = create_private_operator_run_app(
        service=fake,
        resolve_token=resolver,
        resolve_operator_validator=lambda capability, action_type: (
            lambda request, snapshot: AdmissionDecision.accept()
        ),
        config=config(),
    )
    return TestClient(app), fake


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def model_body(**changes: Any) -> dict[str, Any]:
    body = {
        "capability": "submit_model_candidate",
        "capability_id": "cap-model",
        "context_manifest": {"run_id": RUN_ID},
        "created_at": "2026-07-12T16:01:00.000Z",
        "external_codex_ref": {"run_id": RUN_ID},
        "idempotency_key": "candidate-001",
        "operator_visible_proposal": {"requested_change": {"candidate": "option_a"}},
        "run_id": RUN_ID,
        "trusted_adapter_intent_id": "adapter-intent-001",
    }
    body.update(changes)
    return body


def operator_body(**changes: Any) -> dict[str, Any]:
    body = {
        "capability": "submit_operator_disposition",
        "capability_id": "cap-operator",
        "action_type": "record_operator_disposition",
        "confirmation": {
            "confirmed": True,
            "confirmed_at": "2026-07-12T16:01:00.000Z",
            "consequence_acknowledged": True,
            "rationale": "Reviewed.",
        },
        "created_at": "2026-07-12T16:01:00.000Z",
        "effective_policy_hash": "a" * 64,
        "expected_head_event_hash": "b" * 64,
        "expected_head_sequence": 0,
        "idempotency_key": "operator-001",
        "operator_governance_profile_hash": "c" * 64,
        "payload": {
            "disposition": "accept",
            "operator_visible_proposal_hash": "e" * 64,
            "run_id": RUN_ID,
        },
        "run_id": RUN_ID,
        "session_governance_snapshot_hash": "d" * 64,
        "trusted_adapter_intent_id": "operator-intent-001",
    }
    body.update(changes)
    return body


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"enabled": False}, "disabled"),
        ({"bind_host": "0.0.0.0"}, "loopback"),
        ({"bind_host": "localhost"}, "literal loopback"),
        ({"durable_store_path": Path("relative.db")}, "absolute"),
        ({"durable_store_path": Path("/tmp/canonical.db")}, "temporary"),
    ],
)
def test_startup_config_fails_closed(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_private_operator_run_config(config(**changes))


def test_private_app_has_no_public_or_discovery_surface() -> None:
    http, fake = client()

    assert http.get("/v1/operator-runs").status_code == 404
    assert http.get("/v1/mvp").status_code == 404
    assert http.get("/openapi.json").status_code == 404
    assert http.get("/docs").status_code == 404
    assert fake.calls == []


def test_profile_routes_are_present_only_when_injected_and_require_auth() -> None:
    fake = FakeService()
    app = create_private_operator_run_app(
        service=fake,
        resolve_token=resolver,
        resolve_operator_validator=lambda capability, action_type: (
            validate_operator_disposition
            if (
                capability == "submit_operator_disposition"
                and action_type == "record_operator_disposition"
            )
            else None
        ),
        config=config(),
        profile_registry=GovernanceProfileRegistry.in_memory(),
    )
    http = TestClient(app)
    assert http.get("/v1/operator-profiles/active").status_code == 401
    assert (
        http.post(
            "/v1/operator-profiles/profile-local/revisions", json={}
        ).status_code
        == 401
    )
    assert (
        http.post(
            "/v1/operator-profiles/profile-local/session-snapshots", json={}
        ).status_code
        == 401
    )
    assert fake.calls == []


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("post", f"/v1/operator-runs/{RUN_ID}", {"run_id": RUN_ID}),
        ("get", f"/v1/operator-runs/{RUN_ID}/snapshot", None),
        ("post", f"/v1/operator-runs/{RUN_ID}/context-manifests", None),
        (
            "post",
            f"/v1/operator-runs/{RUN_ID}/model-candidates",
            model_body(),
        ),
        (
            "post",
            f"/v1/operator-runs/{RUN_ID}/operator-actions",
            operator_body(),
        ),
        ("get", f"/v1/operator-runs/{RUN_ID}/outcomes/request-001", None),
        ("get", f"/v1/operator-runs/{RUN_ID}/export", None),
    ],
)
def test_every_private_route_rejects_unauthenticated_access(
    method: str, path: str, body: dict[str, Any] | None
) -> None:
    http, fake = client()

    response = http.request(method.upper(), path, json=body)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert fake.calls == []


def test_invalid_token_and_resolver_failure_both_fail_closed() -> None:
    http, fake = client()
    assert (
        http.get(
            f"/v1/operator-runs/{RUN_ID}/snapshot",
            headers=auth("invalid"),
        ).status_code
        == 401
    )
    assert fake.calls == []

    app = create_private_operator_run_app(
        service=fake,
        resolve_token=lambda token: (_ for _ in ()).throw(RuntimeError(token)),
        resolve_operator_validator=lambda capability, action_type: (
            lambda request, snapshot: AdmissionDecision.accept()
        ),
        config=config(),
    )
    failed = TestClient(app).get(
        f"/v1/operator-runs/{RUN_ID}/snapshot",
        headers=auth("secret-value"),
    )
    assert failed.status_code == 401
    assert "secret-value" not in failed.text


def test_snapshot_manifest_and_export_use_authenticated_actor_context() -> None:
    http, fake = client()

    snapshot = http.get(
        f"/v1/operator-runs/{RUN_ID}/snapshot", headers=auth("model-token")
    )
    manifest = http.post(
        f"/v1/operator-runs/{RUN_ID}/context-manifests",
        headers=auth("model-token"),
    )
    challenge_hash = hashlib.sha256(b"fresh-resume-challenge").hexdigest()
    attestation = http.post(
        f"/v1/operator-runs/{RUN_ID}/snapshot-attestations",
        headers=auth("model-token"),
        json={"challenge_hash": challenge_hash},
    )
    exported = http.get(
        f"/v1/operator-runs/{RUN_ID}/export",
        headers=auth("validator-token"),
    )

    assert snapshot.status_code == 200
    assert manifest.status_code == 200
    assert attestation.status_code == 200
    assert attestation.json()["challenge_hash"] == challenge_hash
    assert exported.status_code == 200
    assert fake.calls[0][1]["actor"] == model_actor()
    assert fake.calls[1][1]["actor"] == model_actor()
    assert fake.calls[2] == (
        "build_snapshot_attestation",
        {
            "actor": model_actor(),
            "challenge_hash": challenge_hash,
            "run_id": RUN_ID,
        },
    )
    assert fake.calls[3][1]["actor"] == validator_actor()


def test_snapshot_attestation_rejects_authority_claims_and_extra_fields() -> None:
    http, fake = client()
    challenge_hash = hashlib.sha256(b"challenge").hexdigest()

    authority = http.post(
        f"/v1/operator-runs/{RUN_ID}/snapshot-attestations",
        headers=auth("model-token"),
        json={"actor_id": "operator:forged", "challenge_hash": challenge_hash},
    )
    extra = http.post(
        f"/v1/operator-runs/{RUN_ID}/snapshot-attestations",
        headers=auth("model-token"),
        json={"challenge_hash": challenge_hash, "head_sequence": 4},
    )

    assert authority.status_code == 400
    assert extra.status_code == 400
    assert fake.calls == []


def test_context_manifest_route_rejects_client_authored_manifest_fields() -> None:
    http, fake = client()

    response = http.post(
        f"/v1/operator-runs/{RUN_ID}/context-manifests",
        headers=auth("model-token"),
        json={"actor_id": "operator:forged", "omit_red": True},
    )

    assert response.status_code == 400
    assert fake.calls == []


def test_run_creation_refuses_when_profile_registry_is_unavailable() -> None:
    http, fake = client()
    response = http.post(
        f"/v1/operator-runs/{RUN_ID}",
        headers=auth("operator-token"),
        json={"run_id": RUN_ID},
    )
    assert response.status_code == 503
    assert fake.calls == []


def test_model_candidate_uses_model_context_and_keeps_replay_outside_receipt() -> None:
    http, fake = client()

    response = http.post(
        f"/v1/operator-runs/{RUN_ID}/model-candidates",
        headers=auth("model-token"),
        json=model_body(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["delivery"] == {"replayed": True}
    assert "replayed" not in payload["receipt"]
    assert payload["receipt"]["receipt_id"] == "receipt-001"
    assert fake.calls[-1][0] == "submit_model_candidate"
    assert fake.calls[-1][1]["actor"] == model_actor()


def test_operator_action_uses_operator_context() -> None:
    http, fake = client()

    response = http.post(
        f"/v1/operator-runs/{RUN_ID}/operator-actions",
        headers=auth("operator-token"),
        json=operator_body(),
    )

    assert response.status_code == 200
    assert fake.calls[-1][0] == "submit_operator_action"
    assert fake.calls[-1][1]["actor"] == operator_actor()


@pytest.mark.parametrize(
    ("token", "path", "body"),
    [
        (
            "model-token",
            f"/v1/operator-runs/{RUN_ID}/operator-actions",
            operator_body(capability_id="cap-model"),
        ),
        (
            "operator-token",
            f"/v1/operator-runs/{RUN_ID}/model-candidates",
            model_body(capability_id="cap-operator"),
        ),
    ],
)
def test_model_and_operator_mutation_capabilities_are_distinct(
    token: str, path: str, body: dict[str, Any]
) -> None:
    http, fake = client()

    response = http.post(path, headers=auth(token), json=body)

    assert response.status_code == 403
    assert fake.calls == []


def test_route_and_body_run_id_must_match() -> None:
    http, fake = client()

    response = http.post(
        f"/v1/operator-runs/{RUN_ID}/model-candidates",
        headers=auth("model-token"),
        json=model_body(run_id="run-other"),
    )

    assert response.status_code == 400
    assert fake.calls == []


@pytest.mark.parametrize(
    "claim",
    [
        {"actor_id": "operator:forged", "provenance_class": "operator"},
        {
            "payload": {
                "actor_id": "operator:forged",
                "candidate": "option_a",
                "provenance_class": "operator",
            },
        },
    ],
)
def test_payload_authority_claims_cannot_elevate(claim: dict[str, Any]) -> None:
    http, fake = client()
    body = model_body()
    body.update(claim)

    response = http.post(
        f"/v1/operator-runs/{RUN_ID}/model-candidates",
        headers=auth("model-token"),
        json=body,
    )

    assert response.status_code == 400
    assert fake.calls == []


def test_capability_id_is_bound_to_resolved_actor() -> None:
    http, fake = client()

    response = http.post(
        f"/v1/operator-runs/{RUN_ID}/model-candidates",
        headers=auth("model-token"),
        json=model_body(capability_id="cap-operator"),
    )

    assert response.status_code == 403
    assert fake.calls == []


def test_query_outcome_preserves_unsigned_delivery_metadata_boundary() -> None:
    http, fake = client()

    response = http.get(
        f"/v1/operator-runs/{RUN_ID}/outcomes/request-001",
        headers=auth("model-token"),
    )

    assert response.status_code == 200
    assert response.json()["delivery"]["replayed"] is True
    assert "replayed" not in response.json()["receipt"]
    assert fake.calls[-1][1]["idempotency_key"] == "request-001"


def test_missing_outcome_returns_404_without_manufacturing_receipt() -> None:
    fake = FakeService()
    fake.outcome = None
    http, _ = client(fake)

    response = http.get(
        f"/v1/operator-runs/{RUN_ID}/outcomes/missing",
        headers=auth("operator-token"),
    )

    assert response.status_code == 404


def test_private_http_actualizes_accepted_proposal_and_verifies_export() -> None:
    store = CanonicalRunStore.in_memory()
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    service = RealCanonicalRunService(
        store=store,
        private_key=private_key,
        trust_anchor=build_trust_anchor(
            private_key.public_key(), activated_at="2026-07-01T00:00:00.000Z"
        ),
    )
    packet = {
        "context_state": {
            "data_classification": "synthetic",
            "denominator_collapse_active": False,
            "evidence_root_hash": hashlib.sha256(b"evidence").hexdigest(),
            "frame_root_hash": hashlib.sha256(b"frame").hexdigest(),
            "observation_root_hash": hashlib.sha256(b"observations").hexdigest(),
            "population_root_hash": hashlib.sha256(b"population").hexdigest(),
            "relevant_artifact_revisions": [],
            "remote_inference_authorized": False,
            "unresolved_contradiction_hashes": [],
            "unresolved_red_hazard_hashes": [],
        },
        "packet_schema_version": "nepsis.synthetic_packet@0.1.0",
        "revision": 0,
    }
    profile_hash = hashlib.sha256(b"profile").hexdigest()
    snapshot_hash = hashlib.sha256(b"snapshot").hexdigest()
    effective_hash = hashlib.sha256(b"effective").hexdigest()
    registry_snapshot = {
        "effective_policy_hash": effective_hash,
        "operator_governance_profile_hash": profile_hash,
    }

    class PinnedRegistry:
        def get_session_snapshot_result(self, run_id: str) -> dict[str, Any]:
            assert run_id in {RUN_ID, ZEROBACK_RUN_ID}
            return {
                "outcome": "accepted",
                "snapshot": registry_snapshot,
                "snapshot_hash": snapshot_hash,
            }

    app = create_private_operator_run_app(
        service=service,
        resolve_token=resolver,
        resolve_operator_validator=lambda capability, action_type: {
            (
                "submit_operator_disposition",
                "record_operator_disposition",
            ): validate_operator_disposition,
            ("release_still", RELEASE_STILL_ACTION_TYPE): validate_release_still,
            (
                "request_decision_commit",
                REQUEST_DECISION_COMMIT_ACTION_TYPE,
            ): validate_decision_commit,
            ("perform_zeroback", PERFORM_ZEROBACK_ACTION_TYPE): validate_zeroback,
        }.get((capability, action_type)),
        config=config(),
        profile_registry=PinnedRegistry(),  # type: ignore[arg-type]
    )
    http = TestClient(app)
    created_at = "2026-07-12T16:00:00.000Z"
    create_body = {
        "created_at": created_at,
        "effective_policy_hash": effective_hash,
        "idempotency_key": "create-001",
        "initial_packet_projection": packet,
        "initial_postcondition": {
            "active_hold": False,
            "governance_status": "open",
            "packet_projection_hash": canonical_hash(packet),
            "phase": "intake",
        },
        "operator_governance_profile_hash": profile_hash,
        "owner_id": "operator:local",
        "run_id": RUN_ID,
        "session_governance_snapshot_hash": snapshot_hash,
        "system_policy_bindings": [
            {
                "policy_hash": hashlib.sha256(b"policy").hexdigest(),
                "policy_id": "canonical-run",
                "policy_version": "nepsis.canonical_run_policy@0.1.0",
            },
            OPERATOR_DISPOSITION_POLICY_BINDING,
            CANONICAL_ACTUALIZATION_POLICY_BINDING,
        ],
    }
    created = http.post(
        f"/v1/operator-runs/{RUN_ID}",
        headers=auth("operator-token"),
        json=create_body,
    )
    assert created.status_code == 200, created.text
    assert created.json()["receipt"]["outcome"] == "committed"
    assert service.verify_receipt(created.json()["receipt"])

    manifest_response = http.post(
        f"/v1/operator-runs/{RUN_ID}/context-manifests",
        headers=auth("model-token"),
    )
    assert manifest_response.status_code == 200, manifest_response.text
    context_manifest = manifest_response.json()["artifact"]
    requested_change = {
        "base_event_hash": context_manifest["run_head_event_hash"],
        "model_proposed_tier": "T2",
        "operation_type": "replace",
        "proposed_value": "Keep the decision reversible.",
        "target_path": "analysis.current_summary",
    }
    proposal = {
        "alternatives_summary": "No-op remains available.",
        "evidence_refs": [],
        "hazards_summary": "Synthetic only.",
        "operator_visible_proposal_schema_version": (
            "nepsis.operator_visible_proposal@0.1.0"
        ),
        "proposal_text": "Record option A for review.",
        "rationale_text": "The proposal is reversible.",
        "requested_change": requested_change,
    }
    external_ref = service.build_external_codex_ref(
        actor=model_actor(),
        run_id=RUN_ID,
        adapter_version="adapter-0.1.0",
        created_at="2026-07-12T16:01:00.000Z",
        thread_id="thread-001",
        turn_id="turn-001",
        tool_call_id="tool-001",
        model_id="gpt-test",
        model_configuration_epoch="model-config-001",
        operator_visible_proposal_hash=canonical_hash(proposal),
    )
    candidate_body = {
        "capability": "submit_model_candidate",
        "capability_id": "cap-model",
        "context_manifest": context_manifest,
        "created_at": "2026-07-12T16:01:00.000Z",
        "external_codex_ref": external_ref,
        "idempotency_key": "candidate-001",
        "operator_visible_proposal": proposal,
        "run_id": RUN_ID,
        "trusted_adapter_intent_id": "adapter-intent-001",
    }
    first = http.post(
        f"/v1/operator-runs/{RUN_ID}/model-candidates",
        headers=auth("model-token"),
        json=candidate_body,
    )
    replay = http.post(
        f"/v1/operator-runs/{RUN_ID}/model-candidates",
        headers=auth("model-token"),
        json=candidate_body,
    )
    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json()["receipt"]["outcome"] == "candidate_recorded"
    assert service.verify_receipt(first.json()["receipt"])
    assert first.json()["receipt"] == replay.json()["receipt"]
    assert first.json()["delivery"] == {"replayed": False}
    assert replay.json()["delivery"] == {"replayed": True}

    challenge_hash = hashlib.sha256(b"real-resume-challenge").hexdigest()
    attested = http.post(
        f"/v1/operator-runs/{RUN_ID}/snapshot-attestations",
        headers=auth("model-token"),
        json={"challenge_hash": challenge_hash},
    )
    assert attested.status_code == 200, attested.text
    assert attested.json()["challenge_hash"] == challenge_hash
    assert attested.json()["head_event_hash"] == first.json()["receipt"][
        "resulting_head_event_hash"
    ]
    assert service.verify_receipt(attested.json())

    operator_body_value = {
        "action_type": "record_operator_disposition",
        "capability": "submit_operator_disposition",
        "capability_id": "cap-operator",
        "confirmation": {
            "confirmed": True,
            "confirmed_at": "2026-07-12T16:02:00.000Z",
            "consequence_acknowledged": True,
            "rationale": "Reviewed against the exact candidate head.",
        },
        "created_at": "2026-07-12T16:02:00.000Z",
        "effective_policy_hash": effective_hash,
        "expected_head_event_hash": first.json()["receipt"][
            "resulting_head_event_hash"
        ],
        "expected_head_sequence": first.json()["receipt"][
            "resulting_head_sequence"
        ],
        "idempotency_key": "operator-001",
        "operator_governance_profile_hash": profile_hash,
        "payload": {
            "disposition": "accept",
            "operator_visible_proposal_hash": canonical_hash(proposal),
            "run_id": RUN_ID,
        },
        "run_id": RUN_ID,
        "session_governance_snapshot_hash": snapshot_hash,
        "trusted_adapter_intent_id": "operator-intent-001",
    }
    operator_first = http.post(
        f"/v1/operator-runs/{RUN_ID}/operator-actions",
        headers=auth("operator-token"),
        json=operator_body_value,
    )
    operator_replay = http.post(
        f"/v1/operator-runs/{RUN_ID}/operator-actions",
        headers=auth("operator-token"),
        json=operator_body_value,
    )
    stale_body = {
        **operator_body_value,
        "idempotency_key": "operator-stale",
        "trusted_adapter_intent_id": "operator-intent-stale",
    }
    operator_stale = http.post(
        f"/v1/operator-runs/{RUN_ID}/operator-actions",
        headers=auth("operator-token"),
        json=stale_body,
    )
    assert operator_first.status_code == 200, operator_first.text
    assert operator_replay.status_code == 200, operator_replay.text
    assert operator_first.json()["receipt"] == operator_replay.json()["receipt"]
    assert operator_first.json()["delivery"] == {"replayed": False}
    assert operator_replay.json()["delivery"] == {"replayed": True}
    assert operator_stale.status_code == 200, operator_stale.text
    assert operator_stale.json()["receipt"]["outcome"] == "stale_head"
    assert operator_stale.json()["receipt"]["advanced_head"] is False
    assert service.verify_receipt(operator_first.json()["receipt"])
    assert service.verify_receipt(operator_stale.json()["receipt"])

    def actualization_body(
        *,
        capability: str,
        action_type: str,
        payload: dict[str, Any],
        prior_receipt: Mapping[str, Any],
        created_at: str,
        idempotency_key: str,
        run_id: str = RUN_ID,
    ) -> dict[str, Any]:
        return {
            "action_type": action_type,
            "capability": capability,
            "capability_id": "cap-operator",
            "confirmation": {
                "confirmed": True,
                "confirmed_at": created_at,
                "consequence_acknowledged": True,
                "rationale": f"Confirm {action_type} through the private API.",
            },
            "created_at": created_at,
            "effective_policy_hash": effective_hash,
            "expected_head_event_hash": prior_receipt[
                "resulting_head_event_hash"
            ],
            "expected_head_sequence": prior_receipt["resulting_head_sequence"],
            "idempotency_key": idempotency_key,
            "operator_governance_profile_hash": profile_hash,
            "payload": payload,
            "run_id": run_id,
            "session_governance_snapshot_hash": snapshot_hash,
            "trusted_adapter_intent_id": f"adapter:{idempotency_key}",
        }

    release = http.post(
        f"/v1/operator-runs/{RUN_ID}/operator-actions",
        headers=auth("operator-token"),
        json=actualization_body(
            capability="release_still",
            action_type=RELEASE_STILL_ACTION_TYPE,
            payload={
                "operator_visible_proposal_hash": canonical_hash(proposal),
                "run_id": RUN_ID,
            },
            prior_receipt=operator_first.json()["receipt"],
            created_at="2026-07-12T16:03:00.000Z",
            idempotency_key="release-still-001",
        ),
    )
    assert release.status_code == 200, release.text
    assert release.json()["receipt"]["outcome"] == "committed"
    assert service.verify_receipt(release.json()["receipt"])

    commit = http.post(
        f"/v1/operator-runs/{RUN_ID}/operator-actions",
        headers=auth("operator-token"),
        json=actualization_body(
            capability="request_decision_commit",
            action_type=REQUEST_DECISION_COMMIT_ACTION_TYPE,
            payload={
                "operator_visible_proposal_hash": canonical_hash(proposal),
                "requested_change": requested_change,
                "run_id": RUN_ID,
            },
            prior_receipt=release.json()["receipt"],
            created_at="2026-07-12T16:04:00.000Z",
            idempotency_key="decision-commit-001",
        ),
    )
    assert commit.status_code == 200, commit.text
    assert commit.json()["receipt"]["outcome"] == "committed"
    assert commit.json()["receipt"]["actor_id"] == "operator:local"
    assert commit.json()["receipt"]["provenance_class"] == "operator"
    assert service.verify_receipt(commit.json()["receipt"])

    exported = http.get(
        f"/v1/operator-runs/{RUN_ID}/export",
        headers=auth("validator-token"),
    )
    assert exported.status_code == 200, exported.text
    protected_export = exported.json()
    assert [event["event_type"] for event in protected_export["events"]] == [
        "run_created",
        "model_candidate_recorded",
        "operator_proposal_disposition_recorded",
        "still_released",
        "decision_committed",
    ]
    assert protected_export["protected_export_schema_version"] == (
        "nepsis.canonical_run_protected_export@0.1.0"
    )
    assert len(protected_export["action_receipts"]) == 6
    assert protected_export["export_root_hash"] == canonical_hash(
        {
            key: value
            for key, value in protected_export.items()
            if key != "export_root_hash"
        }
    )
    decision_event = protected_export["events"][-1]
    assert decision_event["actor_id"].startswith("validator:")
    assert decision_event["provenance_class"] == "validator"
    assert decision_event["payload"]["requested_by_actor_id"] == "operator:local"
    application = protected_export["packet_projection"][
        "operator_proposal_application"
    ]
    assert application["requested_change_hash"] == canonical_hash(requested_change)
    assert protected_export["packet_projection"]["fields"][
        application["field_id"]
    ] == {
        "target_path": "analysis.current_summary",
        "value": "Keep the decision reversible.",
    }
    report = verify_protected_canonical_run_export(protected_export)
    assert report["valid"] is True
    assert report["actualization_lifecycle"] == {
        "decision_committed": 1,
        "observed": True,
        "still_released": 1,
        "zeroback_performed": 0,
    }
    assert "canonical_actualization_lifecycle" in report["verified_checks"]

    zeroback_create_body = {
        **create_body,
        "idempotency_key": "create-zeroback-001",
        "run_id": ZEROBACK_RUN_ID,
    }
    zeroback_created = http.post(
        f"/v1/operator-runs/{ZEROBACK_RUN_ID}",
        headers=auth("operator-token"),
        json=zeroback_create_body,
    )
    assert zeroback_created.status_code == 200, zeroback_created.text
    assert service.verify_receipt(zeroback_created.json()["receipt"])
    replacement_frame = hashlib.sha256(b"replacement-frame").hexdigest()
    zeroback = http.post(
        f"/v1/operator-runs/{ZEROBACK_RUN_ID}/operator-actions",
        headers=auth("operator-token"),
        json=actualization_body(
            capability="perform_zeroback",
            action_type=PERFORM_ZEROBACK_ACTION_TYPE,
            payload={
                "replacement_frame_root_hash": replacement_frame,
                "run_id": ZEROBACK_RUN_ID,
            },
            prior_receipt=zeroback_created.json()["receipt"],
            created_at="2026-07-12T16:05:00.000Z",
            idempotency_key="zeroback-001",
            run_id=ZEROBACK_RUN_ID,
        ),
    )
    assert zeroback.status_code == 200, zeroback.text
    assert zeroback.json()["receipt"]["outcome"] == "committed"
    assert service.verify_receipt(zeroback.json()["receipt"])

    zeroback_export = http.get(
        f"/v1/operator-runs/{ZEROBACK_RUN_ID}/export",
        headers=auth("validator-token"),
    )
    assert zeroback_export.status_code == 200, zeroback_export.text
    zeroback_protected = zeroback_export.json()
    context_after = zeroback_protected["packet_projection"]["context_state"]
    context_before = packet["context_state"]
    assert context_after["frame_root_hash"] == replacement_frame
    for field in (
        "evidence_root_hash",
        "observation_root_hash",
        "population_root_hash",
        "unresolved_contradiction_hashes",
        "unresolved_red_hazard_hashes",
    ):
        assert context_after[field] == context_before[field]
    zeroback_report = verify_protected_canonical_run_export(zeroback_protected)
    assert zeroback_report["actualization_lifecycle"] == {
        "decision_committed": 0,
        "observed": True,
        "still_released": 0,
        "zeroback_performed": 1,
    }
