from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nepsis_cgn.api.orchestration_packet import (
    LAYER_ORDER,
    SCHEMA,
    abandon_v3_orchestration,
    artifact_hash,
    canonical_hash,
    finalize_v3_orchestration,
    inspect_v3_orchestration,
    lock_v3_layer,
    propose_v3_layer,
    start_v3_orchestration,
)


NOW = datetime(2026, 6, 21, 12, 0, 0, tzinfo=timezone.utc)
TEST_V3_SEAL_SECRET = "unit-test-v3-packet-seal-secret"


@pytest.fixture(autouse=True)
def _configured_v3_packet_seal_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEPSIS_V3_PACKET_SEAL_SECRET", TEST_V3_SEAL_SECRET)


def _browser_json_roundtrip(value: object) -> object:
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [_browser_json_roundtrip(item) for item in value]
    if isinstance(value, dict):
        return {key: _browser_json_roundtrip(item) for key, item in value.items()}
    return value


def _field(state: str = "present", items: list[str] | None = None, rationale: str = "Reviewed.") -> dict[str, object]:
    return {"status": state, "items": items if items is not None else ["captured"], "rationale": rationale}


def _base_artifact(layer: str) -> dict[str, object]:
    return {
        "layer": layer,
        "summary": f"{layer} layer artifact.",
        "goal_scope": _field(items=["goal", "scope"]),
        "red_triggers": _field(),
        "blue_opportunity_space": _field(),
        "constraints": _field(),
        "manifold_match_mismatch": _field(),
        "still_blockers": _field("none_found", [], "No blocker found at this layer."),
        "unresolved_questions": _field("none_found", [], "No unresolved question found at this layer."),
        "audit_notes": _field(items=["packet visible"]),
        "proposed_status": _field(items=["ready"]),
        "lock_eligibility": _field(items=["eligible"]),
        "layer_findings": {
            "risk": [f"{layer} risk"],
            "ruin": [],
            "win": [f"{layer} win"],
            "recommendations": [],
        },
    }


def _artifact_for(layer: str) -> dict[str, object]:
    artifact = _base_artifact(layer)
    if layer == "intake":
        artifact["intake"] = {
            "goal": "Build V3 packet kernel.",
            "scope": "MCP stateless orchestration.",
            "assumptions": ["Host model drafts artifacts."],
            "unresolved_questions": ["None for first pass."],
        }
    elif layer == "red":
        artifact["red"] = {
            "triggers": ["rollback confusion", "hidden memory"],
            "ruin_paths": ["uninspectable model-to-model drift"],
            "constraints": ["No hidden subagent memory."],
            "safety_blockers": ["Do not finalize with unresolved ruin."],
        }
    elif layer == "manifold":
        artifact["manifold"] = {
            "matches": ["stateless operator packet"],
            "mismatches": ["not an agent framework"],
            "false_analogies": ["shared hidden memory"],
        }
    elif layer == "blue":
        artifact["blue"] = {
            "wins": ["transparent governance", "deterministic validation"],
            "bounded_by_red": ["no server-side model calls"],
        }
    elif layer == "still":
        artifact["still"] = {
            "blockers": [],
            "go_no_go": "go_with_packet_bound_locks",
            "restraint_conditions": ["do not add run-head ledger in V3 first pass"],
        }
    elif layer == "synthesis":
        artifact["synthesis"] = {
            "recommendations": [
                {
                    "text": "Proceed with V3 packet kernel implementation.",
                    "supports_win": ["transparent governance"],
                    "mitigates_risk": ["hash-bound user locks"],
                    "unresolved_ruin": [],
                }
            ]
        }
        artifact["layer_findings"] = {
            "risk": ["rollback/forking before TTL"],
            "ruin": [],
            "win": ["transparent governance"],
            "recommendations": ["Proceed with V3 packet kernel implementation."],
        }
    elif layer == "audit":
        artifact["audit"] = {
            "lineage_checked": True,
            "unresolved_uncertainty": ["Pure stateless rollback remains fork-permitted until TTL."],
            "risk_ruin_win_consistent": True,
        }
    return artifact


def _lock_assertion(packet: dict[str, object], *, text: str = "I explicitly lock this layer.") -> dict[str, object]:
    proposal = packet["current_proposal"]
    assert isinstance(proposal, dict)
    return {
        "asserted": True,
        "assertion_text": text,
        "proposal_hash": proposal["artifact_hash"],
        "lock_nonce": f"nonce-{proposal['layer']}",
    }


