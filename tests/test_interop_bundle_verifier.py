from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from nepsis_cgn.contracts.canonical_json import canonical_hash
from nepsis_cgn.verification.interop_bundle import (
    InteropVerificationError,
    verify_interop_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_PATH = ROOT / "interop" / "golden" / "nepsis.interop_bundle@0.2.0.json"
VECTORS_PATH = (
    ROOT / "interop" / "tamper_vectors" / "nepsis.interop_bundle@0.2.0.json"
)


def _golden() -> dict:
    value = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _included_artifact(bundle: dict, schema_version: str) -> dict:
    return next(
        row
        for row in bundle["subject"]["artifact_rows"]
        if row["included"] and row["schema_version"] == schema_version
    )


def test_independent_verifier_accepts_exact_mc_golden_truthfully() -> None:
    report = verify_interop_bundle(_golden())
    assert report["valid"] is True
    assert report["authenticity"] == "unanchored_self_consistency"
    assert report["anchor_status"] == "unanchored"
    assert report["adoption_eligible"] is False
    assert "accepted_manual_calibration_materialization" in report["verified_checks"]
    assert "nonresampled_integer_inference_recomputation" in report[
        "verified_checks"
    ]
    assert "governance_red_blue_recomputation" in report["verified_checks"]
    assert "inference_resampling_path" in report["unverified_claims"]


def test_every_declared_tamper_vector_has_an_executable_refusal() -> None:
    declarations = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))
    declared_ids = {row["vector_id"] for row in declarations["vectors"]}
    mutators = {
        "audit_payload_mutation": _tamper_audit_payload,
        "artifact_content_mutation": _tamper_artifact_content,
        "artifact_root_mutation": _tamper_artifact_root,
        "lineage_binding_mutation": _tamper_lineage,
        "calibration_acceptance_mutation": _tamper_calibration_acceptance,
        "subject_projection_mutation": _tamper_projection,
        "attestation_mutation": _tamper_attestation,
    }
    assert set(mutators) == declared_ids

    for vector_id in sorted(declared_ids):
        candidate = _golden()
        mutators[vector_id](candidate)
        if vector_id != "attestation_mutation":
            _rebind_outer(candidate)
        with pytest.raises(InteropVerificationError):
            verify_interop_bundle(candidate)


def test_unknown_versions_and_extra_fields_are_refused() -> None:
    unknown = _golden()
    unknown["interop_bundle_version"] = "nepsis.interop_bundle@9.9.9"
    with pytest.raises(InteropVerificationError, match="unsupported"):
        verify_interop_bundle(unknown)

    extra = _golden()
    extra["subject"]["optimistic_success"] = True
    with pytest.raises(InteropVerificationError):
        verify_interop_bundle(extra)

    unknown_artifact = _golden()
    unknown_artifact["subject"]["artifact_rows"][0]["schema_version"] = (
        "nepsis.unknown@9.9.9"
    )
    _rebind_outer(unknown_artifact)
    with pytest.raises(InteropVerificationError, match="unsupported artifact"):
        verify_interop_bundle(unknown_artifact)


def test_full_payload_omission_bool_sequence_and_invalid_roles_fail_closed() -> None:
    missing_payload = _golden()
    missing_payload["subject"]["audit_events"][5].pop("payload")
    _rebind_outer(missing_payload)
    with pytest.raises(InteropVerificationError, match="missing fields: payload"):
        verify_interop_bundle(missing_payload)

    bool_sequence = _golden()
    bool_sequence["subject"]["audit_events"][0]["sequence"] = False
    _rebind_outer(bool_sequence)
    with pytest.raises(InteropVerificationError, match="sequence"):
        verify_interop_bundle(bool_sequence)

    invalid_role = _golden()
    invalid_role["subject"]["artifact_rows"][0]["roles"] = [1]
    _rebind_outer(invalid_role)
    with pytest.raises(InteropVerificationError, match="roles"):
        verify_interop_bundle(invalid_role)


def test_resealed_duplicate_governance_event_is_refused() -> None:
    candidate = _golden()
    candidate["subject"]["audit_events"][11]["event_type"] = (
        "red_governance_evaluated"
    )
    _reseal_chain_and_bundle(candidate)
    with pytest.raises(InteropVerificationError, match="exactly one"):
        verify_interop_bundle(candidate)


def test_resealed_blue_before_red_is_still_refused() -> None:
    candidate = _golden()
    events = candidate["subject"]["audit_events"]
    events[10]["event_type"], events[12]["event_type"] = (
        events[12]["event_type"],
        events[10]["event_type"],
    )
    _reseal_chain_and_bundle(candidate)

    with pytest.raises(InteropVerificationError, match="ordering"):
        verify_interop_bundle(candidate)


def test_rebound_phase_projection_cannot_claim_a_different_state() -> None:
    candidate = _golden()
    candidate["subject"]["phase_projection"]["projected_phase"] = "decision_ready"
    _rebind_outer(candidate)

    with pytest.raises(InteropVerificationError, match="phase projection"):
        verify_interop_bundle(candidate)


