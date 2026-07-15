from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

from nepsis_cgn.contracts.canonical_json import (
    CANONICAL_JSON_VERSION,
    CanonicalJsonError,
    canonical_hash,
    canonical_json,
    canonical_json_policy_hash,
)
from nepsis_cgn.verification.markdown_reconstruct import (
    MarkdownReconstructionError,
    verify_markdown_reconstruction,
)
from nepsis_cgn.verification.semantic_recompute import (
    SemanticVerificationError,
    UnsupportedSemanticPath,
    verify_semantics,
)


INTEROP_BUNDLE_VERSION = "nepsis.interop_bundle@0.2.0"
GENESIS_PREV_EVENT_HASH = hashlib.sha256(b"nepsis.genesis@0.1.0").hexdigest()
AUTHENTICITY_STATUS = "unanchored_self_consistency"

_EVENT_FIELDS = {
    "actor",
    "created_at",
    "event_hash",
    "event_schema_version",
    "event_type",
    "payload_hash",
    "payload",
    "prev_event_hash",
    "provenance_class",
    "sequence",
    "session_id",
}
_EVENT_OPTIONAL_FIELDS = {"idempotency_key"}
_SUBJECT_FIELDS = {
    "artifact_root",
    "artifact_rows",
    "audit_events",
    "audit_range",
    "canonicalization",
    "contracts",
    "decision_projection",
    "frame_lineage_root",
    "guarantee_level",
    "markdown",
    "markdown_hash",
    "markdown_included",
    "particle_lineage_root",
    "phase_projection",
    "policies",
    "producer",
    "profile",
    "redacted_artifact_hashes",
    "redacted_sequences",
    "session_id",
    "verification_claims",
}

_EXPECTED_CONTRACTS = [
    {"contract_id": "foundation", "version": "nepsis.foundation_contract@0.1.0"},
    {
        "contract_id": "actualization",
        "version": "nepsis.actualization_contract@0.2.0",
    },
]
_EXPECTED_POLICIES = [
    {
        "policy_hash": "4bbeb8ed7c2a33e48a5354dd75b651440ce8eaaf532450a8b3d4cb18bee70997",
        "policy_id": "calibration_kernel",
        "version": "nepsis.calibration_policy@0.1.0",
    },
    {
        "policy_hash": "48aaf22a6317cb7f039551a0a142200a869409e2582556728f888be6c6d0972b",
        "policy_id": "event_policy",
        "version": "nepsis.event_policy@0.3.0",
    },
    {
        "policy_hash": "dd46d8f9e6ea488f813c43379637164cdd1f41be86ab1904eba19495762f6b0e",
        "policy_id": "governance_kernel",
        "version": "nepsis.governance_kernel@0.1.0",
    },
    {
        "policy_hash": "3cce5c427d8fbf759dc1ac79d0c178e7b5fe13171b314c79df85829372ff6fef",
        "policy_id": "inference_kernel",
        "version": "nepsis.inference_kernel@0.1.0",
    },
    {
        "policy_hash": "a987035abb4c3c2cb13253d5febbe12e100f678d2b4f6b561ba0bf099a3078dc",
        "policy_id": "patch_tiers",
        "version": "nepsis.patch_tiers@0.1.0",
    },
    {
        "policy_hash": "ae6fda837b16f5c27d631b6b5e63b71b03807a7ba89a27b21e2107531501b646",
        "policy_id": "phase_machine",
        "version": "nepsis.phase_machine@0.3.0",
    },
    {
        "policy_hash": "42f46729aa4dc10470819ea32a8089c7bf516680029321e7b094bb472c64ee04",
        "policy_id": "projection_preconditions",
        "version": "nepsis.projection_preconditions@0.5.0",
    },
]
_EXPECTED_CLAIMS = [
    "artifact_integrity",
    "audit_chain_integrity",
    "calibration_integrity",
    "decision_journey_reconstructable",
    "lineage_integrity",
    "markdown_integrity",
]
_PROJECTION_ARTIFACT_FIELDS = {
    "calibration_acceptance_hash",
    "current_population_hash",
    "frame_hash",
    "frame_lineage_hash",
    "governance_decision_hash",
    "particle_lineage_hash",
    "predictions_hash",
    "pretest_population_hash",
    "update_hash",
}
_PROJECTION_ARTIFACT_ARRAY_FIELDS = {
    "calibration_parent_population_hashes",
    "observation_hashes",
    "population_history",
    "stale_artifact_hashes",
}
_ARTIFACT_CONTRACTS: dict[str, tuple[str, frozenset[tuple[str, ...]]]] = {
    "nepsis.calibration_acceptance@0.1.0": (
        "calibration_acceptance_schema_version",
        frozenset({("acceptance",)}),
    ),
    "nepsis.calibration_proposal@0.1.0": (
        "calibration_proposal_schema_version",
        frozenset({("proposal",)}),
    ),
    "nepsis.calibration_research@0.1.0": (
        "calibration_research_schema_version",
        frozenset({("research",)}),
    ),
    "nepsis.frame@0.1.0": ("frame_schema_version", frozenset({("frame",)})),
    "nepsis.frame_lineage@0.1.0": (
        "frame_lineage_schema_version",
        frozenset({("frame_lineage",)}),
    ),
    "nepsis.governance_decision@0.1.0": (
        "governance_decision_schema_version",
        frozenset({("governance_decision",)}),
    ),
    "nepsis.observation@0.1.0": (
        "observation_schema_version",
        frozenset({("observation",)}),
    ),
    "nepsis.particle@0.1.0": (
        "particle_schema_version",
        frozenset({("particle_artifact",)}),
    ),
    "nepsis.particle_lineage@0.1.0": (
        "particle_lineage_schema_version",
        frozenset({("particle_lineage",)}),
    ),
    "nepsis.population_snapshot@0.1.0": (
        "population_snapshot_schema_version",
        frozenset({("population",), ("posterior_population", "result_population")}),
    ),
    "nepsis.population_update@0.1.0": (
        "population_update_schema_version",
        frozenset({("update",)}),
    ),
    "nepsis.pretest_predictions@0.1.0": (
        "pretest_predictions_schema_version",
        frozenset({("predictions",)}),
    ),
}