def _lock_current(packet: dict[str, object]) -> dict[str, object]:
    layer = str(packet["current_layer"])
    proposed = propose_v3_layer(packet, layer=layer, artifact=_artifact_for(layer), now=NOW)
    return lock_v3_layer(proposed, layer=layer, lock_assertion=_lock_assertion(proposed), now=NOW)


def _locked_through(layer: str) -> dict[str, object]:
    packet = start_v3_orchestration(
        goal="Build V3 packet kernel.",
        scope="MCP stateless orchestration.",
        initial_context="No hidden subagent memory.",
        now=NOW,
    )
    for current in LAYER_ORDER:
        packet = _lock_current(packet)
        if current == layer:
            return packet
    return packet


def _subprocess_env(*, seal_secret: str | None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    env.pop("NEPSIS_V3_PACKET_SEAL_SECRET", None)
    env.pop("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", None)
    if seal_secret is not None:
        env["NEPSIS_V3_PACKET_SEAL_SECRET"] = seal_secret
    return env


def test_v3_stateless_packet_seal_requires_configured_stable_secret() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from nepsis_cgn.api.orchestration_packet import start_v3_orchestration; "
                "start_v3_orchestration(goal='Goal', scope='Scope')"
            ),
        ],
        env=_subprocess_env(seal_secret=None),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "NEPSIS_V3_PACKET_SEAL_SECRET" in result.stderr


def test_v3_stateless_packet_seal_survives_cross_process_when_secret_is_configured() -> None:
    start = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from nepsis_cgn.api.orchestration_packet import start_v3_orchestration; "
                "print(json.dumps(start_v3_orchestration(goal='Goal', scope='Scope')))"
            ),
        ],
        env=_subprocess_env(seal_secret=TEST_V3_SEAL_SECRET),
        text=True,
        capture_output=True,
        check=True,
    )
    inspected = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; "
                "from nepsis_cgn.api.orchestration_packet import inspect_v3_orchestration; "
                "packet = json.loads(sys.stdin.read()); "
                "print(json.dumps(inspect_v3_orchestration(packet)))"
            ),
        ],
        input=start.stdout,
        env=_subprocess_env(seal_secret=TEST_V3_SEAL_SECRET),
        text=True,
        capture_output=True,
        check=True,
    )

    assert json.loads(inspected.stdout)["status"] == "active"


def test_start_packet_has_schema_ttl_layer_order_and_integrity() -> None:
    packet = start_v3_orchestration(
        goal="Build V3 packet kernel.",
        scope="MCP stateless orchestration.",
        initial_context="No hidden subagent memory.",
        ttl_seconds=3600,
        now=NOW,
    )

    inspected = inspect_v3_orchestration(packet, now=NOW)

    assert packet["schema"] == SCHEMA
    assert packet["packet_seq"] == 0
    assert packet["status"] == "active"
    assert packet["current_layer"] == "intake"
    assert packet["layer_order"] == LAYER_ORDER
    assert packet["locked_layers"] == {}
    assert packet["current_proposal"] is None
    assert packet["expires_at"] == "2026-06-21T13:00:00.000Z"
    assert packet["integrity"]["seal_version"] == "hmac-sha256:v1"
    assert inspected["valid"] is True
    assert inspected["next_legal_actions"] == ["propose_v3_layer", "abandon_v3_orchestration"]


def test_canonical_hash_is_stable_for_key_order_and_changes_for_type_changes() -> None:
    left = {"b": [2, {"y": "z"}], "a": 1}
    right = {"a": 1, "b": [2, {"y": "z"}]}
    changed_type = {"a": "1", "b": [2, {"y": "z"}]}

    assert canonical_hash(left) == canonical_hash(right)
    assert canonical_hash(left) != canonical_hash(changed_type)


def test_tampered_packet_rejected_by_hmac() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", now=NOW)
    packet["current_layer"] = "red"

    with pytest.raises(ValueError, match="integrity seal verification failed"):
        inspect_v3_orchestration(packet, now=NOW)


def test_v3_packet_seal_survives_browser_integral_float_roundtrip() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", now=NOW)
    artifact = _artifact_for("intake")
    intake = artifact["intake"]
    assert isinstance(intake, dict)
    intake["priority"] = 1.0
    proposed = propose_v3_layer(packet, layer="intake", artifact=artifact, now=NOW)
    browser_packet = _browser_json_roundtrip(proposed)

    locked = lock_v3_layer(
        browser_packet,  # type: ignore[arg-type]
        layer="intake",
        lock_assertion=_lock_assertion(proposed),
        now=NOW,
    )

    assert locked["current_layer"] == "red"
    assert "intake" in locked["locked_layers"]


