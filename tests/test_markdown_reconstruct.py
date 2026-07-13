from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from nepsis_cgn.contracts.canonical_json import canonical_hash
from nepsis_cgn.verification.markdown_reconstruct import (
    MarkdownReconstructionError,
    _cell,
    _inline,
    _link_text,
    _safe_http_url,
    markdown_sha256,
    reconstruct_subject_markdown,
    verify_markdown_reconstruction,
)


GOLDEN_PATH = (
    Path.cwd() / "interop" / "golden" / "nepsis.interop_bundle@0.2.0.json"
)


def golden_bundle() -> dict[str, object]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_detached_reconstruction_is_byte_exact_for_full_golden_bundle() -> None:
    subject = golden_bundle()["subject"]
    assert isinstance(subject, dict)

    reconstructed = reconstruct_subject_markdown(subject)

    assert reconstructed.encode("utf-8") == subject["markdown"].encode("utf-8")
    assert markdown_sha256(reconstructed) == subject["markdown_hash"]
    assert verify_markdown_reconstruction(subject) == reconstructed


def test_resealed_replacement_markdown_is_rejected() -> None:
    attack = deepcopy(golden_bundle())
    subject = attack["subject"]
    attestation = attack["export_attestation"]
    assert isinstance(subject, dict)
    assert isinstance(attestation, dict)
    payload = attestation["payload"]
    assert isinstance(payload, dict)

    subject["markdown"] = (
        "# Nepsis Decision Journey\n\nDecision committed safely.\n"
    )
    subject["markdown_hash"] = hashlib.sha256(
        subject["markdown"].encode("utf-8")
    ).hexdigest()
    attack["subject_hash"] = canonical_hash(subject)
    payload["markdown_hash"] = subject["markdown_hash"]
    payload["subject_hash"] = attack["subject_hash"]
    attestation["payload_hash"] = canonical_hash(payload)
    attestation_envelope = {
        key: value
        for key, value in attestation.items()
        if key not in {"event_hash", "payload"}
    }
    attestation["event_hash"] = canonical_hash(attestation_envelope)

    assert canonical_hash(subject) == attack["subject_hash"]
    assert payload["markdown_hash"] == subject["markdown_hash"]
    assert payload["subject_hash"] == attack["subject_hash"]
    with pytest.raises(MarkdownReconstructionError, match="detached reconstruction"):
        verify_markdown_reconstruction(subject)


def test_missing_referenced_artifact_fails_closed() -> None:
    subject = deepcopy(golden_bundle()["subject"])
    assert isinstance(subject, dict)
    frame_hash = subject["decision_projection"]["frame_hash"]
    subject["artifact_rows"] = [
        row for row in subject["artifact_rows"] if row["artifact_hash"] != frame_hash
    ]

    with pytest.raises(MarkdownReconstructionError, match="active frame artifact"):
        reconstruct_subject_markdown(subject)


def test_markdown_escaping_matches_0_2_export_policy() -> None:
    assert _cell("alpha|beta\ngamma") == "alpha\\|beta gamma"
    assert _inline("alpha`beta\ngamma") == "alpha\\`beta gamma"
    assert _link_text("a\\b[c]\nd") == "a\\\\b\\[c\\] d"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "HTTPS://Example.com/a(1)/ü?q=[x]&ok=1#fragment",
            "https://Example.com/a%281%29/%C3%BC?q=%5Bx%5D&ok=1",
        ),
        ("javascript:alert(1)", ""),
        ("https://example.com/a b", ""),
        ("https:///missing-host", ""),
    ],
)
def test_research_evidence_urls_are_safely_normalized(
    url: str, expected: str
) -> None:
    assert _safe_http_url(url) == expected


def test_detached_module_has_no_nepsismc_or_runtime_implementation_imports() -> None:
    module_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "nepsis_cgn"
        / "verification"
        / "markdown_reconstruct.py"
    )
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    ] + [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert not any(name.startswith("nepsismc") for name in imports)
    assert not any(
        fragment in name
        for name in imports
        for fragment in ("event_store", "decision_projection", "phase_machine")
    )
