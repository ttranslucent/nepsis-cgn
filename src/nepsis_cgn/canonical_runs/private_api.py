from dataclasses import dataclass
import ipaddress
from pathlib import Path
import tempfile
from typing import Any, Mapping, Protocol, runtime_checkable

from nepsis_cgn.contracts.canonical_run import ActorContext, require_capability
from nepsis_cgn.canonical_runs.service import (
    CanonicalRunServiceError,
    ContextArtifact,
    ContextRefusal,
    ServiceActionResult,
)
from nepsis_cgn.canonical_runs.profile_registry import (
    GovernanceProfileRegistry,
    ProfileRegistryError,
)
from nepsis_cgn.canonical_runs.store import (
    AdmissionValidator,
    RunNotFound,
)


_OPERATOR_ACTION_CAPABILITIES = frozenset(
    {
        "perform_zeroback",
        "release_still",
        "request_decision_commit",
        "submit_operator_disposition",
    }
)
_AUTHORITY_FIELDS = frozenset(
    {
        "actor",
        "actor_id",
        "authority",
        "authorized_as",
        "capabilities",
        "provenance_class",
    }
)


@dataclass(frozen=True)
class PrivateOperatorRunConfig:
    """Explicit startup boundary for the isolated private writer app."""

    enabled: bool
    bind_host: str
    durable_store_path: Path


@runtime_checkable
class CanonicalRunService(Protocol):
    def read_snapshot(
        self, *, run_id: str, actor: ActorContext
    ) -> Mapping[str, Any]: ...

    def build_context_manifest(
        self, *, run_id: str, actor: ActorContext
    ) -> ContextArtifact: ...

    def build_snapshot_attestation(
        self,
        *,
        run_id: str,
        actor: ActorContext,
        challenge_hash: str,
    ) -> Mapping[str, Any]: ...

    def create_run(self, **kwargs: Any) -> ServiceActionResult: ...

    def submit_model_candidate(
        self, **kwargs: Any
    ) -> ServiceActionResult: ...

    def submit_operator_action(
        self, **kwargs: Any
    ) -> ServiceActionResult: ...

    def query_outcome(
        self,
        *,
        run_id: str,
        actor: ActorContext,
        idempotency_key: str,
    ) -> ServiceActionResult | None: ...

    def export_run(
        self, *, run_id: str, actor: ActorContext
    ) -> Mapping[str, Any]: ...


class TrustedActorResolver(Protocol):
    """Resolve an opaque bearer token through a trusted local boundary."""

    def __call__(self, token: str, /) -> ActorContext | None: ...


class TrustedOperatorValidatorResolver(Protocol):
    """Resolve a closed operator action to server-owned validation logic."""

    def __call__(
        self, capability: str, action_type: str, /
    ) -> AdmissionValidator | None: ...


def validate_private_operator_run_config(config: PrivateOperatorRunConfig) -> None:
    """Fail closed unless startup is explicit, loopback-only, and durable."""

    if not isinstance(config, PrivateOperatorRunConfig):
        raise ValueError("private operator-run config is required")
    if config.enabled is not True:
        raise ValueError("private operator-run API is disabled")
    try:
        address = ipaddress.ip_address(config.bind_host)
    except ValueError as exc:
        raise ValueError("bind_host must be a literal loopback IP address") from exc
    if not address.is_loopback:
        raise ValueError("private operator-run API must bind to loopback")
    path = config.durable_store_path.expanduser()
    if not path.is_absolute():
        raise ValueError("durable_store_path must be absolute")
    resolved = path.resolve(strict=False)
    temporary_roots = {
        Path(tempfile.gettempdir()).resolve(strict=False),
        Path("/tmp").resolve(strict=False),
    }
    if any(resolved == root or root in resolved.parents for root in temporary_roots):
        raise ValueError("canonical storage cannot use the temporary directory")


