from __future__ import annotations

import json

import pytest

from nepsis_cgn.provenance import (
    HmacSha256PacketSigner,
    IntegrityConflict,
    PacketProvenanceStore,
    UnsignedPacketSigner,
    build_packet_record,
    canonical_json_bytes,
    record_packet_observation,
    sha256_payload,
)


def test_payload_hash_is_canonical_and_changes_with_payload() -> None:
    left = {"b": 2, "a": {"z": True, "y": [3, 1]}}
    right = {"a": {"y": [3, 1], "z": True}, "b": 2}

    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert sha256_payload(left) == sha256_payload(right)
    assert sha256_payload(left) != sha256_payload({"a": {"y": [3, 2], "z": True}, "b": 2})


def test_hmac_signer_verifies_records_and_unsigned_mode_marks_unsigned() -> None:
    payload = {"schema_id": "nepsis.test", "packet_id": "packet-1"}
    unsigned = build_packet_record(
        packet=payload,
        source="unit_test",
        retention_mode="retained",
        signer=UnsignedPacketSigner(),
    )
    signed = build_packet_record(
        packet=payload,
        source="unit_test",
        retention_mode="retained",
        signer=HmacSha256PacketSigner(secret="test-secret", key_id="unit-key"),
    )

    assert unsigned["signature"]["algorithm"] == "unsigned"
    assert unsigned["integrity"]["payload_hash_verified"] is True
    assert signed["signature"]["algorithm"] == "hmac-sha256"
    assert signed["signature"]["key_id"] == "unit-key"
    assert HmacSha256PacketSigner(secret="test-secret", key_id="unit-key").verify(signed)

    tampered = json.loads(json.dumps(signed))
    tampered["payload"]["packet_id"] = "packet-2"
    assert not HmacSha256PacketSigner(secret="test-secret", key_id="unit-key").verify(tampered)


def test_jsonl_store_is_append_only_idempotent_and_builds_lineage_graph(tmp_path) -> None:
    store = PacketProvenanceStore(tmp_path / "packet_provenance.jsonl")
    first_packet = {
        "schema_id": "nepsis.iteration_packet",
        "meta": {"packet_id": "packet-1", "session_id": "session-1", "parent_packet_id": None},
    }
    second_packet = {
        "schema_id": "nepsis.iteration_packet",
        "meta": {"packet_id": "packet-2", "session_id": "session-1", "parent_packet_id": "packet-1"},
    }
    first = build_packet_record(
        packet=first_packet,
        source="runtime_iteration",
        retention_mode="retained",
        request_id="request-1",
        method="POST",
        path="/v1/sessions/session-1/step",
    )
    second = build_packet_record(
        packet=second_packet,
        source="runtime_iteration",
        retention_mode="retained",
        request_id="request-1",
        method="POST",
        path="/v1/sessions/session-1/step",
    )

    assert store.append(first) == "appended"
    assert store.append(first) == "duplicate"
    assert store.append(second) == "appended"

    graph = store.graph_for_session("session-1")
    assert [node["packet_id"] for node in graph["nodes"]] == ["packet-1", "packet-2"]
    assert graph["edges"] == [{"parent_packet_id": "packet-1", "child_packet_id": "packet-2"}]

    conflict = build_packet_record(
        packet={**first_packet, "changed": True},
        source="runtime_iteration",
        retention_mode="retained",
        request_id="request-2",
    )
    with pytest.raises(IntegrityConflict):
        store.append(conflict)


def test_hash_only_records_never_retain_payload(tmp_path) -> None:
    store = PacketProvenanceStore(tmp_path / "packet_provenance.jsonl")
    record = build_packet_record(
        packet={"schema_id": "nepsis.operator_packet", "packet_id": "packet-1"},
        source="stateless_operator_packet",
        retention_mode="hash_only",
        request_id="request-1",
    )

    assert record["retention"]["mode"] == "hash_only"
    assert record["retention"]["payload_retained"] is False
    assert "payload" not in record

    store.append(record)
    loaded = store.records()[0]
    assert "payload" not in loaded


def test_recording_can_be_disabled_with_env(tmp_path, monkeypatch) -> None:
    ledger_path = tmp_path / "packet_provenance.jsonl"
    monkeypatch.setenv("NEPSIS_PACKET_PROVENANCE_PATH", str(ledger_path))
    monkeypatch.setenv("NEPSIS_PACKET_PROVENANCE_ENABLED", "false")

    result = record_packet_observation(
        packet={"schema_id": "nepsis.test", "packet_id": "packet-disabled"},
        source="unit_test",
        retention_mode="retained",
    )

    assert result is None
    assert not ledger_path.exists()
