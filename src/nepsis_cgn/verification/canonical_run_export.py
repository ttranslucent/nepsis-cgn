from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from nepsis_cgn.contracts.canonical_json import (
    CanonicalJsonError,
    canonical_hash,
    canonical_json,
)
from nepsis_cgn.contracts.canonical_run import (
    CANONICAL_RUN_GENESIS_HASH,
    CanonicalRunContractError,
    verify_event_chain,
)
from nepsis_cgn.verification.receipts import (
    ActionReceiptError,
    public_key_from_trust_anchor,
    verify_action_receipt,
)
from nepsis_cgn.verification.operator_proposal_lifecycle import (
    OperatorProposalLifecycleVerificationError,
    verify_operator_proposal_lifecycle,
)
from nepsis_cgn.verification.canonical_actualization import (
    CanonicalActualizationVerificationError,
    verify_canonical_actualization,
)


PROTECTED_EXPORT_VERSION = "nepsis.canonical_run_protected_export@0.1.0"
STORE_EXPORT_VERSION = "nepsis.canonical_run_store_export@0.1.0"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_PROTECTED_FIELDS = {
    "action_receipts",
    "artifacts",
    "effective_policy_hash",
    "events",
    "export_root_hash",
    "export_schema_version",
    "outcomes",
    "packet_projection",
    "postcondition",
    "protected_export_schema_version",
    "receipt_trust_anchor",
    "run",
}
_RUN_FIELDS = {
    "canonical_run_schema_version",
    "created_at",
    "head_event_hash",
    "head_sequence",
    "operator_governance_profile_hash",
    "owner_id",
    "packet_projection_hash",
    "run_id",
    "session_governance_snapshot_hash",
    "status",
    "system_policy_bindings",
}
_FORK_PROVENANCE_FIELDS = {
    "fork_reason",
    "forked_from_run_id",
    "inherited_evidence_root_hashes",
    "parent_head_event_hash",
    "policy_diff_artifact_hash",
}
_RUN_CREATED_PAYLOAD_FIELDS = {
    "effective_policy_hash",
    "initial_packet_projection",
    "initial_postcondition",
    "operator_governance_profile_hash",
    "owner_id",
    "session_governance_snapshot_hash",
    "system_policy_bindings",
}
_RUN_FORKED_PAYLOAD_FIELDS = {
    "fork_provenance",
    "packet_projection",
    "postcondition",
    "resulting_status",
    "successor_run_id",
}
_GOVERNANCE_POLICY_DIFF_VERSION = "nepsis.governance_policy_diff@0.1.0"
_ACTION_RECEIPT_CAPABILITIES = {
    "create_run",
    "fork_run",
    "perform_zeroback",
    "release_still",
    "request_decision_commit",
    "submit_model_candidate",
    "submit_operator_disposition",
}
_ARTIFACT_FIELDS = {
    "artifact",
    "artifact_hash",
    "artifact_schema_version",
    "canonical_run_artifact_schema_version",
    "created_sequence",
    "roles",
    "run_id",
}
_RECEIPT_METADATA_FIELDS = {
    "action_receipt_schema_version",
    "receipt_id",
    "signature",
    "signed_at",
    "validator_policy_hash",
    "validator_policy_version",
    "verification_level",
}


class CanonicalRunExportVerificationError(ValueError):
    pass


