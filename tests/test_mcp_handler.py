from __future__ import annotations

import hashlib
import json
import logging

import pytest

from nepsis_cgn.api.operator_packet import lock_frame, lock_report, run_report, start_operator_packet
from nepsis_cgn.mcp.handler import handle_mcp_request
from nepsis_cgn.provenance import PacketProvenanceStore

TEST_V3_SEAL_SECRET = "unit-test-v3-packet-seal-secret"


@pytest.fixture(autouse=True)
def _configured_v3_packet_seal_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEPSIS_V3_PACKET_SEAL_SECRET", TEST_V3_SEAL_SECRET)


def _tool_payload(response: dict[str, object]) -> dict[str, object]:
    result = response["result"]
    assert isinstance(result, dict)
    content = result["content"]
    assert isinstance(content, list)
    first = content[0]
    assert isinstance(first, dict)
    text = first["text"]
    assert isinstance(text, str)
    return json.loads(text)


def _operator_frame() -> dict[str, object]:
    return {
        "text": "Decide whether to escalate response.",
        "objective_type": "decide",
        "domain": "safety",
        "time_horizon": "short",
        "rationale_for_change": (
            "Red channel: avoid missing a catastrophic incident | "
            "Blue channel: protect users while minimizing disruption | "
            "Uncertainty: signal quality from the first report"
        ),
        "constraints_hard": ["No policy breach"],
        "constraints_soft": ["Minimize disruption"],
    }


def _report_interpretation() -> dict[str, object]:
    return {
        "report_text": "obs: critical signal present\nobs: no policy violation",
        "evidence_count": 2,
        "report_synced": True,
        "contradictions_status": "none_identified",
        "contradictions_note": "",
        "contradiction_density": 0.0,
    }


def _v3_field(state: str = "present", items: list[str] | None = None, rationale: str = "Reviewed.") -> dict[str, object]:
    return {"status": state, "items": items if items is not None else ["captured"], "rationale": rationale}


def _v3_intake_artifact() -> dict[str, object]:
    return {
        "layer": "intake",
        "summary": "intake layer artifact.",
        "goal_scope": _v3_field(items=["goal", "scope"]),
        "red_triggers": _v3_field("unknown", [], "Not assessed until red layer."),
        "blue_opportunity_space": _v3_field("unknown", [], "Not assessed until blue layer."),
        "constraints": _v3_field(items=["No hidden memory."]),
        "manifold_match_mismatch": _v3_field("not_applicable", [], "Not assessed until manifold layer."),
        "still_blockers": _v3_field("unknown", [], "Not assessed until STILL layer."),
        "unresolved_questions": _v3_field("none_found", [], "No unresolved intake question."),
        "audit_notes": _v3_field(items=["packet visible"]),
        "proposed_status": _v3_field(items=["ready"]),
        "lock_eligibility": _v3_field(items=["eligible"]),
        "layer_findings": {"risk": [], "ruin": [], "win": [], "recommendations": []},
        "intake": {
            "goal": "Build V3 packet kernel.",
            "scope": "MCP stateless orchestration.",
            "assumptions": ["Host model drafts artifacts."],
            "unresolved_questions": ["None for first pass."],
        },
    }


def _report_locked_packet() -> dict[str, object]:
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    reported = run_report(
        packet=locked,
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_report_interpretation(),
    )
    return lock_report(packet=reported)


def test_remote_tool_call_without_capability_token_rejects(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", raising=False)

    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "start_operator_packet", "arguments": {}},
        },
        headers={},
        require_capability_token=True,
        server_name="nepsis-cgn",
    )

    assert response is not None
    assert response["error"]["code"] == -32001
    assert "capability" in response["error"]["message"].lower()


def test_initialize_echoes_supported_client_protocol_version() -> None:
    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        headers={},
        require_capability_token=True,
        server_name="nepsis-cgn",
    )

    assert response is not None
    assert response["result"]["protocolVersion"] == "2024-11-05"


def test_tools_list_advertises_auth_requirement_and_run_mvp_aliases() -> None:
    response = handle_mcp_request(
        {"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}},
        headers={},
        require_capability_token=True,
        server_name="nepsis-cgn",
    )

    assert response is not None
    tools = response["result"]["tools"]
    for tool in tools:
        assert "capability token" in tool["description"].lower()
        assert tool["_meta"]["nepsis.requiresCapabilityToken"] is True

    run_mvp = next(tool for tool in tools if tool["name"] == "run_mvp")
    assert {"case_id", "case", "input_text", "inputText"} <= set(run_mvp["inputSchema"]["properties"])
    tool_names = {tool["name"] for tool in tools}
    assert {
        "start_v3_orchestration",
        "inspect_v3_orchestration",
        "propose_v3_layer",
        "lock_v3_layer",
        "finalize_v3_orchestration",
        "abandon_v3_orchestration",
    } <= tool_names


def test_capability_token_logs_metadata_without_raw_token(monkeypatch, caplog) -> None:
    token = "capability-test-token-for-log-check"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    monkeypatch.setenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", f"log-token:{digest}")
    caplog.set_level(logging.INFO, logger="nepsis_cgn.mcp.handler")

    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "start_operator_packet", "arguments": {}},
        },
        headers={"Authorization": f"Bearer {token}"},
        require_capability_token=True,
        server_name="nepsis-cgn",
    )

    assert response is not None
    assert _tool_payload(response)["schema_id"] == "nepsis.operator_packet"
    assert token not in caplog.text
    assert "Authorization" not in caplog.text
    assert '"token_id": "log-token"' in caplog.text
    assert '"packet_hash": "' in caplog.text