def test_expired_packet_rejected_but_older_valid_packet_can_fork_before_expiry() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", ttl_seconds=1, now=NOW)
    proposed = propose_v3_layer(packet, layer="intake", artifact=_artifact_for("intake"), now=NOW)
    first = lock_v3_layer(proposed, layer="intake", lock_assertion=_lock_assertion(proposed), now=NOW)
    second = lock_v3_layer(
        proposed,
        layer="intake",
        lock_assertion={**_lock_assertion(proposed), "lock_nonce": "different-valid-branch"},
        now=NOW,
    )

    assert first["run_id"] == second["run_id"] == packet["run_id"]
    assert first["current_layer"] == second["current_layer"] == "red"
    assert canonical_hash(first) != canonical_hash(second)

    with pytest.raises(ValueError, match="expired"):
        inspect_v3_orchestration(packet, now=datetime(2026, 6, 21, 12, 0, 2, tzinfo=timezone.utc))


def test_proposal_records_full_artifact_validation_and_does_not_advance() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", now=NOW)
    artifact = _artifact_for("intake")

    proposed = propose_v3_layer(
        packet,
        layer="intake",
        artifact=artifact,
        draft_metadata={"host": "codex", "model_name": "gpt-5", "prompt_hash": "sha256:prompt"},
        now=NOW,
    )

    assert proposed["packet_seq"] == 1
    assert proposed["current_layer"] == "intake"
    assert proposed["locked_layers"] == {}
    assert proposed["current_proposal"]["artifact"] == artifact
    assert proposed["current_proposal"]["artifact_hash"] == artifact_hash(artifact)
    assert proposed["current_proposal"]["draft_metadata"]["host"] == "codex"
    assert proposed["current_proposal"]["validation"]["schema_valid"] is True
    assert proposed["current_proposal"]["validation"]["lock_eligible"] is True
    assert proposed["lineage"][-1]["event"] == "propose"


def test_proposal_for_wrong_layer_rejected() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", now=NOW)

    with pytest.raises(ValueError, match="current layer"):
        propose_v3_layer(packet, layer="red", artifact=_artifact_for("red"), now=NOW)


def test_tri_state_contract_rejects_silent_empty_arrays_at_lock() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", now=NOW)
    artifact = _artifact_for("intake")
    artifact["blue_opportunity_space"] = {"status": "present", "items": [], "rationale": "Silent empty array."}
    proposed = propose_v3_layer(packet, layer="intake", artifact=artifact, now=NOW)

    assert proposed["current_proposal"]["validation"]["schema_valid"] is True
    assert proposed["current_proposal"]["validation"]["lock_eligible"] is False

    with pytest.raises(ValueError, match="blue_opportunity_space"):
        lock_v3_layer(proposed, layer="intake", lock_assertion=_lock_assertion(proposed), now=NOW)


def test_unknown_and_not_applicable_contract_states_do_not_require_items() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", now=NOW)
    artifact = _artifact_for("intake")
    artifact["blue_opportunity_space"] = {
        "status": "unknown",
        "items": [],
        "rationale": "Not assessed until blue layer.",
    }
    artifact["manifold_match_mismatch"] = {
        "status": "not_applicable",
        "items": [],
        "rationale": "Not assessed until manifold layer.",
    }
    proposed = propose_v3_layer(packet, layer="intake", artifact=artifact, now=NOW)
    locked = lock_v3_layer(proposed, layer="intake", lock_assertion=_lock_assertion(proposed), now=NOW)

    assert locked["locked_layers"]["intake"]["artifact"]["blue_opportunity_space"]["status"] == "unknown"
    assert locked["current_layer"] == "red"


