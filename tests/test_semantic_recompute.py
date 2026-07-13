from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from nepsis_cgn.contracts.canonical_json import canonical_hash
from nepsis_cgn.verification.interop_bundle import (
    InteropVerificationError,
    verify_interop_bundle,
)
from nepsis_cgn.verification.markdown_reconstruct import (
    markdown_sha256,
    reconstruct_subject_markdown,
)
from nepsis_cgn.verification.semantic_recompute import (
    SemanticVerificationError,
    UnsupportedSemanticPath,
    effective_sample_size_fraction_ppm,
    normalize_integer_weights,
    verify_semantics,
)


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "interop" / "golden" / "nepsis.interop_bundle@0.2.0.json"
MODULE = ROOT / "src" / "nepsis_cgn" / "verification" / "semantic_recompute.py"
GENESIS = hashlib.sha256(b"nepsis.genesis@0.1.0").hexdigest()


def _golden() -> dict[str, Any]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def _artifact_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["artifact_hash"]: row["artifact"]
        for row in bundle["subject"]["artifact_rows"]
    }


def _replace(value: Any, replacements: dict[str, str]) -> Any:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace(item, replacements) for key, item in value.items()
        }
    return value


def _event_hash(event: dict[str, Any]) -> str:
    envelope = {
        key: deepcopy(value)
        for key, value in event.items()
        if key not in {"event_hash", "payload"}
    }
    return canonical_hash(envelope)


def _reseal(bundle: dict[str, Any]) -> None:
    subject = bundle["subject"]
    old_events = subject["audit_events"]
    event_replacements: dict[str, str] = {}
    new_events: list[dict[str, Any]] = []
    previous = GENESIS
    for old_event in old_events:
        old_hash = old_event["event_hash"]
        event = deepcopy(old_event)
        event["payload"] = _replace(event["payload"], event_replacements)
        event["prev_event_hash"] = previous
        event["payload_hash"] = canonical_hash(event["payload"])
        event["event_hash"] = _event_hash(event)
        event_replacements[old_hash] = event["event_hash"]
        new_events.append(event)
        previous = event["event_hash"]

    subject["audit_events"] = new_events
    subject["audit_range"]["tip_event_hash"] = previous
    subject["phase_projection"] = _replace(
        subject["phase_projection"], event_replacements
    )
    bundle["subject_hash"] = canonical_hash(subject)

    attestation = bundle["export_attestation"]
    attestation["prev_event_hash"] = previous
    attestation["payload"]["artifact_root"] = subject["artifact_root"]
    attestation["payload"]["subject_audit_tip"] = previous
    attestation["payload"]["subject_hash"] = bundle["subject_hash"]
    attestation["payload_hash"] = canonical_hash(attestation["payload"])
    attestation["event_hash"] = _event_hash(attestation)


def _mutated_artifact_bundle(
    schema_version: str,
    mutate: Callable[[dict[str, Any]], None],
    *,
    refresh_markdown: bool = False,
) -> dict[str, Any]:
    bundle = _golden()
    subject = bundle["subject"]
    matches = [
        row
        for row in subject["artifact_rows"]
        if row["schema_version"] == schema_version
    ]
    assert len(matches) == 1
    row = matches[0]
    old_hash = row["artifact_hash"]
    mutate(row["artifact"])
    new_hash = canonical_hash(row["artifact"])
    assert new_hash != old_hash
    row["artifact_hash"] = new_hash

    replacements = {old_hash: new_hash}
    for event in subject["audit_events"]:
        event["payload"] = _replace(event["payload"], replacements)
    subject["decision_projection"] = _replace(
        subject["decision_projection"], replacements
    )
    subject["artifact_rows"].sort(key=lambda item: item["artifact_hash"])
    root_rows = [
        {
            "artifact_hash": item["artifact_hash"],
            "roles": item["roles"],
            "schema_version": item["schema_version"],
        }
        for item in subject["artifact_rows"]
    ]
    subject["artifact_root"] = canonical_hash({"artifact_rows": root_rows})
    _reseal(bundle)
    if refresh_markdown:
        subject["markdown"] = reconstruct_subject_markdown(subject)
        subject["markdown_hash"] = markdown_sha256(subject["markdown"])
        bundle["export_attestation"]["payload"]["markdown_hash"] = subject[
            "markdown_hash"
        ]
        _reseal(bundle)
    return bundle


def _semantic_result(bundle: dict[str, Any]) -> dict[str, Any]:
    subject = bundle["subject"]
    return verify_semantics(
        events=subject["audit_events"],
        artifacts=_artifact_map(bundle),
        subject=subject,
    )