class InteropVerificationError(ValueError):
    pass


def verify_interop_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Verify the bounded neutral 0.2 bundle without either product runtime."""

    try:
        canonical_json(bundle)
    except CanonicalJsonError as exc:
        raise InteropVerificationError(f"bundle is not neutral canonical JSON: {exc}") from exc
    _closed(
        bundle,
        required={
            "export_attestation",
            "interop_bundle_version",
            "subject",
            "subject_hash",
        },
        label="interop_bundle",
    )
    if bundle.get("interop_bundle_version") != INTEROP_BUNDLE_VERSION:
        raise InteropVerificationError("unsupported interop bundle version")

    subject = _object(bundle.get("subject"), "subject")
    _closed(
        subject,
        required=_SUBJECT_FIELDS - {"markdown"},
        optional={"markdown"},
        label="subject",
    )
    subject_hash = _hash(bundle.get("subject_hash"), "subject_hash")
    if canonical_hash(subject) != subject_hash:
        raise InteropVerificationError("subject hash mismatch")
    if subject.get("profile") != "full":
        raise InteropVerificationError("independent V0 verifier accepts full bundles only")
    if subject.get("guarantee_level") != "full_reconstruction":
        raise InteropVerificationError("full reconstruction guarantee is required")
    if subject.get("redacted_sequences") != [] or subject.get(
        "redacted_artifact_hashes"
    ) != []:
        raise InteropVerificationError("full bundle cannot declare redactions")

    events = _event_array(subject.get("audit_events"), "audit_events")
    if not events:
        raise InteropVerificationError("audit_events must not be empty")
    _verify_chain(events)
    session_id = _text(subject.get("session_id"), "session_id")
    if any(event.get("session_id") != session_id for event in events):
        raise InteropVerificationError("audit session mismatch")
    _verify_audit_range(subject, events)

    attestation = _object(bundle.get("export_attestation"), "export_attestation")
    _verify_chain([*events, attestation])
    _verify_attestation(
        attestation=attestation,
        subject=subject,
        subject_hash=subject_hash,
        events=events,
    )

    artifact_by_hash = _verify_artifacts(subject)
    _verify_pinned_versions(subject)
    _verify_lineage_graphs(subject, events, artifact_by_hash)
    _verify_projection_bindings(subject, events, artifact_by_hash)
    _verify_governance_order(events, subject, artifact_by_hash)
    _verify_projection_reconstruction(subject, events)

    semantic_checks: list[str] = []
    semantic_gaps = [
        "blocked_or_discriminator_governance_path",
        "denominator_collapse_repair_path",
        "inference_rejuvenation_path",
        "inference_resampling_path",
        "model_calibration_proposal_quality",
    ]
    try:
        semantic_result = verify_semantics(events, artifact_by_hash, subject)
    except UnsupportedSemanticPath as exc:
        semantic_gaps.append(f"subject_semantic_path:{exc}")
    except SemanticVerificationError as exc:
        raise InteropVerificationError(str(exc)) from exc
    else:
        semantic_checks = list(semantic_result["verified_semantics"])

    # Rendering is an independent projection check. Run it after semantic
    # recomputation so a resealed artifact mutation receives the narrowest
    # truthful rejection instead of being masked by its stale Markdown view.
    _verify_markdown(subject)

    return {
        "valid": True,
        "adoption_eligible": False,
        "anchor_status": "unanchored",
        "authenticity": AUTHENTICITY_STATUS,
        "interop_bundle_version": INTEROP_BUNDLE_VERSION,
        "verification_scope": "bounded_structural_projection_lineage_semantic_and_governance_v0_2",
        "verified_checks": [
            "artifact_integrity",
            "audit_chain_integrity",
            "decision_projection_reconstruction",
            "export_attestation_binding",
            "lineage_graph_integrity",
            "markdown_projection_reconstruction",
            "phase_projection_reconstruction",
            "pinned_contract_and_policy_versions",
            "projection_artifact_references",
            "governance_event_order_and_hash_binding",
            *semantic_checks,
        ],
        "unverified_claims": semantic_gaps,
        "subject_hash": subject_hash,
        "audit_tip": events[-1]["event_hash"],
        "artifact_root": subject["artifact_root"],
        "artifact_count": len(artifact_by_hash),
    }


def _verify_chain(events: list[dict[str, Any]]) -> None:
    expected_prev = GENESIS_PREV_EVENT_HASH
    expected_session = ""
    for sequence, event in enumerate(events):
        _closed(
            event,
            required=_EVENT_FIELDS,
            optional=_EVENT_OPTIONAL_FIELDS,
            label=f"event[{sequence}]",
        )
        if isinstance(event.get("sequence"), bool) or event.get("sequence") != sequence:
            raise InteropVerificationError(f"event sequence mismatch at {sequence}")
        if event.get("event_schema_version") != "nepsis.audit_event@0.1.0":
            raise InteropVerificationError("unsupported audit event schema version")
        event_session = _text(event.get("session_id"), "event session_id")
        if sequence == 0:
            expected_session = event_session
        elif event_session != expected_session:
            raise InteropVerificationError("session_id changed inside audit chain")
        if event.get("prev_event_hash") != expected_prev:
            raise InteropVerificationError(f"prev_event_hash mismatch at {sequence}")
        payload = event.get("payload")
        if payload is not None and canonical_hash(payload) != event.get("payload_hash"):
            raise InteropVerificationError(f"payload_hash mismatch at {sequence}")
        envelope = {
            key: deepcopy(value)
            for key, value in event.items()
            if key not in {"payload", "event_hash"}
        }
        if canonical_hash(envelope) != event.get("event_hash"):
            raise InteropVerificationError(f"event_hash mismatch at {sequence}")
        expected_prev = _hash(event.get("event_hash"), "event_hash")


def _verify_audit_range(subject: dict[str, Any], events: list[dict[str, Any]]) -> None:
    audit_range = _object(subject.get("audit_range"), "audit_range")
    _closed(
        audit_range,
        required={"end_sequence", "start_sequence", "tip_event_hash"},
        label="audit_range",
    )
    if audit_range != {
        "start_sequence": 0,
        "end_sequence": events[-1]["sequence"],
        "tip_event_hash": events[-1]["event_hash"],
    }:
        raise InteropVerificationError("audit range mismatch")


def _verify_attestation(
    *,
    attestation: dict[str, Any],
    subject: dict[str, Any],
    subject_hash: str,
    events: list[dict[str, Any]],
) -> None:
    if attestation.get("event_type") != "export_created":
        raise InteropVerificationError("attestation event type mismatch")
    if attestation.get("actor") != f"validator:{INTEROP_BUNDLE_VERSION}":
        raise InteropVerificationError("attestation actor mismatch")
    if attestation.get("provenance_class") != "validator":
        raise InteropVerificationError("attestation provenance mismatch")
    payload = _object(attestation.get("payload"), "attestation payload")
    _closed(
        payload,
        required={
            "artifact_root",
            "intent_hash",
            "interop_bundle_version",
            "markdown_hash",
            "profile",
            "redact_artifact_hashes",
            "redact_sequences",
            "subject_audit_end_sequence",
            "subject_audit_tip",
            "subject_hash",
        },
        label="attestation payload",
    )
    expected = {
        "artifact_root": subject["artifact_root"],
        "interop_bundle_version": INTEROP_BUNDLE_VERSION,
        "markdown_hash": subject["markdown_hash"],
        "profile": "full",
        "redact_artifact_hashes": [],
        "redact_sequences": [],
        "subject_audit_end_sequence": events[-1]["sequence"],
        "subject_audit_tip": events[-1]["event_hash"],
        "subject_hash": subject_hash,
    }
    for field, value in expected.items():
        if payload.get(field) != value:
            raise InteropVerificationError(f"attestation {field} mismatch")
    _hash(payload.get("intent_hash"), "attestation intent_hash")


def _verify_artifacts(subject: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = subject.get("artifact_rows")
    if not isinstance(rows, list) or not rows:
        raise InteropVerificationError("artifact_rows must be a non-empty array")
    if any(not isinstance(row, dict) for row in rows):
        raise InteropVerificationError("artifact rows must be objects")
    if rows != sorted(rows, key=lambda row: row.get("artifact_hash", "")):
        raise InteropVerificationError("artifact_rows must be hash sorted")
    root_rows: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, Any]] = {}
    for index, row_value in enumerate(rows):
        row = _object(row_value, f"artifact row {index}")
        _closed(
            row,
            required={"artifact", "artifact_hash", "included", "roles", "schema_version"},
            label=f"artifact row {index}",
        )
        artifact_hash = _hash(row.get("artifact_hash"), "artifact_hash")
        if artifact_hash in artifacts:
            raise InteropVerificationError("duplicate artifact hash")
        if row.get("included") is not True:
            raise InteropVerificationError("full bundle must include every artifact")
        artifact = _object(row.get("artifact"), "artifact")
        if canonical_hash(artifact) != artifact_hash:
            raise InteropVerificationError("artifact hash mismatch")
        if artifact.get("session_id") != subject.get("session_id"):
            raise InteropVerificationError("artifact session mismatch")
        roles = row.get("roles")
        if (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or not role for role in roles)
        ):
            raise InteropVerificationError("artifact roles must be sorted unique strings")
        if roles != sorted(set(roles)):
            raise InteropVerificationError("artifact roles must be sorted unique strings")
        schema_version = _text(row.get("schema_version"), "artifact schema_version")
        contract = _ARTIFACT_CONTRACTS.get(schema_version)
        if contract is None:
            raise InteropVerificationError("unsupported artifact schema version")
        version_field, allowed_roles = contract
        if artifact.get(version_field) != schema_version:
            raise InteropVerificationError("artifact schema version mismatch")
        if tuple(roles) not in allowed_roles:
            raise InteropVerificationError("artifact role is invalid for its schema")
        artifacts[artifact_hash] = artifact
        root_rows.append(
            {
                "artifact_hash": artifact_hash,
                "roles": roles,
                "schema_version": schema_version,
            }
        )
    if canonical_hash({"artifact_rows": root_rows}) != subject.get("artifact_root"):
        raise InteropVerificationError("artifact root mismatch")
    return artifacts


def _verify_markdown(subject: dict[str, Any]) -> None:
    if subject.get("markdown_included") is not True:
        raise InteropVerificationError("full bundle must include markdown")
    markdown = subject.get("markdown")
    if not isinstance(markdown, str):
        raise InteropVerificationError("markdown body is required")
    actual = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    if actual != subject.get("markdown_hash"):
        raise InteropVerificationError("markdown hash mismatch")
    try:
        verify_markdown_reconstruction(subject)
    except MarkdownReconstructionError as exc:
        raise InteropVerificationError(str(exc)) from exc


def _verify_pinned_versions(subject: dict[str, Any]) -> None:
    if subject.get("canonicalization") != {
        "policy_hash": canonical_json_policy_hash(),
        "version": CANONICAL_JSON_VERSION,
    }:
        raise InteropVerificationError("canonicalization policy mismatch")
    if subject.get("contracts") != _EXPECTED_CONTRACTS:
        raise InteropVerificationError("contract manifest mismatch")
    if subject.get("policies") != _EXPECTED_POLICIES:
        raise InteropVerificationError("policy manifest mismatch")
    if subject.get("producer") != {
        "producer_id": "nepsismc",
        "producer_version": "0.1.0",
    }:
        raise InteropVerificationError("producer identity mismatch")
    if subject.get("verification_claims") != _EXPECTED_CLAIMS:
        raise InteropVerificationError("verification claims mismatch")


def _verify_lineage_graphs(
    subject: dict[str, Any],
    events: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    event_hashes = {str(event["event_hash"]) for event in events}
    projection = _object(subject.get("decision_projection"), "decision_projection")
    frame_lineage_hash = _hash(subject.get("frame_lineage_root"), "frame lineage root")
    particle_lineage_hash = _hash(
        subject.get("particle_lineage_root"), "particle lineage root"
    )
    try:
        frame_lineage = artifacts[frame_lineage_hash]
        particle_lineage = artifacts[particle_lineage_hash]
    except KeyError as exc:
        raise InteropVerificationError("lineage root references a missing artifact") from exc
    if frame_lineage.get("frame_lineage_schema_version") != (
        "nepsis.frame_lineage@0.1.0"
    ):
        raise InteropVerificationError("frame lineage root has the wrong artifact type")
    if particle_lineage.get("particle_lineage_schema_version") != (
        "nepsis.particle_lineage@0.1.0"
    ):
        raise InteropVerificationError("particle lineage root has the wrong artifact type")

    frame_nodes = _verify_lineage_graph(
        lineage=frame_lineage,
        artifacts=artifacts,
        event_hashes=event_hashes,
        node_id_field="frame_id",
        artifact_id_field="frame_id",
        expected_artifact_version="nepsis.frame@0.1.0",
        from_field="from_frame_id",
        to_field="to_frame_id",
        allowed_causal_kinds={
            "derived_from",
            "foreign_frame_challenge",
            "reframes",
            "supersedes",
        },
        allowed_evaluative_kinds=set(),
        allowed_states={"active", "challenger", "stale", "superseded"},
        label="frame lineage",
    )
    active_frames = [
        node for node in frame_nodes.values() if node.get("state") == "active"
    ]
    if len(active_frames) != 1 or active_frames[0].get("artifact_hash") != projection.get(
        "frame_hash"
    ):
        raise InteropVerificationError(
            "frame lineage active node does not match the decision projection"
        )

    particle_nodes = _verify_lineage_graph(
        lineage=particle_lineage,
        artifacts=artifacts,
        event_hashes=event_hashes,
        node_id_field="particle_id",
        artifact_id_field="particle_id",
        expected_artifact_version="nepsis.particle@0.1.0",
        from_field="from_particle_id",
        to_field="to_particle_id",
        allowed_causal_kinds={
            "propagated_from",
            "resampled_from",
            "rejuvenated_from",
            "updated_from",
            "supersedes",
        },
        allowed_evaluative_kinds={"supports", "contradicts", "tests"},
        allowed_states={"active", "quarantined", "stale", "superseded"},
        label="particle lineage",
    )
    population_hash = projection.get("current_population_hash")
    if population_hash:
        population = artifacts.get(population_hash)
        if population is None or population.get("population_snapshot_schema_version") != (
            "nepsis.population_snapshot@0.1.0"
        ):
            raise InteropVerificationError(
                "current population is missing or has the wrong artifact type"
            )
        active_particle_refs = sorted(
            (str(node["particle_id"]), str(node["artifact_hash"]))
            for node in particle_nodes.values()
            if node.get("state") == "active"
        )
        population_refs = sorted(
            (str(row.get("particle_id")), str(row.get("artifact_hash")))
            for row in population.get("particle_refs", [])
            if isinstance(row, dict)
        )
        if active_particle_refs != population_refs:
            raise InteropVerificationError(
                "active particle lineage does not match the current population"
            )


def _verify_lineage_graph(
    *,
    lineage: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
    event_hashes: set[str],
    node_id_field: str,
    artifact_id_field: str,
    expected_artifact_version: str,
    from_field: str,
    to_field: str,
    allowed_causal_kinds: set[str],
    allowed_evaluative_kinds: set[str],
    allowed_states: set[str],
    label: str,
) -> dict[str, dict[str, Any]]:
    source_hashes = lineage.get("source_event_hashes")
    if (
        not isinstance(source_hashes, list)
        or source_hashes != sorted(set(source_hashes))
        or any(value not in event_hashes for value in source_hashes)
    ):
        raise InteropVerificationError(f"{label} source events are invalid")
    nodes_value = lineage.get("nodes")
    if not isinstance(nodes_value, list) or not nodes_value:
        raise InteropVerificationError(f"{label} nodes must be non-empty")
    if any(not isinstance(node, dict) for node in nodes_value):
        raise InteropVerificationError(f"{label} nodes must be objects")
    node_ids = [node.get(node_id_field) for node in nodes_value]
    if node_ids != sorted(node_ids) or len(node_ids) != len(set(node_ids)):
        raise InteropVerificationError(f"{label} nodes must be sorted and unique")
    node_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes_value:
        _closed(
            node,
            required={node_id_field, "artifact_hash", "source_event_hash", "state"},
            label=f"{label} node",
        )
        node_id = _text(node.get(node_id_field), f"{label} node id")
        artifact_hash = _hash(node.get("artifact_hash"), f"{label} node artifact")
        if node.get("source_event_hash") not in event_hashes:
            raise InteropVerificationError(f"{label} node source event is unavailable")
        if node.get("state") not in allowed_states:
            raise InteropVerificationError(f"{label} node state is unsupported")
        referenced = artifacts.get(artifact_hash)
        version_fields = [
            value
            for key, value in (referenced or {}).items()
            if key.endswith("_schema_version")
        ]
        if referenced is None or version_fields != [expected_artifact_version]:
            raise InteropVerificationError(f"{label} node has the wrong artifact type")
        if referenced.get(artifact_id_field) != node_id:
            raise InteropVerificationError(f"{label} node identity does not match artifact")
        if referenced.get("session_id") != lineage.get("session_id"):
            raise InteropVerificationError(f"{label} node belongs to another session")
        node_by_id[node_id] = node

    edges_value = lineage.get("edges")
    if not isinstance(edges_value, list) or any(
        not isinstance(edge, dict) for edge in edges_value
    ):
        raise InteropVerificationError(f"{label} edges must be objects")
    edge_ids = [edge.get("edge_id") for edge in edges_value]
    if edge_ids != sorted(edge_ids) or len(edge_ids) != len(set(edge_ids)):
        raise InteropVerificationError(f"{label} edges must be sorted and unique")
    causal_edges: list[dict[str, Any]] = []
    resample_slots: dict[str, list[int]] = {}
    for edge in edges_value:
        kind = edge.get("edge_kind")
        optional = {"resample_slot"} if kind == "resampled_from" else set()
        _closed(
            edge,
            required={"cause_event_hash", "edge_id", "edge_kind", from_field, to_field},
            optional=optional,
            label=f"{label} edge",
        )
        source = _text(edge.get(from_field), f"{label} edge source")
        target = _text(edge.get(to_field), f"{label} edge target")
        if source == target or source not in node_by_id or target not in node_by_id:
            raise InteropVerificationError(f"{label} edge is dangling or self-referential")
        if edge.get("cause_event_hash") not in event_hashes:
            raise InteropVerificationError(f"{label} edge cause event is unavailable")
        if kind not in allowed_causal_kinds | allowed_evaluative_kinds:
            raise InteropVerificationError(f"{label} edge kind is unsupported")
        if kind in allowed_causal_kinds:
            causal_edges.append(edge)
        if kind == "resampled_from":
            slot = edge.get("resample_slot")
            if isinstance(slot, bool) or not isinstance(slot, int) or slot < 0:
                raise InteropVerificationError("resampling slot must be non-negative")
            resample_slots.setdefault(str(edge["cause_event_hash"]), []).append(slot)
    for slots in resample_slots.values():
        if sorted(slots) != list(range(len(slots))):
            raise InteropVerificationError(
                "resampling slots must be unique and contiguous from zero"
            )
    _verify_acyclic_lineage(
        node_ids=[str(value) for value in node_ids],
        edges=causal_edges,
        from_field=from_field,
        to_field=to_field,
        roots=lineage.get("roots"),
        label=label,
    )
    return node_by_id


def _verify_acyclic_lineage(
    *,
    node_ids: list[str],
    edges: list[dict[str, Any]],
    from_field: str,
    to_field: str,
    roots: Any,
    label: str,
) -> None:
    incoming = {node_id: 0 for node_id in node_ids}
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    for edge in edges:
        source = str(edge[from_field])
        target = str(edge[to_field])
        adjacency[source].append(target)
        incoming[target] += 1
    expected_roots = sorted(
        node_id for node_id, incoming_count in incoming.items() if incoming_count == 0
    )
    if roots != expected_roots:
        raise InteropVerificationError(f"{label} roots do not match graph indegree")
    queue = list(expected_roots)
    visited = 0
    while queue:
        node_id = queue.pop(0)
        visited += 1
        for target in sorted(adjacency[node_id]):
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
    if visited != len(node_ids):
        raise InteropVerificationError(f"{label} causal graph is cyclic")


def _verify_projection_reconstruction(
    subject: dict[str, Any], events: list[dict[str, Any]]
) -> None:
    reconstructed_decision = _reconstruct_decision_projection(events)
    if subject.get("decision_projection") != reconstructed_decision:
        raise InteropVerificationError(
            "decision projection does not reconstruct from audit events"
        )
    reconstructed_phase = _reconstruct_phase_projection(events)
    if subject.get("phase_projection") != reconstructed_phase:
        raise InteropVerificationError(
            "phase projection does not reconstruct from audit events"
        )


def _reconstruct_decision_projection(events: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "actualization_contract_version": "nepsis.actualization_contract@0.2.0",
        "initialized": False,
        "decision_id": "",
        "seed": "",
        "minimum_absolute_fit_ppm": 0,
        "resample_ess_threshold_ppm": 0,
        "credible_mass_ppm": 0,
        "frame_hash": "",
        "frame_lineage_hash": "",
        "particle_lineage_hash": "",
        "pretest_population_hash": "",
        "current_population_hash": "",
        "calibration_cycle_id": "",
        "calibration_generation": 0,
        "calibration_parent_population_hashes": [],
        "calibration_acceptance_hash": "",
        "predictions_hash": "",
        "observation_hashes": [],
        "population_history": [],
        "update_hash": "",
        "governance_decision_hash": "",
        "governance_status": "not_evaluated",
        "unresolved_contradictions": [],
        "proposed_action_id": "",
        "next_discriminator_id": "",
        "committed_action_id": "",
        "status": "not_initialized",
        "zeroback_count": 0,
        "stale_artifact_hashes": [],
        "last_sequence": -1,
    }
    for event in events:
        sequence = event.get("sequence")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            state["last_sequence"] = max(state["last_sequence"], sequence)
        event_type = event.get("event_type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "actualization_initialized":
            state["initialized"] = True
            for field in (
                "decision_id",
                "seed",
                "calibration_cycle_id",
                "frame_hash",
                "frame_lineage_hash",
                "particle_lineage_hash",
            ):
                state[field] = _projection_text(payload.get(field))
            for field in (
                "minimum_absolute_fit_ppm",
                "resample_ess_threshold_ppm",
                "credible_mass_ppm",
                "calibration_generation",
            ):
                state[field] = _projection_integer(payload.get(field))
            state["calibration_parent_population_hashes"] = _projection_list(
                payload.get("calibration_parent_population_hashes")
            )
            state["status"] = "calibration_pending"
        elif event_type == "calibration_committed":
            population_hash = _projection_text(payload.get("population_hash"))
            state["calibration_acceptance_hash"] = _projection_text(
                payload.get("acceptance_hash")
            )
            state["pretest_population_hash"] = population_hash
            state["current_population_hash"] = population_hash
            state["predictions_hash"] = _projection_text(payload.get("predictions_hash"))
            _projection_append_unique(state["population_history"], population_hash)
            state["status"] = "pretest_frozen"
        elif event_type == "pretest_predictions_frozen":
            state["predictions_hash"] = _projection_text(payload.get("predictions_hash"))
            state["pretest_population_hash"] = _projection_text(
                payload.get("population_hash")
            )
            state["status"] = "pretest_frozen"
        elif event_type == "observation_recorded":
            _projection_append_unique(
                state["observation_hashes"],
                _projection_text(payload.get("observation_hash")),
            )
            state["status"] = "observation_recorded"
        elif event_type == "population_updated":
            state["update_hash"] = _projection_text(payload.get("update_hash"))
            state["current_population_hash"] = _projection_text(
                payload.get("result_population_hash")
            )
            state["particle_lineage_hash"] = (
                _projection_text(payload.get("particle_lineage_hash"))
                or state["particle_lineage_hash"]
            )
            for field in ("posterior_population_hash", "result_population_hash"):
                _projection_append_unique(
                    state["population_history"], _projection_text(payload.get(field))
                )
            state["status"] = (
                _projection_text(payload.get("denominator_status"))
                or "population_updated"
            )
        elif event_type == "particles_resampled":
            state["current_population_hash"] = _projection_text(
                payload.get("population_hash")
            )
            state["particle_lineage_hash"] = _projection_text(
                payload.get("particle_lineage_hash")
            )
            _projection_append_unique(
                state["population_history"], state["current_population_hash"]
            )
            state["status"] = "particles_resampled"
        elif event_type == "red_governance_evaluated":
            state["governance_decision_hash"] = _projection_text(
                payload.get("governance_decision_hash")
            )
            state["governance_status"] = _projection_text(payload.get("status"))
            state["unresolved_contradictions"] = _projection_sorted_texts(
                payload.get("unresolved_contradictions")
            )
            state["status"] = "red_evaluated"
        elif event_type == "blue_governance_evaluated":
            state["governance_decision_hash"] = _projection_text(
                payload.get("governance_decision_hash")
            )
            state["proposed_action_id"] = _projection_text(
                payload.get("proposed_action_id")
            )
            state["status"] = "blue_evaluated"
        elif event_type == "governance_decision_created":
            state["governance_decision_hash"] = _projection_text(
                payload.get("governance_decision_hash")
            )
            state["governance_status"] = _projection_text(payload.get("status"))
            state["proposed_action_id"] = _projection_text(
                payload.get("proposed_action_id")
            )
            state["next_discriminator_id"] = _projection_text(
                payload.get("next_discriminator_id")
            )
            state["status"] = (
                "decision_ready"
                if state["governance_status"] == "ready"
                else "blocked"
            )
        elif event_type == "decision_committed":
            state["committed_action_id"] = _projection_text(payload.get("action_id"))
            state["status"] = "committed"
        elif event_type == "zeroback_performed":
            state["zeroback_count"] += 1
            state["seed"] = _projection_text(payload.get("seed")) or state["seed"]
            state["calibration_cycle_id"] = _projection_text(
                payload.get("calibration_cycle_id")
            )
            state["calibration_generation"] = _projection_integer(
                payload.get("calibration_generation")
            )
            state["calibration_parent_population_hashes"] = _projection_list(
                payload.get("calibration_parent_population_hashes")
            )
            state["calibration_acceptance_hash"] = ""
            state["frame_hash"] = _projection_text(payload.get("new_frame_hash"))
            state["frame_lineage_hash"] = _projection_text(
                payload.get("frame_lineage_hash")
            )
            state["particle_lineage_hash"] = _projection_text(
                payload.get("particle_lineage_hash")
            )
            state["pretest_population_hash"] = ""
            state["current_population_hash"] = ""
            for artifact_hash in _projection_list(payload.get("stale_artifact_hashes")):
                _projection_append_unique(
                    state["stale_artifact_hashes"], _projection_text(artifact_hash)
                )
            for field in (
                "predictions_hash",
                "update_hash",
                "governance_decision_hash",
                "proposed_action_id",
                "next_discriminator_id",
                "committed_action_id",
            ):
                state[field] = ""
            state["governance_status"] = "not_evaluated"
            manifest = payload.get("carry_forward_manifest")
            if isinstance(manifest, dict):
                state["unresolved_contradictions"] = _projection_sorted_texts(
                    manifest.get("unresolved_contradictions")
                )
            state["status"] = "calibration_pending"
    return state


def _reconstruct_phase_projection(events: list[dict[str, Any]]) -> dict[str, Any]:
    projected_phase = "intake"
    active_hold = False
    hold: dict[str, Any] = {"state": "clear"}
    gates: dict[str, dict[str, Any]] = {}
    locked_gates: set[str] = set()
    unlocked_gates: dict[str, str] = {}
    last_sequence = -1
    for event in events:
        event_type = event.get("event_type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        sequence = event.get("sequence")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            last_sequence = max(last_sequence, sequence)
        if event_type in {"phase_advanced", "phase_reverted"}:
            for field in ("to_phase", "projected_phase", "phase_id", "phase"):
                value = _projection_text(payload.get(field))
                if value:
                    projected_phase = value
                    break
        elif event_type == "hold_placed":
            active_hold = True
            hold = _phase_hold(event, payload, state="active")
        elif event_type == "hold_released":
            active_hold = False
            released = _phase_hold(event, payload, state="released")
            if not released.get("hold_id") and hold.get("hold_id"):
                released["hold_id"] = hold["hold_id"]
            hold = released
        elif event_type == "gate_locked":
            gate_id = _projection_text(payload.get("gate_id"))
            if gate_id:
                locked_gates.add(gate_id)
                unlocked_gates.pop(gate_id, None)
                gates[gate_id] = _phase_gate(event, payload, gate_id, "locked")
        elif event_type == "gate_unlocked":
            gate_id = _projection_text(payload.get("gate_id"))
            if gate_id:
                locked_gates.discard(gate_id)
                prior_boundary = _projection_text(
                    gates.get(gate_id, {}).get("boundary_phase")
                )
                gates[gate_id] = _phase_gate(
                    event, payload, gate_id, "unlocked", prior_boundary
                )
                event_hash = _projection_text(event.get("event_hash"))
                if event_hash:
                    unlocked_gates[gate_id] = event_hash
    return {
        "phase_machine_version": "nepsis.phase_machine@0.3.0",
        "projected_phase": projected_phase,
        "active_hold": active_hold,
        "hold": hold,
        "gates": list(gates.values()),
        "locked_gates": sorted(locked_gates),
        "unlocked_gates": unlocked_gates,
        "last_sequence": last_sequence,
    }


def _phase_hold(
    event: dict[str, Any], payload: dict[str, Any], *, state: str
) -> dict[str, Any]:
    projected: dict[str, Any] = {
        "state": state,
        "sequence": event.get("sequence")
        if isinstance(event.get("sequence"), int)
        else -1,
    }
    for field in ("governance_decision_hash", "hold_id", "rationale", "reason"):
        value = _projection_text(payload.get(field))
        if value:
            projected[field] = value
    event_hash = _projection_text(event.get("event_hash"))
    if event_hash:
        projected["event_hash"] = event_hash
    return projected


def _phase_gate(
    event: dict[str, Any],
    payload: dict[str, Any],
    gate_id: str,
    state: str,
    boundary_phase: str = "",
) -> dict[str, Any]:
    projected: dict[str, Any] = {
        "gate_id": gate_id,
        "state": state,
        "sequence": event.get("sequence")
        if isinstance(event.get("sequence"), int)
        else -1,
        "rationale": _projection_text(payload.get("rationale"))
        or _projection_text(payload.get("reason")),
    }
    resolved_boundary = boundary_phase or _projection_text(
        payload.get("boundary_phase")
    )
    if resolved_boundary:
        projected["boundary_phase"] = resolved_boundary
    event_hash = _projection_text(event.get("event_hash"))
    if event_hash:
        projected["event_hash"] = event_hash
    return projected


def _projection_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _projection_integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _projection_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _projection_sorted_texts(value: Any) -> list[str]:
    return sorted(
        {item for item in _projection_list(value) if isinstance(item, str) and item}
    )


def _projection_append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _verify_projection_bindings(
    subject: dict[str, Any],
    events: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    projection = _object(subject.get("decision_projection"), "decision_projection")
    if projection.get("last_sequence") != events[-1]["sequence"]:
        raise InteropVerificationError("decision projection sequence mismatch")
    if projection.get("frame_lineage_hash") != subject.get("frame_lineage_root"):
        raise InteropVerificationError("frame lineage root mismatch")
    if projection.get("particle_lineage_hash") != subject.get("particle_lineage_root"):
        raise InteropVerificationError("particle lineage root mismatch")
    for field in _PROJECTION_ARTIFACT_FIELDS:
        value = projection.get(field)
        if value and value not in artifacts:
            raise InteropVerificationError(f"projection references missing {field}")
    for field in _PROJECTION_ARTIFACT_ARRAY_FIELDS:
        values = projection.get(field)
        if not isinstance(values, list):
            raise InteropVerificationError(f"projection {field} must be an array")
        if any(value not in artifacts for value in values):
            raise InteropVerificationError(f"projection references missing {field}")

    phase = _object(subject.get("phase_projection"), "phase_projection")
    if phase.get("last_sequence") != events[-1]["sequence"]:
        raise InteropVerificationError("phase projection sequence mismatch")


def _verify_governance_order(
    events: list[dict[str, Any]],
    subject: dict[str, Any],
    artifacts: dict[str, dict[str, Any]],
) -> None:
    required_order = [
        "red_governance_evaluated",
        "blue_governance_evaluated",
        "governance_decision_created",
        "hold_placed",
        "hold_released",
        "decision_committed",
    ]
    by_type: dict[str, dict[str, Any]] = {}
    for event_type in required_order:
        matches = [event for event in events if event.get("event_type") == event_type]
        if len(matches) != 1:
            raise InteropVerificationError(
                f"governed commitment requires exactly one {event_type} event"
            )
        by_type[event_type] = matches[0]
    sequences = [by_type[event_type]["sequence"] for event_type in required_order]
    if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
        raise InteropVerificationError("RED/BLUE/STILL/commit ordering mismatch")

    red = by_type["red_governance_evaluated"]
    blue = by_type["blue_governance_evaluated"]
    decision = by_type["governance_decision_created"]
    hold_placed = by_type["hold_placed"]
    hold_released = by_type["hold_released"]
    committed = by_type["decision_committed"]
    governance_hash = _object(red.get("payload"), "RED payload").get(
        "governance_decision_hash"
    )
    if governance_hash not in artifacts:
        raise InteropVerificationError("governance artifact is missing")
    for label, event in (
        ("BLUE", blue),
        ("decision", decision),
        ("hold", hold_placed),
        ("commit", committed),
    ):
        if _object(event.get("payload"), f"{label} payload").get(
            "governance_decision_hash"
        ) != governance_hash:
            raise InteropVerificationError(f"{label} governance binding mismatch")
    if _object(blue["payload"], "BLUE payload").get("red_cause_event_hash") != red.get(
        "event_hash"
    ):
        raise InteropVerificationError("BLUE is not causally bound to RED")
    if _object(decision["payload"], "decision payload").get(
        "red_cause_event_hash"
    ) != red.get("event_hash"):
        raise InteropVerificationError("decision is not causally bound to RED")
    red_payload = _object(red["payload"], "RED payload")
    decision_payload = _object(decision["payload"], "decision payload")
    if red_payload.get("status") != "ready":
        raise InteropVerificationError("RED evaluation is not ready")
    if red_payload.get("unresolved_contradictions") != []:
        raise InteropVerificationError("RED has unresolved contradictions")
    placed_payload = _object(hold_placed["payload"], "hold placed payload")
    released_payload = _object(hold_released["payload"], "hold released payload")
    commit_payload = _object(committed["payload"], "commit payload")
    if released_payload.get("hold_id") != placed_payload.get("hold_id"):
        raise InteropVerificationError("STILL hold release mismatch")
    if commit_payload.get("hold_release_event_hash") != hold_released.get("event_hash"):
        raise InteropVerificationError("commit does not cite the STILL release")
    if hold_released.get("provenance_class") != "operator" or not str(
        hold_released.get("actor", "")
    ).startswith("operator:"):
        raise InteropVerificationError("STILL release lacks operator provenance")
    if committed["sequence"] != hold_released["sequence"] + 1:
        raise InteropVerificationError("commit must immediately follow STILL release")
    if commit_payload.get("rationale") != released_payload.get("rationale"):
        raise InteropVerificationError("commit rationale does not match STILL release")

    projection = _object(subject["decision_projection"], "decision projection")
    governance = artifacts[governance_hash]
    if projection.get("governance_decision_hash") != governance_hash:
        raise InteropVerificationError("projection governance hash mismatch")
    if projection.get("committed_action_id") != commit_payload.get("action_id"):
        raise InteropVerificationError("committed action projection mismatch")
    if governance.get("proposed_action_id") != commit_payload.get("action_id"):
        raise InteropVerificationError("commit action does not match governance proposal")
    admissible = sorted(
        row.get("action_id")
        for row in governance.get("red_action_rows", [])
        if isinstance(row, dict) and row.get("admissible") is True
    )
    if red_payload.get("admissible_action_ids") != admissible:
        raise InteropVerificationError("RED admissible actions mismatch governance artifact")
    if decision_payload.get("status") != governance.get("status"):
        raise InteropVerificationError("decision status mismatch governance artifact")
    if decision_payload.get("unresolved_contradictions") != governance.get(
        "unresolved_contradictions"
    ):
        raise InteropVerificationError("decision contradictions mismatch governance artifact")
    if projection.get("status") != "committed":
        raise InteropVerificationError("decision projection is not committed")
    if projection.get("governance_status") != governance.get("status"):
        raise InteropVerificationError("projection governance status mismatch")
    phase = _object(subject["phase_projection"], "phase projection")
    if phase.get("active_hold") is not False:
        raise InteropVerificationError("phase projection retains an active hold")


def _event_array(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise InteropVerificationError(f"{label} must be an object array")
    return value


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InteropVerificationError(f"{label} must be an object")
    return value


def _closed(
    value: dict[str, Any],
    *,
    required: set[str],
    label: str,
    optional: set[str] | None = None,
) -> None:
    fields = set(value)
    missing = required - fields
    unknown = fields - required - (optional or set())
    if missing:
        raise InteropVerificationError(
            f"{label} missing fields: {', '.join(sorted(missing))}"
        )
    if unknown:
        raise InteropVerificationError(
            f"{label} has unknown fields: {', '.join(sorted(unknown))}"
        )


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise InteropVerificationError(f"{label} must be a non-empty string")
    return value


def _hash(value: Any, label: str) -> str:
    text = _text(value, label)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise InteropVerificationError(f"{label} must be a lowercase SHA-256 hash")
    return text


__all__ = [
    "AUTHENTICITY_STATUS",
    "INTEROP_BUNDLE_VERSION",
    "InteropVerificationError",
    "verify_interop_bundle",
]