def test_lock_requires_hash_bound_user_assertion_for_current_proposal() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", now=NOW)
    proposed = propose_v3_layer(packet, layer="intake", artifact=_artifact_for("intake"), now=NOW)

    with pytest.raises(ValueError, match="proposal_hash"):
        lock_v3_layer(
            proposed,
            layer="intake",
            lock_assertion={"asserted": True, "assertion_text": "I lock.", "lock_nonce": "nonce"},
            now=NOW,
        )

    with pytest.raises(ValueError, match="proposal hash"):
        lock_v3_layer(
            proposed,
            layer="intake",
            lock_assertion={
                "asserted": True,
                "assertion_text": "I lock.",
                "proposal_hash": "sha256:not-the-current-proposal",
                "lock_nonce": "nonce",
            },
            now=NOW,
        )

    locked = lock_v3_layer(proposed, layer="intake", lock_assertion=_lock_assertion(proposed), now=NOW)

    assert locked["current_layer"] == "red"
    assert locked["current_proposal"] is None
    assert locked["locked_layers"]["intake"]["artifact_hash"] == proposed["current_proposal"]["artifact_hash"]
    assert locked["locked_layers"]["intake"]["locked_by_assertion_hash"].startswith("sha256:")


def test_locked_layer_cannot_be_modified_and_later_layer_depends_on_locked_prior_layers() -> None:
    locked_intake = _locked_through("intake")

    with pytest.raises(ValueError, match="already locked"):
        lock_v3_layer(locked_intake, layer="intake", lock_assertion={"asserted": True}, now=NOW)

    proposed_red = propose_v3_layer(locked_intake, layer="red", artifact=_artifact_for("red"), now=NOW)
    tampered = dict(proposed_red)
    tampered["locked_layers"] = dict(proposed_red["locked_layers"])
    tampered["locked_layers"]["intake"] = dict(proposed_red["locked_layers"]["intake"])
    changed_artifact = _artifact_for("intake")
    changed_artifact["summary"] = "tampered intake artifact"
    tampered["locked_layers"]["intake"]["artifact"] = changed_artifact

    with pytest.raises(ValueError, match="integrity seal verification failed"):
        lock_v3_layer(tampered, layer="red", lock_assertion=_lock_assertion(proposed_red), now=NOW)


def test_finalize_requires_all_layers_and_traces_recommendations_to_locked_artifacts() -> None:
    partial = _locked_through("red")

    with pytest.raises(ValueError, match="requires all layers locked"):
        finalize_v3_orchestration(partial, now=NOW)

    packet = _locked_through("audit")
    finalized = finalize_v3_orchestration(packet, now=NOW)
    final = finalized["final_response_packet"]

    assert finalized["status"] == "finalized"
    assert finalized["current_layer"] is None
    assert final["goal"] == "Build V3 packet kernel."
    assert "rollback/forking before TTL" in final["risk"]
    assert "transparent governance" in final["win"]
    assert final["recommendations"][0]["text"] == "Proceed with V3 packet kernel implementation."
    assert final["recommendations"][0]["source_layers"] == ["synthesis"]
    assert final["recommendations"][0]["unresolved_ruin"] == []
    assert final["lineage_hashes"]["synthesis"].startswith("sha256:")
    assert any("Pure stateless rollback" in item for item in final["unresolved_questions"])


def test_blue_win_cannot_erase_unresolved_red_ruin_in_finalization() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", now=NOW)
    for layer in LAYER_ORDER:
        artifact = _artifact_for(layer)
        if layer == "red":
            artifact["layer_findings"] = {"risk": [], "ruin": ["hidden memory drift"], "win": [], "recommendations": []}
        if layer == "synthesis":
            artifact["synthesis"] = {
                "recommendations": [
                    {
                        "text": "Proceed anyway.",
                        "supports_win": ["speed"],
                        "mitigates_risk": [],
                        "unresolved_ruin": ["hidden memory drift"],
                    }
                ]
            }
            artifact["layer_findings"] = {
                "risk": [],
                "ruin": [],
                "win": ["speed"],
                "recommendations": ["Proceed anyway."],
            }
        proposed = propose_v3_layer(packet, layer=layer, artifact=artifact, now=NOW)
        packet = lock_v3_layer(proposed, layer=layer, lock_assertion=_lock_assertion(proposed), now=NOW)

    with pytest.raises(ValueError, match="unresolved ruin"):
        finalize_v3_orchestration(packet, now=NOW)


def test_abandon_emits_abandoned_packet_without_global_invalidation() -> None:
    packet = start_v3_orchestration(goal="Goal", scope="Scope", now=NOW)
    abandoned = abandon_v3_orchestration(packet, reason="Frame was wrong.", now=NOW)

    assert abandoned["status"] == "abandoned"
    assert abandoned["abandon_reason"] == "Frame was wrong."
    assert abandoned["lineage"][-1]["event"] == "abandon"
    assert inspect_v3_orchestration(packet, now=NOW)["status"] == "active"
