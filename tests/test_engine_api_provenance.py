from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nepsis_cgn.api import asgi
from nepsis_cgn.api.service import EngineApiService
from nepsis_cgn.provenance import PacketProvenanceStore, default_provenance_path


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


def test_vercel_default_store_path_uses_temp_runtime_root_on_read_only_checkout(
    tmp_path, monkeypatch
) -> None:
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime_tmp.mkdir()
    checkout = tmp_path / "var-task"
    checkout.mkdir()
    checkout.chmod(0o555)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TMPDIR", str(runtime_tmp))
    monkeypatch.delenv("NEPSIS_API_STORE_PATH", raising=False)
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")

    try:
        monkeypatch.chdir(checkout)
        store_path = Path(asgi._default_store_path())
        expected = runtime_tmp.resolve() / "nepsis-cgn" / "sessions" / "engine_api_sessions.db"
        assert store_path == expected

        monkeypatch.setattr(asgi, "API", EngineApiService(store_path=str(store_path)))
        response = TestClient(asgi.create_app()).post("/v1/sessions", json={"family": "safety"})

        assert response.status_code == 200
        assert store_path.exists()
        assert not (checkout / "ledger" / "sessions" / "engine_api_sessions.db").exists()
    finally:
        checkout.chmod(0o755)


def test_vercel_default_provenance_path_uses_temp_runtime_root_and_preserves_retention_modes(
    tmp_path, monkeypatch
) -> None:
    runtime_tmp = tmp_path / "runtime-tmp"
    runtime_tmp.mkdir()
    checkout = tmp_path / "var-task"
    checkout.mkdir()
    checkout.chmod(0o555)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("TMPDIR", str(runtime_tmp))
    monkeypatch.delenv("NEPSIS_PACKET_PROVENANCE_PATH", raising=False)
    monkeypatch.setenv("NEPSIS_API_ALLOW_ANON", "true")

    try:
        monkeypatch.chdir(checkout)
        ledger_path = default_provenance_path()
        expected = runtime_tmp.resolve() / "nepsis-cgn" / "sessions" / "packet_provenance.jsonl"
        assert ledger_path == expected

        client = TestClient(asgi.create_app())
        mvp = client.post(
            "/v1/mvp",
            headers={"X-Request-ID": "request-mvp-vercel-default"},
            json={"case_id": "jailing"},
        )
        operator = client.post(
            "/v1/operator-packet/start",
            headers={"X-Request-ID": "request-operator-vercel-default"},
            json={},
        )

        assert mvp.status_code == 200
        assert mvp.json()["schema_id"] == "nepsis.mvp_packet"
        assert operator.status_code == 200
        assert operator.json()["schema_id"] == "nepsis.operator_packet"

        records = PacketProvenanceStore(ledger_path).records()
        retained = [record for record in records if record["source"] == "backend_mvp"]
        hash_only = [record for record in records if record["source"] == "stateless_operator_packet"]
        assert retained and retained[0]["retention"]["payload_retained"] is True
        assert hash_only and hash_only[0]["retention"]["mode"] == "hash_only"
        assert "payload" not in hash_only[0]
        assert not (checkout / "ledger" / "sessions" / "packet_provenance.jsonl").exists()
    finally:
        checkout.chmod(0o755)