def _mutate_manual_priors(acceptance: dict[str, Any]) -> None:
    acceptance["selected_prior_rows"][0]["weight_ppm"] = 500_000
    acceptance["selected_prior_rows"][1]["weight_ppm"] = 500_000
    preimage = {
        key: deepcopy(value)
        for key, value in acceptance.items()
        if key
        not in {
            "acceptance_id",
            "calibration_acceptance_schema_version",
        }
    }
    preimage["proposal_hash"] = ""
    acceptance["acceptance_id"] = (
        f"acceptance_{canonical_hash(preimage)[:20]}"
    )


def test_golden_bundle_semantics_recompute_independently() -> None:
    result = _semantic_result(_golden())

    assert result["valid"] is True
    assert result["calibration"] == {
        "acceptance_hash": (
            "5eb6619382c4eb7d0f22569edff234924c280992a0a48767cfa207bb276b9c01"
        ),
        "population_hash": (
            "a4f1661ec833d3632722a65c8f7e84d287216d4028fa10b7bd14f32f2f52b99d"
        ),
        "predictions_hash": (
            "dc5d7699c39defa490cee999c1864a6907f9cfc36d92a188942622476951519b"
        ),
    }
    assert result["inference"]["absolute_fit_ppm"] == 420_000
    assert result["inference"]["ess_fraction_ppm"] == 662_161
    assert result["governance"]["admissible_action_ids"] == ["act_treat"]
    assert result["governance"]["proposed_action_id"] == "act_treat"


def test_integer_normalization_and_ess_match_kernel_rules() -> None:
    assert normalize_integer_weights({"z": 1, "a": 1, "m": 1}) == {
        "a": 333_334,
        "m": 333_333,
        "z": 333_333,
    }
    assert effective_sample_size_fraction_ppm(
        {"particle_hazard": 857_143, "particle_low_risk": 142_857}
    ) == 662_161


@pytest.mark.parametrize(
    ("schema_version", "mutate", "message"),
    [
        (
            "nepsis.calibration_acceptance@0.1.0",
            _mutate_manual_priors,
            "manual calibration population materialization mismatch",
        ),
        (
            "nepsis.population_update@0.1.0",
            lambda artifact: artifact.__setitem__(
                "ess_fraction_ppm", artifact["ess_fraction_ppm"] - 1
            ),
            "population update recomputation mismatch",
        ),
        (
            "nepsis.governance_decision@0.1.0",
            lambda artifact: artifact["blue_action_rows"][0].__setitem__(
                "expected_utility_microunits",
                artifact["blue_action_rows"][0]["expected_utility_microunits"]
                + 1,
            ),
            "governance decision recomputation mismatch",
        ),
    ],
)
def test_resealed_semantic_tamper_is_rejected_by_integrated_recomputation(
    schema_version: str,
    mutate: Callable[[dict[str, Any]], None],
    message: str,
) -> None:
    bundle = _mutated_artifact_bundle(
        schema_version,
        mutate,
        refresh_markdown=True,
    )

    assert reconstruct_subject_markdown(bundle["subject"]) == bundle["subject"][
        "markdown"
    ]
    with pytest.raises(InteropVerificationError, match=message):
        verify_interop_bundle(bundle)
    with pytest.raises(SemanticVerificationError, match=message):
        _semantic_result(bundle)


def test_resampling_is_explicitly_unsupported() -> None:
    bundle = _mutated_artifact_bundle(
        "nepsis.population_update@0.1.0",
        lambda artifact: artifact.__setitem__(
            "resample_ess_threshold_ppm", 700_000
        ),
        refresh_markdown=True,
    )

    report = verify_interop_bundle(bundle)
    assert report["valid"] is True
    assert report["adoption_eligible"] is False
    assert (
        "subject_semantic_path:resampling is not supported"
        in report["unverified_claims"]
    )
    assert "accepted_manual_calibration_materialization" not in report[
        "verified_checks"
    ]
    assert "nonresampled_integer_inference_recomputation" not in report[
        "verified_checks"
    ]
    assert "governance_red_blue_recomputation" not in report["verified_checks"]
    with pytest.raises(UnsupportedSemanticPath, match="resampling"):
        _semantic_result(bundle)


def test_semantic_module_has_only_neutral_imports() -> None:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert imports == {
        "__future__",
        "copy",
        "typing",
        "nepsis_cgn.contracts.canonical_json",
    }
    source = MODULE.read_text(encoding="utf-8")
    assert "nepsismc" not in source
    assert "ledger" not in source