def test_rebound_lineage_node_cannot_point_to_the_wrong_artifact_type() -> None:
    candidate = _golden()
    subject = candidate["subject"]
    lineage_row = _included_artifact(
        candidate, "nepsis.particle_lineage@0.1.0"
    )
    frame_row = _included_artifact(candidate, "nepsis.frame@0.1.0")
    lineage_row["artifact"]["nodes"][0]["artifact_hash"] = frame_row[
        "artifact_hash"
    ]
    old_lineage_hash = lineage_row["artifact_hash"]
    new_lineage_hash = canonical_hash(lineage_row["artifact"])
    lineage_row["artifact_hash"] = new_lineage_hash
    subject["particle_lineage_root"] = new_lineage_hash
    subject["decision_projection"]["particle_lineage_hash"] = new_lineage_hash
    subject["artifact_rows"].sort(key=lambda row: row["artifact_hash"])
    subject["artifact_root"] = _artifact_root(subject["artifact_rows"])
    _rebind_outer(candidate)

    assert new_lineage_hash != old_lineage_hash
    with pytest.raises(InteropVerificationError, match="wrong artifact type"):
        verify_interop_bundle(candidate)


def test_verifier_imports_neither_product_runtime() -> None:
    module_path = (
        ROOT / "src" / "nepsis_cgn" / "verification" / "interop_bundle.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    assert set(imports) <= {
        "__future__",
        "copy",
        "hashlib",
        "typing",
        "nepsis_cgn.contracts.canonical_json",
        "nepsis_cgn.verification.markdown_reconstruct",
        "nepsis_cgn.verification.semantic_recompute",
    }


def _tamper_audit_payload(bundle: dict) -> None:
    bundle["subject"]["audit_events"][1]["payload"]["decision_id"] = "tampered"


def _tamper_artifact_content(bundle: dict) -> None:
    row = next(row for row in bundle["subject"]["artifact_rows"] if row["included"])
    row["artifact"]["session_id"] = "session_tampered"


def _tamper_artifact_root(bundle: dict) -> None:
    bundle["subject"]["artifact_root"] = "0" * 64


def _tamper_lineage(bundle: dict) -> None:
    row = _included_artifact(bundle, "nepsis.particle_lineage@0.1.0")
    row["artifact"]["nodes"][0]["artifact_hash"] = "0" * 64


def _tamper_calibration_acceptance(bundle: dict) -> None:
    row = _included_artifact(bundle, "nepsis.calibration_acceptance@0.1.0")
    row["artifact"]["selected_prior_rows"][0]["weight_ppm"] += 1


def _tamper_projection(bundle: dict) -> None:
    bundle["subject"]["decision_projection"]["status"] = "tampered"


def _tamper_attestation(bundle: dict) -> None:
    bundle["export_attestation"]["event_hash"] = "0" * 64


def _reseal_chain_and_bundle(bundle: dict) -> None:
    events = bundle["subject"]["audit_events"]
    previous = hashlib.sha256(b"nepsis.genesis@0.1.0").hexdigest()
    for event in events:
        event["prev_event_hash"] = previous
        event["payload_hash"] = canonical_hash(event["payload"])
        envelope = {
            key: deepcopy(value)
            for key, value in event.items()
            if key not in {"payload", "event_hash"}
        }
        event["event_hash"] = canonical_hash(envelope)
        previous = event["event_hash"]

    subject = bundle["subject"]
    subject["audit_range"]["tip_event_hash"] = previous
    subject_hash = canonical_hash(subject)
    bundle["subject_hash"] = subject_hash

    attestation = bundle["export_attestation"]
    attestation["prev_event_hash"] = previous
    attestation["payload"]["subject_audit_tip"] = previous
    attestation["payload"]["subject_hash"] = subject_hash
    attestation["payload_hash"] = canonical_hash(attestation["payload"])
    envelope = {
        key: deepcopy(value)
        for key, value in attestation.items()
        if key not in {"payload", "event_hash"}
    }
    attestation["event_hash"] = canonical_hash(envelope)


def _rebind_outer(bundle: dict) -> None:
    subject = bundle["subject"]
    subject_hash = canonical_hash(subject)
    bundle["subject_hash"] = subject_hash
    attestation = bundle["export_attestation"]
    attestation["payload"]["artifact_root"] = subject["artifact_root"]
    attestation["payload"]["markdown_hash"] = subject["markdown_hash"]
    attestation["payload"]["profile"] = subject["profile"]
    attestation["payload"]["subject_hash"] = subject_hash
    attestation["payload_hash"] = canonical_hash(attestation["payload"])
    envelope = {
        key: deepcopy(value)
        for key, value in attestation.items()
        if key not in {"payload", "event_hash"}
    }
    attestation["event_hash"] = canonical_hash(envelope)


def _artifact_root(rows: list[dict]) -> str:
    return canonical_hash(
        {
            "artifact_rows": [
                {
                    "artifact_hash": row["artifact_hash"],
                    "roles": row["roles"],
                    "schema_version": row["schema_version"],
                }
                for row in rows
            ]
        }
    )