def test_mcp_tool_call_records_hash_only_provenance_without_raw_token(tmp_path, monkeypatch) -> None:
    token = "capability-test-token-for-provenance-check"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    ledger_path = tmp_path / "packet_provenance.jsonl"
    monkeypatch.setenv("NEPSIS_MCP_CAPABILITY_TOKEN_HASHES", f"prov-token:{digest}")
    monkeypatch.setenv("NEPSIS_PACKET_PROVENANCE_PATH", str(ledger_path))

    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "start_operator_packet", "arguments": {}},
        },
        headers={"Authorization": f"Bearer {token}"},
        require_capability_token=True,
        server_name="nepsis-cgn",
        request_id="mcp-request-1",
    )

    assert response is not None
    assert _tool_payload(response)["schema_id"] == "nepsis.operator_packet"
    records = PacketProvenanceStore(ledger_path).records_for_request("mcp-request-1")
    assert len(records) == 1
    assert records[0]["source"] == "mcp_tool_call"
    assert records[0]["retention"]["mode"] == "hash_only"
    assert "payload" not in records[0]
    assert token not in ledger_path.read_text(encoding="utf-8")


def test_get_session_state_rejects_non_object_packet_argument() -> None:
    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_session_state", "arguments": {"packet": "not-a-packet"}},
        },
        require_capability_token=False,
        server_name="nepsis-cgn-local",
    )

    assert response is not None
    assert response["error"]["code"] == -32602
    assert "packet" in response["error"]["message"]


def test_get_session_state_rejects_tampered_operator_packet(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-packet-seal-secret")
    packet = start_operator_packet()
    packet["phase"] = "threshold_set"

    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "get_session_state", "arguments": {"packet": packet}},
        },
        require_capability_token=False,
        server_name="nepsis-cgn-local",
    )

    assert response is not None
    assert response["error"]["code"] == -32602
    assert "integrity" in response["error"]["message"]


def test_set_threshold_decision_rejects_non_string_hold_reason() -> None:
    packet = _report_locked_packet()

    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "set_threshold_decision",
                "arguments": {
                    "packet": packet,
                    "decision": "hold",
                    "hold_reason": {"not": "a string"},
                },
            },
        },
        require_capability_token=False,
        server_name="nepsis-cgn-local",
    )

    assert response is not None
    assert response["error"]["code"] == -32602
    assert "hold_reason" in response["error"]["message"]


def test_v3_mcp_tools_execute_packet_in_packet_out() -> None:
    started_response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/call",
            "params": {
                "name": "start_v3_orchestration",
                "arguments": {"goal": "Build V3 packet kernel.", "scope": "MCP stateless orchestration."},
            },
        },
        require_capability_token=False,
        server_name="nepsis-cgn-local",
    )
    assert started_response is not None
    started = _tool_payload(started_response)
    assert started["schema"] == "nepsis.v3_orchestration_packet@0.1.0"
    assert started["current_layer"] == "intake"

    proposed_response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {
                "name": "propose_v3_layer",
                "arguments": {
                    "packet": started,
                    "layer": "intake",
                    "artifact": _v3_intake_artifact(),
                    "draft_metadata": {"host": "codex", "model_name": "gpt-5"},
                },
            },
        },
        require_capability_token=False,
        server_name="nepsis-cgn-local",
    )
    assert proposed_response is not None
    proposed = _tool_payload(proposed_response)
    proposal_hash = proposed["current_proposal"]["artifact_hash"]

    locked_response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {
                "name": "lock_v3_layer",
                "arguments": {
                    "packet": proposed,
                    "layer": "intake",
                    "lock_assertion": {
                        "asserted": True,
                        "assertion_text": "I explicitly lock the intake layer.",
                        "proposal_hash": proposal_hash,
                        "lock_nonce": "unit-test-nonce",
                    },
                },
            },
        },
        require_capability_token=False,
        server_name="nepsis-cgn-local",
    )
    assert locked_response is not None
    locked = _tool_payload(locked_response)

    assert locked["current_layer"] == "red"
    assert locked["locked_layers"]["intake"]["artifact_hash"] == proposal_hash


def test_v3_mcp_rejects_raw_token_like_draft_metadata() -> None:
    started_response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 30,
            "method": "tools/call",
            "params": {
                "name": "start_v3_orchestration",
                "arguments": {"goal": "Build V3 packet kernel.", "scope": "MCP stateless orchestration."},
            },
        },
        require_capability_token=False,
        server_name="nepsis-cgn-local",
    )
    packet = _tool_payload(started_response)

    rejected = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {
                "name": "propose_v3_layer",
                "arguments": {
                    "packet": packet,
                    "layer": "intake",
                    "artifact": _v3_intake_artifact(),
                    "draft_metadata": {"capability_token": "raw-secret-token"},
                },
            },
        },
        require_capability_token=False,
        server_name="nepsis-cgn-local",
    )

    assert rejected is not None
    assert rejected["error"]["code"] == -32602
    assert "raw secret" in rejected["error"]["message"]


def test_abandon_packet_rejects_non_string_reason() -> None:
    packet = start_operator_packet()

    response = handle_mcp_request(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "abandon_packet",
                "arguments": {"packet": packet, "reason": {"not": "a string"}},
            },
        },
        require_capability_token=False,
        server_name="nepsis-cgn-local",
    )

    assert response is not None
    assert response["error"]["code"] == -32602
    assert "reason" in response["error"]["message"]
