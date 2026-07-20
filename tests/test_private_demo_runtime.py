from __future__ import annotations

from fastapi.testclient import TestClient

from nepsis_cgn.api import asgi
from nepsis_cgn.api.private_demo import build_private_demo_runtime_packet


def test_asgi_private_demo_runtime_returns_operator_audit_packet(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-packet-seal-secret")

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/private-demo",
        headers={"Authorization": "Bearer test-token"},
        json={
            "case_id": "jailing",
            "prompt": (
                "No PHI. Source token is JINGALL and the candidate answer collapses "
                "to JAILING; preserve the mismatch and show the packet audit."
            ),
            "no_phi_acknowledged": True,
            "thread_id": "00000000-0000-4000-8000-000000000001",
            "user_id": "00000000-0000-4000-8000-000000000002",
        },
    )

    assert response.status_code == 200
    packet = response.json()
    assert packet["schema_id"] == "nepsis.private_demo_runtime_packet"
    assert packet["runtime"] == "nepsis-cgn.operator_packet"
    assert packet["mode"] == "external-private-runtime"
    assert packet["case_id"] == "jailing"
    assert packet["thread_id"] == "00000000-0000-4000-8000-000000000001"
    assert packet["user_id"] == "00000000-0000-4000-8000-000000000002"
    assert packet["no_phi_acknowledged"] is True
    assert "RED before BLUE" in packet["summary"]

    operator_packet = packet["operator_packet"]
    assert operator_packet["schema_id"] == "nepsis.operator_packet"
    assert operator_packet["phase"] == "threshold_set"
    assert operator_packet["latest_audit"]["frame"]["status"] == "PASS"
    assert operator_packet["latest_audit"]["interpretation"]["status"] == "PASS"
    assert operator_packet["latest_audit"]["threshold"]["status"] == "PASS"

    assert [entry["event"] for entry in packet["audit_trace"]] == [
        "LOCK_FRAME",
        "RUN_REPORT",
        "LOCK_REPORT",
        "SET_THRESHOLD_DECISION",
    ]


def test_private_demo_uncertain_assessment_holds_without_claiming_direct_red(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "NEPSIS_OPERATOR_PACKET_SEAL_SECRET",
        "unit-test-packet-seal-secret",
    )

    packet = build_private_demo_runtime_packet(
        {
            "prompt": "No PHI. Consider a bounded ambiguous scenario without a specified hazard.",
            "no_phi_acknowledged": True,
        }
    )

    assert packet["case_reasoning_compiler"]["current_red_status"] == "uncertain"
    threshold = packet["latest_audit"]["threshold"]["packet"]
    assert threshold["red_veto_active"] is False
    assert packet["audit_trace"][-1]["arguments"]["decision"] == "hold"


def test_asgi_private_demo_runtime_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/private-demo",
        json={"prompt": "No PHI. Preserve the private demo backend boundary."},
    )

    assert response.status_code == 401


def test_asgi_private_demo_runtime_requires_no_phi_acknowledgement(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/private-demo",
        headers={"Authorization": "Bearer test-token"},
        json={"prompt": "No PHI text is not enough without the explicit acknowledgement."},
    )

    assert response.status_code == 400
    assert "no_phi_acknowledged must be true" in response.json()["detail"]


def test_asgi_private_demo_runtime_reports_missing_seal_secret_as_server_misconfiguration(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_API_ALLOW_ANON", raising=False)
    monkeypatch.delenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", raising=False)
    monkeypatch.setenv("NEPSIS_API_TOKEN", "test-token")
    monkeypatch.setenv("NODE_ENV", "production")

    client = TestClient(asgi.create_app())
    response = client.post(
        "/v1/private-demo",
        headers={"Authorization": "Bearer test-token"},
        json={
            "prompt": "No PHI. Preserve the private demo backend boundary.",
            "no_phi_acknowledged": True,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Private demo runtime is not configured."
