from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from nepsis_cgn.api import asgi
from nepsis_cgn.api.service import EngineApiService
from nepsis_cgn.provenance import PacketProvenanceStore


def test_engine_service_records_iteration_provenance_and_audit_export(tmp_path, monkeypatch) -> None:
    ledger_path = tmp_path / "packet_provenance.jsonl"
    monkeypatch.setenv("NEPSIS_PACKET_PROVENANCE_PATH", str(ledger_path))

    svc = EngineApiService()
    created = svc.create_session(family="safety")
    sid = created["session_id"]
    svc.step_session(sid, sign={"critical_signal": True})
    svc.step_session(sid, sign={"critical_signal": False})

    provenance = svc.get_packet_provenance(sid)
    assert provenance["count"] == 2
    assert provenance["graph"]["edges"] == [
        {
            "parent_packet_id": provenance["records"][0]["packet_id"],
            "child_packet_id": provenance["records"][1]["packet_id"],
        }
    ]
    assert provenance["records"][0]["retention"]["payload_retained"] is True
    assert provenance["records"][0]["payload_hash"].startswith("sha256:")
    lineage = svc.get_packet_lineage(provenance["records"][0]["packet_id"])
    assert lineage["edges"] == provenance["graph"]["edges"]

    export = svc.export_session_audit(sid)
    assert export["schema_id"] == "nepsis.audit_export"
    assert export["session"]["session_id"] == sid
    assert export["verification"]["record_count"] == 2
    assert export["verification"]["hash_failures"] == []
    assert export["verification"]["signature_failures"] == []


def test_service_provenance_reads_are_owner_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_PACKET_PROVENANCE_PATH", str(tmp_path / "packet_provenance.jsonl"))
    svc = EngineApiService()
    created = svc.create_session(family="safety", owner_id="owner@example.com")
    sid = created["session_id"]
    svc.step_session(
        sid,
        sign={"critical_signal": True},
        owner_id="owner@example.com",
        request_context={"request_id": "owner-request-1", "method": "POST", "path": "/v1/sessions/test/step"},
    )

    assert svc.get_packet_provenance(sid, owner_id="owner@example.com")["count"] == 1
    assert svc.get_request_provenance("owner-request-1", owner_id="owner@example.com")["count"] == 1
    with pytest.raises(PermissionError):
        svc.get_packet_provenance(sid, owner_id="other@example.com")
    with pytest.raises(PermissionError):
        svc.get_request_provenance("owner-request-1", owner_id="other@example.com")


def test_asgi_mvp_response_is_unchanged_while_request_provenance_is_recorded(tmp_path, monkeypatch) -> None:
    ledger_path = tmp_path / "packet_provenance.jsonl"
    monkeypatch.setenv("NEPSIS_PACKET_PROVENANCE_PATH", str(ledger_path))
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/mvp",
        headers={"X-Request-ID": "request-mvp-1"},
        json={"case_id": "jailing"},
    )

    payload = response.json()
    assert response.status_code == 200
    assert payload["schema_id"] == "nepsis.mvp_packet"
    assert "provenance" not in payload

    request_records = PacketProvenanceStore(ledger_path).records_for_request("request-mvp-1")
    assert len(request_records) == 1
    assert request_records[0]["source"] == "backend_mvp"
    assert request_records[0]["retention"]["payload_retained"] is True


def test_asgi_stateless_operator_packet_records_hash_only(tmp_path, monkeypatch) -> None:
    ledger_path = tmp_path / "packet_provenance.jsonl"
    monkeypatch.setenv("NEPSIS_PACKET_PROVENANCE_PATH", str(ledger_path))
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/operator-packet/start",
        headers={"X-Request-ID": "request-operator-packet-1"},
        json={},
    )

    assert response.status_code == 200
    assert response.json()["schema_id"] == "nepsis.operator_packet"
    request_records = PacketProvenanceStore(ledger_path).records_for_request("request-operator-packet-1")
    assert len(request_records) == 1
    assert request_records[0]["source"] == "stateless_operator_packet"
    assert request_records[0]["retention"]["mode"] == "hash_only"
    assert "payload" not in request_records[0]


def test_asgi_provenance_request_reconstruction_endpoint(tmp_path, monkeypatch) -> None:
    ledger_path = tmp_path / "packet_provenance.jsonl"
    monkeypatch.setenv("NEPSIS_PACKET_PROVENANCE_PATH", str(ledger_path))
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")
    monkeypatch.setattr(asgi, "API", EngineApiService())

    client = TestClient(asgi.create_app())
    session = client.post("/v1/sessions", json={"family": "safety"}).json()
    sid = session["session_id"]
    step = client.post(
        f"/v1/sessions/{sid}/step",
        headers={"X-Request-ID": "request-step-1"},
        json={"sign": {"critical_signal": True}},
    )
    reconstructed = client.get("/v1/provenance/requests/request-step-1")
    scoped = client.get(f"/v1/sessions/{sid}/provenance")
    exported = client.get(f"/v1/sessions/{sid}/audit-export")

    assert step.status_code == 200
    assert reconstructed.status_code == 200
    assert reconstructed.json()["request_id"] == "request-step-1"
    assert reconstructed.json()["count"] == 1
    assert scoped.status_code == 200
    assert scoped.json()["count"] == 1
    assert exported.status_code == 200
    assert exported.json()["verification"]["record_count"] == 1
    assert json.loads(json.dumps(exported.json()))