def verify_protected_canonical_run_export(
    export: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify a signed protected export without the writer/store implementation."""

    value = _mapping(export, "protected export")
    try:
        canonical_json(value)
    except CanonicalJsonError as exc:
        raise CanonicalRunExportVerificationError(
            f"protected export is not neutral canonical JSON: {exc}"
        ) from exc
    _closed(value, _PROTECTED_FIELDS, "protected export")
    if value["protected_export_schema_version"] != PROTECTED_EXPORT_VERSION:
        raise CanonicalRunExportVerificationError(
            "protected export schema version mismatch"
        )
    if value["export_schema_version"] != STORE_EXPORT_VERSION:
        raise CanonicalRunExportVerificationError("store export version mismatch")
    root = _hash(value["export_root_hash"], "export_root_hash")
    unsigned_export = {
        key: deepcopy(item)
        for key, item in value.items()
        if key != "export_root_hash"
    }
    if canonical_hash(unsigned_export) != root:
        raise CanonicalRunExportVerificationError("export root hash mismatch")

    run = _mapping(value["run"], "run")
    _closed_optional(run, _RUN_FIELDS, {"fork_provenance"}, "run")
    if run["canonical_run_schema_version"] != "nepsis.canonical_run@0.1.0":
        raise CanonicalRunExportVerificationError("canonical run version mismatch")
    run_id = _text(run["run_id"], "run_id")
    effective_policy_hash = _hash(
        value["effective_policy_hash"], "effective_policy_hash"
    )
    profile_hash = _hash(
        run["operator_governance_profile_hash"],
        "operator_governance_profile_hash",
    )
    snapshot_hash = _hash(
        run["session_governance_snapshot_hash"],
        "session_governance_snapshot_hash",
    )
    fork_provenance = (
        _normalize_fork_provenance(run["fork_provenance"], "run fork provenance")
        if "fork_provenance" in run
        else None
    )

    events = _array(value["events"], "events")
    if not events or any(not isinstance(event, dict) for event in events):
        raise CanonicalRunExportVerificationError("events must be a non-empty object array")
    try:
        verify_event_chain(events)
    except CanonicalRunContractError as exc:
        raise CanonicalRunExportVerificationError(str(exc)) from exc
    _verify_event_bindings(
        events,
        run_id=run_id,
        fork_provenance=fork_provenance,
    )
    last_event = events[-1]
    if run["head_sequence"] != last_event["sequence"]:
        raise CanonicalRunExportVerificationError("run head sequence mismatch")
    if run["head_event_hash"] != last_event["event_hash"]:
        raise CanonicalRunExportVerificationError("run head event hash mismatch")

    artifacts = _verify_artifacts(
        value["artifacts"],
        run_id=run_id,
        head_sequence=int(run["head_sequence"]),
    )
    for event in events:
        for artifact_hash in _hash_array(
            event.get("caused_by_artifact_hashes"),
            "caused_by_artifact_hashes",
        ):
            if artifact_hash not in artifacts:
                raise CanonicalRunExportVerificationError(
                    "event references unavailable artifact"
                )

    packet_projection = _mapping(value["packet_projection"], "packet_projection")
    packet_hash = canonical_hash(packet_projection)
    if packet_hash != _hash(run["packet_projection_hash"], "packet_projection_hash"):
        raise CanonicalRunExportVerificationError("packet projection hash mismatch")
    postcondition = _mapping(value["postcondition"], "postcondition")
    if set(postcondition) != {
        "active_hold",
        "governance_status",
        "packet_projection_hash",
        "phase",
    }:
        raise CanonicalRunExportVerificationError("postcondition fields mismatch")
    if postcondition["packet_projection_hash"] != packet_hash:
        raise CanonicalRunExportVerificationError(
            "postcondition packet projection hash mismatch"
        )
    has_external_fork_predecessor = _verify_run_replay(
        run=run,
        events=events,
        artifacts=artifacts,
        effective_policy_hash=effective_policy_hash,
        fork_provenance=fork_provenance,
        packet_projection=packet_projection,
        postcondition=postcondition,
    )

    outcomes = _array(value["outcomes"], "outcomes")
    receipts = _array(value["action_receipts"], "action_receipts")
    if len(outcomes) != len(receipts) or not outcomes:
        raise CanonicalRunExportVerificationError(
            "every persisted outcome requires exactly one receipt"
        )
    anchor = _mapping(value["receipt_trust_anchor"], "receipt_trust_anchor")
    try:
        public_key = public_key_from_trust_anchor(anchor)
    except ActionReceiptError as exc:
        raise CanonicalRunExportVerificationError(str(exc)) from exc
    seen_outcomes: set[str] = set()
    advanced_event_hashes: list[str] = []
    for outcome, receipt in zip(outcomes, receipts, strict=True):
        outcome_value = _mapping(outcome, "outcome")
        receipt_value = _mapping(receipt, "action receipt")
        advanced_event_hash = _verify_outcome_receipt_pair(
            outcome_value,
            receipt_value,
            run_id=run_id,
            effective_policy_hash=effective_policy_hash,
            profile_hash=profile_hash,
            snapshot_hash=snapshot_hash,
            public_key=public_key,
            anchor=anchor,
            events=events,
            artifacts=artifacts,
        )
        if advanced_event_hash is not None:
            advanced_event_hashes.append(advanced_event_hash)
        outcome_id = _hash(outcome_value.get("outcome_id"), "outcome_id")
        if outcome_id in seen_outcomes:
            raise CanonicalRunExportVerificationError("duplicate outcome identity")
        seen_outcomes.add(outcome_id)
    if len(set(advanced_event_hashes)) != len(advanced_event_hashes):
        raise CanonicalRunExportVerificationError(
            "a canonical event has more than one advancing receipt"
        )
    if advanced_event_hashes != [str(event["event_hash"]) for event in events]:
        raise CanonicalRunExportVerificationError(
            "every canonical event requires exactly one advancing receipt"
        )

    try:
        proposal_lifecycle = verify_operator_proposal_lifecycle(
            events=events,
            artifacts=artifacts,
            final_packet_projection=packet_projection,
            system_policy_bindings=run["system_policy_bindings"],
        )
    except OperatorProposalLifecycleVerificationError as exc:
        raise CanonicalRunExportVerificationError(str(exc)) from exc
    try:
        actualization = verify_canonical_actualization(
            events=events,
            artifacts=artifacts,
            final_packet_projection=packet_projection,
            final_postcondition=postcondition,
            system_policy_bindings=run["system_policy_bindings"],
        )
    except CanonicalActualizationVerificationError as exc:
        raise CanonicalRunExportVerificationError(str(exc)) from exc
    verified_checks = [
        "protected_export_root",
        "canonical_event_chain",
        "artifact_integrity_and_references",
        "packet_and_postcondition_binding",
        "signed_action_receipts",
        "outcome_receipt_identity",
        "run_governance_pins",
        "run_status_and_projection_replay",
        "advancing_receipt_event_coverage",
    ]
    if fork_provenance is not None or any(
        event.get("event_type") == "run_forked" for event in events
    ):
        verified_checks.append("fork_lineage_contract")
    if proposal_lifecycle["observed"]:
        verified_checks.append("operator_proposal_disposition_lifecycle")
    if actualization["observed"]:
        verified_checks.append("canonical_actualization_lifecycle")

    unverified_claims = [
        "domain_projection_semantics",
        "external_observation_truth",
        "external_timestamp_authority",
    ]
    if has_external_fork_predecessor:
        unverified_claims.append("external_fork_predecessor_event")

    return {
        "valid": True,
        "adoption_eligible": False,
        "authenticity": "writer_signed_self_consistency",
        "export_root_hash": root,
        "run_id": run_id,
        "head_event_hash": last_event["event_hash"],
        "head_sequence": last_event["sequence"],
        "event_count": len(events),
        "artifact_count": len(artifacts),
        "receipt_count": len(receipts),
        "proposal_lifecycle": proposal_lifecycle,
        "actualization_lifecycle": actualization,
        "verified_checks": verified_checks,
        "unverified_claims": unverified_claims,
    }


def verify_canonical_run_fork_pair(
    *,
    parent_export: Mapping[str, Any],
    child_export: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify the cross-run claims that neither protected export proves alone."""

    parent_report = verify_protected_canonical_run_export(parent_export)
    child_report = verify_protected_canonical_run_export(child_export)
    parent = _mapping(parent_export, "parent protected export")
    child = _mapping(child_export, "child protected export")
    parent_run = _mapping(parent["run"], "parent run")
    child_run = _mapping(child["run"], "child run")
    if "fork_provenance" not in child_run:
        raise CanonicalRunExportVerificationError(
            "child export does not declare fork provenance"
        )
    provenance = _normalize_fork_provenance(
        child_run["fork_provenance"], "child fork provenance"
    )
    parent_events = _array(parent["events"], "parent events")
    child_events = _array(child["events"], "child events")
    parent_terminal = _mapping(parent_events[-1], "parent terminal event")
    parent_payload = _mapping(
        parent_terminal.get("payload"), "parent terminal payload"
    )
    child_genesis = _mapping(child_events[0], "child genesis event")
    child_payload = _mapping(child_genesis.get("payload"), "child genesis payload")
    if (
        parent_run.get("status") != "read_only"
        or parent_terminal.get("event_type") != "run_forked"
        or parent_payload.get("fork_provenance") != provenance
        or parent_payload.get("successor_run_id") != child_run.get("run_id")
        or provenance["forked_from_run_id"] != parent_run.get("run_id")
        or provenance["parent_head_event_hash"]
        != parent_terminal.get("prev_event_hash")
        or child_genesis.get("caused_by_event_hashes")
        != [parent_terminal.get("event_hash")]
        or child_payload.get("fork_provenance") != provenance
        or parent_run.get("owner_id") != child_run.get("owner_id")
    ):
        raise CanonicalRunExportVerificationError(
            "fork pair does not bind the exact terminal predecessor transition"
        )
    if (
        child_payload.get("initial_packet_projection")
        != parent.get("packet_projection")
        or child_payload.get("initial_postcondition") != parent.get("postcondition")
    ):
        raise CanonicalRunExportVerificationError(
            "fork successor genesis does not preserve the predecessor checkpoint"
        )

    policy_diff_hash = provenance["policy_diff_artifact_hash"]
    parent_artifacts = {
        str(row["artifact_hash"]): row
        for row in _array(parent["artifacts"], "parent artifacts")
    }
    child_artifacts = {
        str(row["artifact_hash"]): row
        for row in _array(child["artifacts"], "child artifacts")
    }
    parent_policy_diff = parent_artifacts.get(policy_diff_hash)
    child_policy_diff = child_artifacts.get(policy_diff_hash)
    if not isinstance(parent_policy_diff, Mapping) or not isinstance(
        child_policy_diff, Mapping
    ):
        raise CanonicalRunExportVerificationError(
            "fork pair is missing its shared policy-diff artifact"
        )
    if any(
        parent_policy_diff.get(field) != child_policy_diff.get(field)
        for field in ("artifact", "artifact_hash", "artifact_schema_version", "roles")
    ):
        raise CanonicalRunExportVerificationError(
            "fork pair policy-diff artifacts do not match"
        )
    policy_diff = _mapping(
        parent_policy_diff["artifact"], "fork pair policy-diff artifact"
    )
    if (
        policy_diff.get("from_effective_policy_hash")
        != parent.get("effective_policy_hash")
        or policy_diff.get("to_effective_policy_hash")
        != child.get("effective_policy_hash")
    ):
        raise CanonicalRunExportVerificationError(
            "fork pair policy-diff does not bind both effective policies"
        )
    for inherited_hash in provenance["inherited_evidence_root_hashes"]:
        parent_row = parent_artifacts.get(inherited_hash)
        child_row = child_artifacts.get(inherited_hash)
        if not isinstance(parent_row, Mapping) or not isinstance(child_row, Mapping):
            raise CanonicalRunExportVerificationError(
                "fork pair is missing an inherited evidence root"
            )
        if any(
            parent_row.get(field) != child_row.get(field)
            for field in ("artifact", "artifact_hash", "artifact_schema_version", "roles")
        ):
            raise CanonicalRunExportVerificationError(
                "fork pair inherited evidence roots do not match"
            )

    return {
        "valid": True,
        "adoption_eligible": False,
        "authenticity": "writer_signed_cross_run_self_consistency",
        "child_run_id": child_run["run_id"],
        "parent_run_id": parent_run["run_id"],
        "parent_terminal_event_hash": parent_terminal["event_hash"],
        "policy_diff_artifact_hash": policy_diff_hash,
        "verified_checks": [
            "parent_and_child_protected_exports",
            "terminal_predecessor_to_successor_lineage",
            "predecessor_checkpoint_preservation",
            "shared_policy_diff_artifact",
            "inherited_evidence_root_identity",
        ],
        "unverified_claims": sorted(
            {
                *parent_report["unverified_claims"],
                *(
                    claim
                    for claim in child_report["unverified_claims"]
                    if claim != "external_fork_predecessor_event"
                ),
            }
        ),
    }


def _verify_event_bindings(
    events: list[dict[str, Any]],
    *,
    run_id: str,
    fork_provenance: Mapping[str, Any] | None,
) -> None:
    event_hashes: set[str] = set()
    for index, event in enumerate(events):
        if event.get("run_id") != run_id:
            raise CanonicalRunExportVerificationError("event run_id mismatch")
        provenance = event.get("provenance_class")
        actor_id = event.get("actor_id")
        if provenance not in {"model", "operator", "validator", "system"}:
            raise CanonicalRunExportVerificationError("event provenance is unsupported")
        if not isinstance(actor_id, str) or not actor_id.startswith(f"{provenance}:"):
            raise CanonicalRunExportVerificationError(
                "event actor/provenance binding mismatch"
            )
        causes = _hash_array(
            event.get("caused_by_event_hashes"), "caused_by_event_hashes"
        )
        if index == 0 and fork_provenance is not None:
            if len(causes) != 1:
                raise CanonicalRunExportVerificationError(
                    "fork genesis must reference exactly one external predecessor event"
                )
        else:
            if any(cause not in event_hashes for cause in causes):
                raise CanonicalRunExportVerificationError(
                    "event cause must reference a prior event"
                )
        event_hashes.add(str(event["event_hash"]))


def _verify_run_replay(
    *,
    run: Mapping[str, Any],
    events: list[dict[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    effective_policy_hash: str,
    fork_provenance: Mapping[str, Any] | None,
    packet_projection: Mapping[str, Any],
    postcondition: Mapping[str, Any],
) -> bool:
    genesis = events[0]
    if genesis.get("event_type") != "run_created":
        raise CanonicalRunExportVerificationError(
            "canonical run genesis must be run_created"
        )
    genesis_payload = _mapping(genesis.get("payload"), "run_created payload")
    expected_genesis_fields = set(_RUN_CREATED_PAYLOAD_FIELDS)
    if fork_provenance is not None:
        expected_genesis_fields.add("fork_provenance")
    _closed(genesis_payload, expected_genesis_fields, "run_created payload")
    for payload_field, expected in (
        ("effective_policy_hash", effective_policy_hash),
        ("operator_governance_profile_hash", run["operator_governance_profile_hash"]),
        ("owner_id", run["owner_id"]),
        ("session_governance_snapshot_hash", run["session_governance_snapshot_hash"]),
        ("system_policy_bindings", run["system_policy_bindings"]),
    ):
        if genesis_payload.get(payload_field) != expected:
            raise CanonicalRunExportVerificationError(
                f"run {payload_field} does not match genesis"
            )
    if (
        genesis.get("created_at") != run.get("created_at")
        or genesis.get("actor_id") != run.get("owner_id")
        or genesis.get("provenance_class") != "operator"
    ):
        raise CanonicalRunExportVerificationError(
            "run creation identity does not match genesis"
        )

    initial_packet = _mapping(
        genesis_payload.get("initial_packet_projection"),
        "initial packet projection",
    )
    initial_postcondition = _verify_postcondition(
        genesis_payload.get("initial_postcondition"),
        packet=initial_packet,
        label="initial postcondition",
    )
    has_external_fork_predecessor = fork_provenance is not None
    if fork_provenance is None:
        if genesis.get("caused_by_event_hashes") or genesis.get(
            "caused_by_artifact_hashes"
        ):
            raise CanonicalRunExportVerificationError(
                "non-fork genesis cannot claim predecessor lineage"
            )
    else:
        if genesis_payload.get("fork_provenance") != fork_provenance:
            raise CanonicalRunExportVerificationError(
                "run fork provenance does not match genesis"
            )
        if fork_provenance["forked_from_run_id"] == run["run_id"]:
            raise CanonicalRunExportVerificationError(
                "fork predecessor and successor run_ids must differ"
            )
        expected_artifacts = sorted(
            {
                fork_provenance["policy_diff_artifact_hash"],
                *fork_provenance["inherited_evidence_root_hashes"],
            }
        )
        if genesis.get("caused_by_artifact_hashes") != expected_artifacts:
            raise CanonicalRunExportVerificationError(
                "fork genesis artifact lineage does not match provenance"
            )
        if any(
            artifacts[artifact_hash].get("created_sequence") != 0
            for artifact_hash in expected_artifacts
        ):
            raise CanonicalRunExportVerificationError(
                "fork genesis artifacts must be recorded at genesis"
            )
        policy_diff = artifacts.get(fork_provenance["policy_diff_artifact_hash"])
        _verify_fork_policy_diff_artifact(
            policy_diff,
            provenance=fork_provenance,
            expected_parent_run_id=str(fork_provenance["forked_from_run_id"]),
            expected_child_run_id=str(run["run_id"]),
            expected_from_policy_hash=None,
            expected_to_policy_hash=effective_policy_hash,
            created_at=str(genesis["created_at"]),
            expected_created_sequence=0,
        )

    replayed_packet = initial_packet
    replayed_postcondition = initial_postcondition
    replayed_status = "active"
    for index, event in enumerate(events[1:], start=1):
        if replayed_status != "active":
            raise CanonicalRunExportVerificationError(
                "canonical run contains an event after becoming read-only"
            )
        payload = _mapping(event.get("payload"), "canonical event payload")
        if event.get("event_type") == "run_forked":
            _verify_terminal_fork_event(
                event=event,
                event_index=index,
                event_count=len(events),
                run=run,
                payload=payload,
                artifacts=artifacts,
                effective_policy_hash=effective_policy_hash,
                prior_packet=replayed_packet,
                prior_postcondition=replayed_postcondition,
            )
            replayed_status = "read_only"
        has_packet = "packet_projection" in payload
        has_postcondition = "postcondition" in payload
        if has_packet != has_postcondition:
            raise CanonicalRunExportVerificationError(
                "canonical event has a partial projection transition"
            )
        if has_packet:
            replayed_packet = _mapping(
                payload["packet_projection"], "event packet projection"
            )
            replayed_postcondition = _verify_postcondition(
                payload["postcondition"],
                packet=replayed_packet,
                label="event postcondition",
            )

    if run.get("status") != replayed_status:
        raise CanonicalRunExportVerificationError(
            "run status does not match event replay"
        )
    if replayed_packet != dict(packet_projection):
        raise CanonicalRunExportVerificationError(
            "event replay does not match final packet projection"
        )
    if replayed_postcondition != dict(postcondition):
        raise CanonicalRunExportVerificationError(
            "event replay does not match final postcondition"
        )
    return has_external_fork_predecessor


def _verify_terminal_fork_event(
    *,
    event: Mapping[str, Any],
    event_index: int,
    event_count: int,
    run: Mapping[str, Any],
    payload: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
    effective_policy_hash: str,
    prior_packet: Mapping[str, Any],
    prior_postcondition: Mapping[str, Any],
) -> None:
    _closed(payload, _RUN_FORKED_PAYLOAD_FIELDS, "run_forked payload")
    provenance = _normalize_fork_provenance(
        payload.get("fork_provenance"), "run_forked fork provenance"
    )
    successor_run_id = _text(payload.get("successor_run_id"), "successor_run_id")
    if (
        event_index != event_count - 1
        or provenance["forked_from_run_id"] != run["run_id"]
        or provenance["parent_head_event_hash"] != event.get("prev_event_hash")
        or successor_run_id == run["run_id"]
        or payload.get("resulting_status") != "read_only"
        or event.get("actor_id") != run["owner_id"]
        or event.get("provenance_class") != "operator"
        or event.get("caused_by_event_hashes") != [event.get("prev_event_hash")]
        or event.get("caused_by_artifact_hashes")
        != [provenance["policy_diff_artifact_hash"]]
        or payload.get("packet_projection") != dict(prior_packet)
        or payload.get("postcondition") != dict(prior_postcondition)
    ):
        raise CanonicalRunExportVerificationError(
            "run_forked event does not bind a terminal read-only transition"
        )
    policy_diff = artifacts.get(provenance["policy_diff_artifact_hash"])
    _verify_fork_policy_diff_artifact(
        policy_diff,
        provenance=provenance,
        expected_parent_run_id=str(run["run_id"]),
        expected_child_run_id=successor_run_id,
        expected_from_policy_hash=effective_policy_hash,
        expected_to_policy_hash=None,
        created_at=str(event["created_at"]),
        expected_created_sequence=event_index,
    )


def _verify_fork_policy_diff_artifact(
    row: Mapping[str, Any] | None,
    *,
    provenance: Mapping[str, Any],
    expected_parent_run_id: str,
    expected_child_run_id: str,
    expected_from_policy_hash: str | None,
    expected_to_policy_hash: str | None,
    created_at: str,
    expected_created_sequence: int,
) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise CanonicalRunExportVerificationError(
            "fork policy-diff artifact is unavailable"
        )
    if row.get("artifact_schema_version") != _GOVERNANCE_POLICY_DIFF_VERSION or row.get(
        "roles"
    ) != ["policy_diff"]:
        raise CanonicalRunExportVerificationError(
            "fork policy-diff artifact type or roles mismatch"
        )
    if row.get("created_sequence") != expected_created_sequence:
        raise CanonicalRunExportVerificationError(
            "fork policy-diff artifact creation sequence mismatch"
        )
    artifact = _mapping(row.get("artifact"), "fork policy-diff artifact")
    _closed(
        artifact,
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
        "fork policy-diff artifact",
    )
    if artifact["governance_policy_diff_schema_version"] != (
        _GOVERNANCE_POLICY_DIFF_VERSION
    ):
        raise CanonicalRunExportVerificationError(
            "fork policy-diff artifact version mismatch"
        )
    from_policy_hash = _hash(
        artifact["from_effective_policy_hash"], "from_effective_policy_hash"
    )
    to_policy_hash = _hash(
        artifact["to_effective_policy_hash"], "to_effective_policy_hash"
    )
    if (
        artifact["parent_run_id"] != expected_parent_run_id
        or artifact["child_run_id"] != expected_child_run_id
        or artifact["fork_reason"] != provenance["fork_reason"]
        or (
            expected_from_policy_hash is not None
            and from_policy_hash != expected_from_policy_hash
        )
        or (
            expected_to_policy_hash is not None
            and to_policy_hash != expected_to_policy_hash
        )
    ):
        raise CanonicalRunExportVerificationError(
            "fork policy-diff artifact does not bind predecessor and successor"
        )
    confirmation = _mapping(
        artifact["operator_confirmation"], "fork operator confirmation"
    )
    _closed(
        confirmation,
        {"confirmed", "confirmed_at", "consequence_acknowledged", "rationale"},
        "fork operator confirmation",
    )
    if (
        confirmation["confirmed"] is not True
        or confirmation["consequence_acknowledged"] is not True
        or confirmation["confirmed_at"] != created_at
    ):
        raise CanonicalRunExportVerificationError(
            "fork operator confirmation is not exact and affirmative"
        )
    _text(confirmation["rationale"], "fork operator confirmation rationale")
    changes = _array(artifact["changes"], "fork policy-diff changes")
    paths: list[str] = []
    for change_value in changes:
        change = _mapping(change_value, "fork policy-diff change")
        _closed(
            change,
            {
                "comparison",
                "field_path",
                "prior_value_hash",
                "resulting_value_hash",
            },
            "fork policy-diff change",
        )
        if change["comparison"] not in {"replaceable", "tighter"}:
            raise CanonicalRunExportVerificationError(
                "fork policy-diff comparison is unsupported"
            )
        paths.append(_text(change["field_path"], "field_path"))
        prior_hash = _hash(change["prior_value_hash"], "prior_value_hash")
        resulting_hash = _hash(
            change["resulting_value_hash"], "resulting_value_hash"
        )
        if prior_hash == resulting_hash:
            raise CanonicalRunExportVerificationError(
                "fork policy-diff change is not a change"
            )
    if paths != sorted(set(paths)):
        raise CanonicalRunExportVerificationError(
            "fork policy-diff changes must be sorted by unique field_path"
        )
    if (from_policy_hash == to_policy_hash) != (not changes):
        raise CanonicalRunExportVerificationError(
            "fork policy-diff changes do not match the effective policy hashes"
        )
    if canonical_hash(artifact) != provenance["policy_diff_artifact_hash"]:
        raise CanonicalRunExportVerificationError(
            "fork policy-diff artifact hash mismatch"
        )
    return artifact


def _verify_postcondition(
    value: Any, *, packet: Mapping[str, Any], label: str
) -> dict[str, Any]:
    postcondition = _mapping(value, label)
    _closed(
        postcondition,
        {"active_hold", "governance_status", "packet_projection_hash", "phase"},
        label,
    )
    if postcondition["packet_projection_hash"] != canonical_hash(dict(packet)):
        raise CanonicalRunExportVerificationError(
            f"{label} packet projection hash mismatch"
        )
    if not isinstance(postcondition["active_hold"], bool):
        raise CanonicalRunExportVerificationError(
            f"{label} active_hold must be boolean"
        )
    _text(postcondition["governance_status"], f"{label} governance_status")
    _text(postcondition["phase"], f"{label} phase")
    return postcondition


def _verify_artifacts(
    value: Any, *, run_id: str, head_sequence: int
) -> dict[str, dict[str, Any]]:
    rows = _array(value, "artifacts")
    result: dict[str, dict[str, Any]] = {}
    expected_order = sorted(
        rows,
        key=lambda row: (
            row.get("created_sequence", -1) if isinstance(row, dict) else -1,
            row.get("artifact_hash", "") if isinstance(row, dict) else "",
        ),
    )
    if rows != expected_order:
        raise CanonicalRunExportVerificationError("artifacts are not canonically ordered")
    for row in rows:
        item = _mapping(row, "artifact row")
        _closed(item, _ARTIFACT_FIELDS, "artifact row")
        if item["canonical_run_artifact_schema_version"] != (
            "nepsis.canonical_run_artifact@0.1.0"
        ):
            raise CanonicalRunExportVerificationError("artifact row version mismatch")
        if item["run_id"] != run_id:
            raise CanonicalRunExportVerificationError("artifact run_id mismatch")
        created_sequence = _nonnegative_int(
            item["created_sequence"], "created_sequence"
        )
        if created_sequence > head_sequence:
            raise CanonicalRunExportVerificationError(
                "artifact creation sequence exceeds run head"
            )
        artifact = _mapping(item["artifact"], "artifact")
        artifact_hash = _hash(item["artifact_hash"], "artifact_hash")
        if canonical_hash(artifact) != artifact_hash:
            raise CanonicalRunExportVerificationError("artifact hash mismatch")
        if artifact_hash in result:
            raise CanonicalRunExportVerificationError("duplicate artifact hash")
        roles = item["roles"]
        if (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or not role for role in roles)
            or roles != sorted(set(roles))
        ):
            raise CanonicalRunExportVerificationError(
                "artifact roles must be sorted and unique"
            )
        _text(item["artifact_schema_version"], "artifact_schema_version")
        result[artifact_hash] = item
    return result


def _verify_outcome_receipt_pair(
    outcome: dict[str, Any],
    receipt: dict[str, Any],
    *,
    run_id: str,
    effective_policy_hash: str,
    profile_hash: str,
    snapshot_hash: str,
    public_key: Any,
    anchor: Mapping[str, Any],
    events: list[dict[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
) -> str | None:
    try:
        verified = verify_action_receipt(
            receipt,
            public_key=public_key,
            trust_anchor=anchor,
        )
    except Exception as exc:  # defensive boundary around cryptographic input
        raise CanonicalRunExportVerificationError(
            "action receipt verification failed"
        ) from exc
    if not verified:
        raise CanonicalRunExportVerificationError("action receipt signature mismatch")
    receipt_outcome = {
        key: deepcopy(item)
        for key, item in receipt.items()
        if key not in _RECEIPT_METADATA_FIELDS
    }
    expected_outcome = {
        key: deepcopy(item)
        for key, item in outcome.items()
        if key != "outcome_id"
    }
    if canonical_json(receipt_outcome) != canonical_json(expected_outcome):
        raise CanonicalRunExportVerificationError("receipt/outcome identity mismatch")
    expected_outcome_id = canonical_hash(
        {
            "outcome_record": expected_outcome,
            "schema": "canonical_run_store_outcome@0.1.0",
        }
    )
    if outcome.get("outcome_id") != expected_outcome_id:
        raise CanonicalRunExportVerificationError("outcome_id mismatch")
    for field, expected in (
        ("run_id", run_id),
        ("effective_policy_hash", effective_policy_hash),
        ("operator_governance_profile_hash", profile_hash),
        ("session_governance_snapshot_hash", snapshot_hash),
    ):
        if receipt.get(field) != expected:
            raise CanonicalRunExportVerificationError(f"receipt {field} mismatch")
    capability = receipt.get("capability")
    if capability not in _ACTION_RECEIPT_CAPABILITIES:
        raise CanonicalRunExportVerificationError(
            "receipt capability is unsupported"
        )
    if receipt.get("postcondition_hash") != canonical_hash(
        _mapping(receipt.get("postcondition"), "receipt postcondition")
    ):
        raise CanonicalRunExportVerificationError("receipt postcondition hash mismatch")
    artifact_hashes = _hash_array(receipt.get("artifact_hashes"), "artifact_hashes")
    if any(artifact_hash not in artifacts for artifact_hash in artifact_hashes):
        raise CanonicalRunExportVerificationError(
            "receipt references unavailable artifact"
        )
    advanced_head = receipt.get("advanced_head")
    if not isinstance(advanced_head, bool):
        raise CanonicalRunExportVerificationError(
            "receipt advanced_head must be boolean"
        )
    if advanced_head:
        sequence = _nonnegative_int(
            receipt.get("resulting_head_sequence"), "resulting_head_sequence"
        )
        if sequence >= len(events) or events[sequence]["event_hash"] != receipt.get(
            "resulting_head_event_hash"
        ):
            raise CanonicalRunExportVerificationError(
                "receipt resulting head is not in the event chain"
            )
        if receipt.get("event_hash") != receipt.get("resulting_head_event_hash"):
            raise CanonicalRunExportVerificationError("receipt event/head mismatch")
        event = events[sequence]
        if capability == "create_run":
            if sequence != 0 or receipt.get("prior_head_event_hash") != (
                CANONICAL_RUN_GENESIS_HASH
            ):
                raise CanonicalRunExportVerificationError(
                    "create receipt genesis binding mismatch"
                )
            if receipt.get("prior_head_sequence") != 0:
                raise CanonicalRunExportVerificationError(
                    "create receipt prior sequence mismatch"
                )
            if event.get("event_type") != "run_created":
                raise CanonicalRunExportVerificationError(
                    "create receipt does not identify run genesis"
                )
        else:
            if sequence == 0 or events[sequence - 1]["event_hash"] != receipt.get(
                "prior_head_event_hash"
            ):
                raise CanonicalRunExportVerificationError(
                    "receipt prior head mismatch"
                )
            if receipt.get("prior_head_sequence") != sequence - 1:
                raise CanonicalRunExportVerificationError(
                    "receipt prior sequence mismatch"
                )
            if capability == "fork_run" and event.get("event_type") != "run_forked":
                raise CanonicalRunExportVerificationError(
                    "fork receipt does not identify the terminal run-forked event"
                )
        if (
            receipt.get("expected_head_sequence")
            != receipt.get("prior_head_sequence")
            or receipt.get("expected_head_event_hash")
            != receipt.get("prior_head_event_hash")
        ):
            raise CanonicalRunExportVerificationError(
                "advancing receipt expected head does not match its prior head"
            )
        for field in (
            "idempotency_key",
            "intent_hash",
            "trusted_adapter_intent_id",
        ):
            if receipt.get(field) != event.get(field):
                raise CanonicalRunExportVerificationError(
                    f"receipt event {field} mismatch"
                )
        if sorted(artifact_hashes) != event.get("caused_by_artifact_hashes"):
            raise CanonicalRunExportVerificationError(
                "receipt artifact lineage does not match its event"
            )
        event_payload = _mapping(event.get("payload"), "receipt event payload")
        if (
            capability == "request_decision_commit"
            and receipt.get("outcome") == "committed"
        ):
            if (
                event.get("event_type") != "decision_committed"
                or event.get("provenance_class") != "validator"
                or not str(event.get("actor_id", "")).startswith("validator:")
            ):
                raise CanonicalRunExportVerificationError(
                    "decision commit event must be validator-authored"
                )
            if (
                receipt.get("provenance_class") != "operator"
                or not str(receipt.get("actor_id", "")).startswith("operator:")
            ):
                raise CanonicalRunExportVerificationError(
                    "decision commit receipt must be operator-authored"
                )
            if event_payload.get("requested_by_actor_id") != receipt.get("actor_id"):
                raise CanonicalRunExportVerificationError(
                    "validator event requester does not match its receipt actor"
                )
        elif event.get("provenance_class") == "validator":
            if event_payload.get("requested_by_actor_id") != receipt.get("actor_id"):
                raise CanonicalRunExportVerificationError(
                    "validator event requester does not match its receipt actor"
                )
            if not str(receipt.get("actor_id", "")).startswith(
                f"{receipt.get('provenance_class')}:"
            ):
                raise CanonicalRunExportVerificationError(
                    "receipt actor/provenance binding mismatch"
                )
        elif (
            receipt.get("actor_id") != event.get("actor_id")
            or receipt.get("provenance_class") != event.get("provenance_class")
        ):
            raise CanonicalRunExportVerificationError(
                "receipt event actor/provenance mismatch"
            )
        event_postcondition = event_payload.get(
            "initial_postcondition" if capability == "create_run" else "postcondition"
        )
        if event_postcondition is not None and event_postcondition != receipt.get(
            "postcondition"
        ):
            raise CanonicalRunExportVerificationError(
                "receipt postcondition does not match its event"
            )
        if capability not in {"create_run", "fork_run"}:
            event_capability = event_payload.get(
                "capability", event_payload.get("attempted_capability")
            )
            if event_capability != capability:
                raise CanonicalRunExportVerificationError(
                    "receipt capability does not match its event"
                )
        return str(event["event_hash"])
    if receipt.get("event_hash") is not None:
        raise CanonicalRunExportVerificationError(
            "non-advancing receipt cannot claim an event"
        )
    return None


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalRunExportVerificationError(f"{label} must be an object")
    return deepcopy(dict(value))


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise CanonicalRunExportVerificationError(f"{label} must be an array")
    return deepcopy(value)


def _closed(value: Mapping[str, Any], fields: set[str], label: str) -> None:
    if set(value) != fields:
        raise CanonicalRunExportVerificationError(f"{label} fields mismatch")


def _closed_optional(
    value: Mapping[str, Any],
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    fields = set(value)
    if not required <= fields or fields - required - optional:
        raise CanonicalRunExportVerificationError(f"{label} fields mismatch")


def _normalize_fork_provenance(value: Any, label: str) -> dict[str, Any]:
    provenance = _mapping(value, label)
    _closed(provenance, _FORK_PROVENANCE_FIELDS, label)
    _text(provenance["fork_reason"], "fork_reason")
    _text(provenance["forked_from_run_id"], "forked_from_run_id")
    _hash(provenance["parent_head_event_hash"], "parent_head_event_hash")
    _hash(provenance["policy_diff_artifact_hash"], "policy_diff_artifact_hash")
    inherited = _hash_array(
        provenance["inherited_evidence_root_hashes"],
        "inherited_evidence_root_hashes",
    )
    if inherited != sorted(inherited):
        raise CanonicalRunExportVerificationError(
            "inherited evidence root hashes must be canonically ordered"
        )
    provenance["inherited_evidence_root_hashes"] = inherited
    return provenance


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise CanonicalRunExportVerificationError(
            f"{field} must be a non-empty string"
        )
    return value


def _hash(value: Any, field: str) -> str:
    text = _text(value, field)
    if not _HASH_RE.fullmatch(text):
        raise CanonicalRunExportVerificationError(f"{field} must be a sha256 digest")
    return text


def _hash_array(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) != len(set(value)):
        raise CanonicalRunExportVerificationError(f"{field} must be a unique array")
    return [_hash(item, field) for item in value]


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CanonicalRunExportVerificationError(
            f"{field} must be a non-negative integer"
        )
    return value


__all__ = [
    "PROTECTED_EXPORT_VERSION",
    "CanonicalRunExportVerificationError",
    "verify_canonical_run_fork_pair",
    "verify_protected_canonical_run_export",
]