def create_private_operator_run_app(
    *,
    service: CanonicalRunService,
    resolve_token: TrustedActorResolver,
    resolve_operator_validator: TrustedOperatorValidatorResolver,
    config: PrivateOperatorRunConfig,
    profile_registry: GovernanceProfileRegistry | None = None,
) -> Any:
    """Create the isolated protected app without binding a network socket."""

    validate_private_operator_run_config(config)
    if not isinstance(service, CanonicalRunService):
        raise TypeError("service must implement CanonicalRunService")
    if not callable(resolve_token):
        raise TypeError("resolve_token must be callable")
    if not callable(resolve_operator_validator):
        raise TypeError("resolve_operator_validator must be callable")

    try:
        from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "FastAPI runtime is not installed. Install optional API dependencies."
        ) from exc

    app = FastAPI(
        title="NepsisCGN Private Canonical Runs",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    async def authenticate(request: Request) -> None:
        token = _bearer_token(request.headers.get("authorization"))
        if token is None:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            actor = resolve_token(token)
        except Exception as exc:
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        if not isinstance(actor, ActorContext):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized",
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.actor_context = actor

    router = APIRouter(
        prefix="/v1/operator-runs",
        dependencies=[Depends(authenticate)],
    )

    @router.post("/{run_id}")
    async def create_run(
        run_id: str, body: dict[str, Any], request: Request
    ) -> Mapping[str, Any]:
        actor = _actor_from_request(request)
        _require_provenance(actor, {"operator"})
        _require_http_capability(actor, "create_run")
        _reject_authority_claims(body)
        if body.get("run_id") != run_id:
            _raise_http(400, "route run_id does not match request run_id")
        if profile_registry is None:
            _raise_http(503, "governance profile registry is unavailable")
        snapshot_result = _call_profile(
            profile_registry.get_session_snapshot_result, run_id
        )
        if snapshot_result.get("outcome") != "accepted" or not isinstance(
            snapshot_result.get("snapshot"), Mapping
        ):
            _raise_http(409, "run does not have an accepted governance snapshot")
        pinned_snapshot = snapshot_result["snapshot"]
        expected_pins = {
            "effective_policy_hash": pinned_snapshot["effective_policy_hash"],
            "operator_governance_profile_hash": pinned_snapshot[
                "operator_governance_profile_hash"
            ],
            "session_governance_snapshot_hash": snapshot_result["snapshot_hash"],
        }
        if any(body.get(field) != value for field, value in expected_pins.items()):
            _raise_http(409, "run governance pins do not match the registry snapshot")
        if body.get("fork_provenance") != pinned_snapshot.get(
            "fork_provenance"
        ):
            _raise_http(
                409,
                "run fork provenance does not match the registry snapshot",
            )
        if ("fork_policy_diff_artifact" in body) != (
            "fork_provenance" in pinned_snapshot
        ):
            _raise_http(
                409,
                "fork creation requires both pinned provenance and a policy-diff artifact",
            )
        result = _call_service(
            service.create_run,
            actor=actor,
            run_id=run_id,
            owner_id=body.get("owner_id"),
            created_at=body.get("created_at"),
            idempotency_key=body.get("idempotency_key"),
            operator_governance_profile_hash=body.get(
                "operator_governance_profile_hash"
            ),
            session_governance_snapshot_hash=body.get(
                "session_governance_snapshot_hash"
            ),
            effective_policy_hash=body.get("effective_policy_hash"),
            system_policy_bindings=body.get("system_policy_bindings"),
            initial_packet_projection=body.get("initial_packet_projection"),
            initial_postcondition=body.get("initial_postcondition"),
            fork_provenance=body.get("fork_provenance"),
            fork_policy_diff_artifact=body.get("fork_policy_diff_artifact"),
        )
        return _action_response(result)

    @router.get("/{run_id}/snapshot")
    async def read_snapshot(run_id: str, request: Request) -> Mapping[str, Any]:
        actor = _actor_from_request(request)
        _require_http_capability(actor, "read_snapshot")
        return _call_service(
            service.read_snapshot,
            run_id=run_id,
            actor=actor,
        )

    @router.post("/{run_id}/snapshot-attestations")
    async def build_snapshot_attestation(
        run_id: str, body: dict[str, Any], request: Request
    ) -> Mapping[str, Any]:
        actor = _actor_from_request(request)
        _require_http_capability(actor, "read_snapshot")
        _reject_authority_claims(body)
        if set(body) != {"challenge_hash"}:
            _raise_http(400, "snapshot attestation accepts only challenge_hash")
        return _call_service(
            service.build_snapshot_attestation,
            run_id=run_id,
            actor=actor,
            challenge_hash=body.get("challenge_hash"),
        )

    @router.post("/{run_id}/context-manifests")
    async def build_context_manifest(
        run_id: str, request: Request
    ) -> Mapping[str, Any]:
        actor = _actor_from_request(request)
        _require_provenance(actor, {"model", "operator"})
        _require_http_capability(actor, "read_snapshot")
        if await request.body():
            _raise_http(
                400,
                "context manifests are generated from the canonical snapshot and accept no body",
            )
        result = _call_service(
            service.build_context_manifest,
            run_id=run_id,
            actor=actor,
        )
        if not isinstance(result, ContextArtifact):
            raise RuntimeError("canonical run service returned an invalid context artifact")
        return {"artifact": dict(result.artifact), "artifact_hash": result.artifact_hash}

    @router.post("/{run_id}/model-candidates")
    async def submit_model_candidate(
        run_id: str, body: dict[str, Any], request: Request
    ) -> Mapping[str, Any]:
        actor = _actor_from_request(request)
        _require_provenance(actor, {"model"})
        _validate_action_envelope(
            body,
            route_run_id=run_id,
            actor=actor,
            allowed_capabilities={"submit_model_candidate"},
        )
        result = _call_service(
            service.submit_model_candidate,
            actor=actor,
            context_manifest=body.get("context_manifest"),
            operator_visible_proposal=body.get("operator_visible_proposal"),
            external_codex_ref=body.get("external_codex_ref"),
            created_at=body.get("created_at"),
            idempotency_key=body.get("idempotency_key"),
            trusted_adapter_intent_id=body.get("trusted_adapter_intent_id"),
        )
        return _action_response(result)

    @router.post("/{run_id}/operator-actions")
    async def submit_operator_action(
        run_id: str, body: dict[str, Any], request: Request
    ) -> Mapping[str, Any]:
        actor = _actor_from_request(request)
        _require_provenance(actor, {"operator"})
        _validate_action_envelope(
            body,
            route_run_id=run_id,
            actor=actor,
            allowed_capabilities=_OPERATOR_ACTION_CAPABILITIES,
        )
        action_type = body.get("action_type")
        if not isinstance(action_type, str) or not action_type:
            _raise_http(400, "operator action_type is required")
        try:
            validator = resolve_operator_validator(
                str(body["capability"]), action_type
            )
        except Exception as exc:
            _raise_http(400, "operator action is unsupported", cause=exc)
        if validator is None:
            _raise_http(400, "operator action is unsupported")
        result = _call_service(
            service.submit_operator_action,
            actor=actor,
            capability=body.get("capability"),
            action_type=action_type,
            payload=body.get("payload"),
            confirmation=body.get("confirmation"),
            created_at=body.get("created_at"),
            effective_policy_hash=body.get("effective_policy_hash"),
            expected_head_event_hash=body.get("expected_head_event_hash"),
            expected_head_sequence=body.get("expected_head_sequence"),
            idempotency_key=body.get("idempotency_key"),
            operator_governance_profile_hash=body.get(
                "operator_governance_profile_hash"
            ),
            session_governance_snapshot_hash=body.get(
                "session_governance_snapshot_hash"
            ),
            trusted_adapter_intent_id=body.get("trusted_adapter_intent_id"),
            validator=validator,
        )
        return _action_response(result)

    @router.get("/{run_id}/outcomes/{idempotency_key}")
    async def query_outcome(
        run_id: str, idempotency_key: str, request: Request
    ) -> Mapping[str, Any]:
        actor = _actor_from_request(request)
        _require_http_capability(actor, "read_snapshot")
        result = _call_service(
            service.query_outcome,
            run_id=run_id,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Outcome not found")
        return _action_response(result)

    @router.get("/{run_id}/export")
    async def export_run(run_id: str, request: Request) -> Mapping[str, Any]:
        actor = _actor_from_request(request)
        _require_provenance(actor, {"operator", "validator"})
        _require_http_capability(actor, "export_run")
        return _call_service(
            service.export_run,
            run_id=run_id,
            actor=actor,
        )

    app.include_router(router)
    if profile_registry is not None:
        profile_router = APIRouter(
            prefix="/v1/operator-profiles",
            dependencies=[Depends(authenticate)],
        )

        @profile_router.get("/active")
        async def read_active_profile(request: Request) -> Mapping[str, Any]:
            actor = _actor_from_request(request)
            _require_provenance(actor, {"operator"})
            _require_http_capability(actor, "revise_operator_profile")
            active = _call_profile(
                profile_registry.active_profile, operator_id=actor.actor_id
            )
            if active is None:
                raise HTTPException(status_code=404, detail="Active profile not found")
            return active

        @profile_router.post("/{profile_id}/revisions")
        async def create_profile_revision(
            profile_id: str, body: dict[str, Any], request: Request
        ) -> Mapping[str, Any]:
            actor = _actor_from_request(request)
            _require_provenance(actor, {"operator"})
            profile = body.get("profile")
            if not isinstance(profile, Mapping) or profile.get("profile_id") != profile_id:
                _raise_http(400, "route profile_id does not match profile")
            return _call_profile(
                profile_registry.create_revision,
                profile,
                actor=actor,
                expected_head_revision=body.get("expected_head_revision"),
                idempotency_key=body.get("idempotency_key"),
            )

        @profile_router.post("/{profile_id}/revisions/{revision}/activate")
        async def activate_profile_revision(
            profile_id: str,
            revision: int,
            body: dict[str, Any],
            request: Request,
        ) -> Mapping[str, Any]:
            actor = _actor_from_request(request)
            _require_provenance(actor, {"operator"})
            return _call_profile(
                profile_registry.activate,
                profile_id,
                revision,
                actor=actor,
                expected_head_revision=body.get("expected_head_revision"),
                idempotency_key=body.get("idempotency_key"),
                occurred_at=body.get("occurred_at"),
            )

        @profile_router.post("/{profile_id}/revisions/{revision}/revoke")
        async def revoke_profile_revision(
            profile_id: str,
            revision: int,
            body: dict[str, Any],
            request: Request,
        ) -> Mapping[str, Any]:
            actor = _actor_from_request(request)
            _require_provenance(actor, {"operator"})
            return _call_profile(
                profile_registry.revoke,
                profile_id,
                revision,
                actor=actor,
                expected_head_revision=body.get("expected_head_revision"),
                idempotency_key=body.get("idempotency_key"),
                occurred_at=body.get("occurred_at"),
            )

        @profile_router.post("/{profile_id}/session-snapshots")
        async def build_profile_session_snapshot(
            profile_id: str, body: dict[str, Any], request: Request
        ) -> Mapping[str, Any]:
            actor = _actor_from_request(request)
            _require_provenance(actor, {"operator"})
            overrides = body.get("overrides")
            if not isinstance(overrides, list):
                _raise_http(400, "overrides must be an array")
            return _call_profile(
                profile_registry.build_session_snapshot,
                profile_id,
                run_id=body.get("run_id"),
                overrides=overrides,
                created_at=body.get("created_at"),
                actor=actor,
                session_started=body.get("session_started") is True,
                fork_provenance=body.get("fork_provenance"),
            )

        app.include_router(profile_router)
    return app


def _bearer_token(authorization: str | None) -> str | None:
    if not isinstance(authorization, str):
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        return None
    if token != token.strip() or " " in token:
        return None
    return token


def _actor_from_request(request: Any) -> ActorContext:
    actor = getattr(request.state, "actor_context", None)
    if not isinstance(actor, ActorContext):
        _raise_http(401, "Unauthorized", authenticate=True)
    return actor


def _require_provenance(actor: ActorContext, allowed: set[str]) -> None:
    if actor.provenance_class not in allowed:
        _raise_http(403, "Forbidden")


def _require_http_capability(actor: ActorContext, capability: str) -> None:
    try:
        require_capability(actor, capability)
    except PermissionError as exc:
        _raise_http(403, "Forbidden", cause=exc)


def _validate_action_envelope(
    body: Mapping[str, Any],
    *,
    route_run_id: str,
    actor: ActorContext,
    allowed_capabilities: set[str] | frozenset[str],
) -> None:
    _reject_authority_claims(body)
    if body.get("run_id") != route_run_id:
        _raise_http(400, "route run_id does not match request run_id")
    capability = body.get("capability")
    if capability not in allowed_capabilities:
        _raise_http(403, "Forbidden")
    if body.get("capability_id") != actor.capability_id:
        _raise_http(403, "Forbidden")
    _require_http_capability(actor, str(capability))


def _reject_authority_claims(body: Mapping[str, Any]) -> None:
    claimed = _AUTHORITY_FIELDS.intersection(body)
    payload = body.get("payload")
    if isinstance(payload, Mapping):
        claimed = claimed.union(_AUTHORITY_FIELDS.intersection(payload))
    if claimed:
        _raise_http(400, "actor and provenance are assigned by authentication")


def _action_response(result: Any) -> dict[str, Any]:
    if not isinstance(result, ServiceActionResult):
        raise RuntimeError("canonical run service returned an invalid action result")
    return {
        "delivery": {"replayed": result.replayed},
        "receipt": dict(result.receipt),
    }


def _call_service(method: Any, **kwargs: Any) -> Any:
    try:
        return method(**kwargs)
    except RunNotFound as exc:
        _raise_http(404, "Not found", cause=exc)
    except ContextRefusal as exc:
        _raise_http(409, str(exc), cause=exc)
    except CanonicalRunServiceError as exc:
        _raise_http(400, str(exc), cause=exc)
    except PermissionError as exc:
        _raise_http(403, "Forbidden", cause=exc)
    except KeyError as exc:
        _raise_http(404, "Not found", cause=exc)
    except ValueError as exc:
        _raise_http(400, str(exc), cause=exc)


def _call_profile(method: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return method(*args, **kwargs)
    except ProfileRegistryError as exc:
        _raise_http(400, str(exc), cause=exc)


def _raise_http(
    status_code: int,
    detail: str,
    *,
    authenticate: bool = False,
    cause: BaseException | None = None,
) -> None:
    from fastapi import HTTPException

    headers = {"WWW-Authenticate": "Bearer"} if authenticate else None
    error = HTTPException(status_code=status_code, detail=detail, headers=headers)
    if cause is None:
        raise error
    raise error from cause


__all__ = [
    "CanonicalRunService",
    "PrivateOperatorRunConfig",
    "ServiceActionResult",
    "TrustedActorResolver",
    "TrustedOperatorValidatorResolver",
    "create_private_operator_run_app",
    "validate_private_operator_run_config",
]
