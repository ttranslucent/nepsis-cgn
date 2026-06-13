from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import subprocess
from uuid import uuid4

import pytest

from nepsis_cgn.api.operator_packet import (
    _read_rationale_segment,
    abandon_packet,
    commit_iteration,
    lock_frame,
    lock_report,
    run_report,
    set_threshold_decision,
    start_operator_packet,
)


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


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_PROPOSAL_SECRET = "unit-test-proposal-receipt-secret"


def _receipt(
    packet: dict[str, object],
    *,
    target: str,
    model: str = "gpt-4.1-mini",
    proposed_text: str,
    receipt_id: str | None = None,
    loop_id: str | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_id": "nepsis.operator_model_proposal_receipt",
        "schema_version": "1.0.0",
        "receipt_id": receipt_id or str(uuid4()),
        "issued_at": "2026-06-12T00:00:00.000Z",
        "route": "/api/operator/model",
        "mode": "suggest_field",
        "target": target,
        "model": model,
        "loop_id": loop_id or str(packet["loop_id"]),
        "proposed_value_hash": _h(proposed_text),
    }
    signed = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body["signature"] = {
        "algorithm": "hmac-sha256",
        "key_id": "default",
        "signature": hmac.new(_PROPOSAL_SECRET.encode("utf-8"), signed, hashlib.sha256).hexdigest(),
        "signed_at": "2026-06-12T00:00:00.000Z",
    }
    return body


def _node_receipt(
    packet: dict[str, object],
    *,
    target: str,
    model: str = "gpt-4.1-mini",
    proposed_text: str,
) -> dict[str, object]:
    if shutil.which("node") is None:
        pytest.skip("node is required for the cross-language proposal receipt test")
    script = r"""
const crypto = require("node:crypto");

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

const input = JSON.parse(process.argv[1]);
const proposedValueHash = crypto.createHash("sha256").update(input.proposedText, "utf8").digest("hex");
const issuedAt = "2026-06-12T00:00:00.000Z";
const body = {
  schema_id: "nepsis.operator_model_proposal_receipt",
  schema_version: "1.0.0",
  receipt_id: "node-cross-language-receipt",
  issued_at: issuedAt,
  route: "/api/operator/model",
  mode: "suggest_field",
  target: input.target,
  model: input.model,
  loop_id: input.loopId,
  proposed_value_hash: proposedValueHash,
};
const signature = crypto.createHmac("sha256", input.secret).update(canonicalJson(body), "utf8").digest("hex");
console.log(JSON.stringify({
  ...body,
  signature: {
    algorithm: "hmac-sha256",
    key_id: "default",
    signature,
    signed_at: issuedAt,
  },
}));
"""
    result = subprocess.run(
        [
            "node",
            "-e",
            script,
            json.dumps(
                {
                    "loopId": packet["loop_id"],
                    "target": target,
                    "model": model,
                    "proposedText": proposed_text,
                    "secret": _PROPOSAL_SECRET,
                }
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    parsed = json.loads(result.stdout)
    assert isinstance(parsed, dict)
    return parsed


def _hard_text(frame: dict[str, object]) -> str:
    return "\n".join(str(item) for item in frame["constraints_hard"])


def test_stateless_operator_packet_valid_flow_commits_and_cycles() -> None:
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
    report_locked = lock_report(packet=reported)
    threshold = set_threshold_decision(
        packet=report_locked,
        decision="hold",
        hold_reason="Collect one additional discriminator before recommendation.",
    )
    committed = commit_iteration(
        packet=threshold,
        carry_forward_frame={
            "text": "Continue escalation assessment after the next discriminator.",
            "rationale_for_change": "Carry forward held threshold decision.",
        },
    )

    assert committed["schema_id"] == "nepsis.operator_packet"
    assert committed["schema_version"] == "2.1.0"
    assert committed["integrity"]["seal_version"] == "hmac-sha256:v1"
    assert committed["integrity"]["seal"]
    assert committed["phase"] == "frame_draft"
    assert committed["legal_next_tools"] == ["start_operator_packet", "lock_frame", "abandon_packet"]
    assert committed["audit_trace"] == []
    assert committed["last_commit_packet"]["schema_id"] == "nepsis.operator_audit_packet"
    assert committed["last_commit_packet"]["phase_events"] == [
        "LOCK_FRAME",
        "RUN_REPORT",
        "LOCK_REPORT",
        "SET_THRESHOLD_DECISION",
        "COMMIT_ITERATION",
    ]
    assert committed["frame"]["text"].startswith("Continue escalation")


def test_stateless_operator_packet_rejects_report_before_frame_lock() -> None:
    packet = start_operator_packet()

    result = run_report(
        packet=packet,
        report_text="obs: critical signal present",
        sign={"critical_signal": True, "policy_violation": False},
    )

    assert result["schema_id"] == "nepsis.phase_rejection"
    assert result["attempted_tool"] == "run_report"
    assert result["current_phase"] == "frame_draft"
    assert result["legal_next_tools"] == ["start_operator_packet", "lock_frame", "abandon_packet"]


def test_stateless_operator_packet_rejects_commit_before_threshold() -> None:
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
    report_locked = lock_report(packet=reported)

    result = commit_iteration(packet=report_locked)

    assert result["schema_id"] == "nepsis.phase_rejection"
    assert result["attempted_tool"] == "commit_iteration"
    assert result["current_phase"] == "report_locked"
    assert result["failed_precondition"] == "threshold_decision_required"


def test_stateless_operator_packet_rejects_commit_when_trace_does_not_prove_gates() -> None:
    packet = start_operator_packet()
    packet["phase"] = "threshold_set"
    packet["audit_trace"] = []

    result = commit_iteration(packet=packet)

    assert result["schema_id"] == "nepsis.phase_rejection"
    assert result["attempted_tool"] == "commit_iteration"
    assert result["current_phase"] == "threshold_set"
    assert result["failed_precondition"] == "audit_trace_required"
    assert result["missing"] == ["LOCK_FRAME", "RUN_REPORT", "LOCK_REPORT", "SET_THRESHOLD_DECISION"]


def test_serialized_operator_packet_continues_without_server_memory() -> None:
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    restored = json.loads(json.dumps(locked))

    reported = run_report(
        packet=restored,
        report_text="obs: critical signal present\nobs: no policy violation",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation=_report_interpretation(),
    )

    assert reported["schema_id"] == "nepsis.operator_packet"
    assert reported["phase"] == "report_evaluated"
    assert [entry["event"] for entry in reported["audit_trace"]] == ["LOCK_FRAME", "RUN_REPORT"]


def test_stateless_operator_packet_seals_output_and_accepts_valid_sealed_flow(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-packet-seal-secret")
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

    assert packet["integrity"]["seal_version"] == "hmac-sha256:v1"
    assert locked["integrity"]["counter"] == 1
    assert reported["integrity"]["counter"] == 2
    assert reported["schema_id"] == "nepsis.operator_packet"
    assert reported["phase"] == "report_evaluated"


def test_stateless_operator_packet_rejects_tampered_seal(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-packet-seal-secret")
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    locked["phase"] = "threshold_set"

    with pytest.raises(ValueError, match="integrity"):
        run_report(
            packet=locked,
            report_text="obs: critical signal present",
            sign={"critical_signal": True, "policy_violation": False},
        )


def test_stateless_operator_packet_rejects_trace_over_configured_cap(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", "unit-test-packet-seal-secret")
    monkeypatch.setenv("NEPSIS_OPERATOR_PACKET_MAX_TRACE_EVENTS", "1")
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

    with pytest.raises(ValueError, match="audit_trace"):
        lock_report(packet=reported)


def test_operator_packet_requires_configured_seal_secret_in_operator_mode(monkeypatch) -> None:
    monkeypatch.delenv("NEPSIS_OPERATOR_PACKET_SEAL_SECRET", raising=False)
    monkeypatch.setenv("NEPSIS_DEPLOYMENT_MODE", "operator")

    with pytest.raises(ValueError, match="NEPSIS_OPERATOR_PACKET_SEAL_SECRET"):
        start_operator_packet()


def test_stateless_operator_packet_preserves_hash_checked_assist_dispositions(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    hard_text = _hard_text(frame)
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=frame,
        assist_acceptances=[
            {
                "target": "frame.constraints_hard",
                "source": "model_suggestion",
                "model": "gpt-4.1-mini",
                "disposition": "accepted",
                "proposed_value_hash": _h(hard_text),
                "final_value_hash": _h(hard_text),
                "proposal_receipt": _receipt(packet, target="frame.constraints_hard", proposed_text=hard_text),
                "summary": "Preserved RED-before-BLUE sequencing.",
            }
        ],
    )

    traced = locked["audit_trace"][-1]["arguments"]["assist_acceptances"]
    assert locked["phase"] == "frame_locked"
    assert traced[0]["target"] == "frame.constraints_hard"
    assert traced[0]["disposition"] == "accepted"
    assert traced[0]["final_value_hash"] == _h(hard_text)
    assert locked["integrity"]["seal"]


def test_assist_disposition_requires_model_proposal_receipt(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    hard_text = _hard_text(frame)

    with pytest.raises(ValueError, match="proposal_receipt is required"):
        lock_frame(
            packet=packet,
            family="safety",
            frame=frame,
            assist_acceptances=[
                {
                    "target": "frame.constraints_hard",
                    "source": "model_suggestion",
                    "model": "gpt-4.1-mini",
                    "disposition": "accepted",
                    "proposed_value_hash": _h(hard_text),
                    "final_value_hash": _h(hard_text),
                    "summary": "Preserved RED-before-BLUE sequencing.",
                }
            ],
        )


def test_assist_disposition_rejects_proposal_receipt_hash_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    hard_text = _hard_text(frame)
    receipt = _receipt(packet, target="frame.constraints_hard", proposed_text="different model text")

    with pytest.raises(ValueError, match="proposal_receipt proposed_value_hash mismatch"):
        lock_frame(
            packet=packet,
            family="safety",
            frame=frame,
            assist_acceptances=[
                {
                    "target": "frame.constraints_hard",
                    "source": "model_suggestion",
                    "model": "gpt-4.1-mini",
                    "disposition": "accepted",
                    "proposed_value_hash": _h(hard_text),
                    "final_value_hash": _h(hard_text),
                    "proposal_receipt": receipt,
                    "summary": "Tampered proposal hash.",
                }
            ],
        )


def test_assist_disposition_rejects_proposal_receipt_from_other_loop(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    hard_text = _hard_text(frame)
    receipt = _receipt(packet, target="frame.constraints_hard", proposed_text=hard_text, loop_id="other-loop")

    with pytest.raises(ValueError, match="proposal_receipt loop_id mismatch"):
        lock_frame(
            packet=packet,
            family="safety",
            frame=frame,
            assist_acceptances=[
                {
                    "target": "frame.constraints_hard",
                    "source": "model_suggestion",
                    "model": "gpt-4.1-mini",
                    "disposition": "accepted",
                    "proposed_value_hash": _h(hard_text),
                    "final_value_hash": _h(hard_text),
                    "proposal_receipt": receipt,
                    "summary": "Wrong loop.",
                }
            ],
        )


def test_node_signed_proposal_receipt_verifies_in_python(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    hard_text = _hard_text(frame)
    receipt = _node_receipt(packet, target="frame.constraints_hard", proposed_text=hard_text)

    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=frame,
        assist_acceptances=[
            {
                "target": "frame.constraints_hard",
                "source": "model_suggestion",
                "model": "gpt-4.1-mini",
                "disposition": "accepted",
                "proposed_value_hash": _h(hard_text),
                "final_value_hash": _h(hard_text),
                "proposal_receipt": receipt,
                "summary": "Node route receipt verified by Python.",
            }
        ],
    )

    traced = locked["audit_trace"][-1]["arguments"]["assist_acceptances"][0]
    assert traced["proposal_receipt"]["receipt_id"] == "node-cross-language-receipt"
    assert traced["proposal_receipt"]["issued_at"].endswith("Z")


def test_assist_disposition_rejects_final_hash_mismatch(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    proposed_text = "not the field"

    with pytest.raises(ValueError, match="final_value_hash mismatch"):
        lock_frame(
            packet=packet,
            family="safety",
            frame=frame,
            assist_acceptances=[
                {
                    "target": "frame.constraints_hard",
                    "model": "gpt-4.1-mini",
                    "disposition": "accepted",
                    "proposed_value_hash": _h(proposed_text),
                    "final_value_hash": _h(proposed_text),
                    "proposal_receipt": _receipt(
                        packet,
                        target="frame.constraints_hard",
                        proposed_text=proposed_text,
                    ),
                    "summary": "False claim.",
                }
            ],
        )


def test_assist_disposition_rejects_accepted_when_hashes_diverge(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    proposed_text = "original suggestion"

    with pytest.raises(ValueError, match="use disposition=edited"):
        lock_frame(
            packet=packet,
            family="safety",
            frame=frame,
            assist_acceptances=[
                {
                    "target": "frame.constraints_hard",
                    "model": "gpt-4.1-mini",
                    "disposition": "accepted",
                    "proposed_value_hash": _h(proposed_text),
                    "final_value_hash": _h(_hard_text(frame)),
                    "proposal_receipt": _receipt(
                        packet,
                        target="frame.constraints_hard",
                        proposed_text=proposed_text,
                    ),
                    "summary": "Edited but labeled accepted.",
                }
            ],
        )


def test_assist_disposition_rejects_overflow_instead_of_truncating() -> None:
    packet = start_operator_packet()
    frame = _operator_frame()
    too_many = [
        {
            "target": "frame.text",
            "disposition": "rejected",
            "proposed_value_hash": _h(str(i)),
            "summary": str(i),
        }
        for i in range(17)
    ]

    with pytest.raises(ValueError, match="exceeds"):
        lock_frame(packet=packet, family="safety", frame=frame, assist_acceptances=too_many)


def test_assist_disposition_resolves_rationale_segments(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    red = _read_rationale_segment(frame["rationale_for_change"], "Red channel")
    proposed_text = "avoid missing harm"

    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=frame,
        assist_acceptances=[
                {
                    "target": "frame.red_definition",
                    "model": "gpt-4.1-mini",
                    "disposition": "edited",
                    "proposed_value_hash": _h(proposed_text),
                    "final_value_hash": _h(red),
                    "proposal_receipt": _receipt(
                        packet,
                        target="frame.red_definition",
                        proposed_text=proposed_text,
                    ),
                    "summary": "Tightened RED definition.",
                }
            ],
    )

    assert locked["audit_trace"][-1]["arguments"]["assist_acceptances"][0]["final_value_hash"] == _h(red)


def test_assist_disposition_rejects_target_outside_transition_scope(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    proposed_text = "collect one more discriminator"

    with pytest.raises(ValueError, match="not part of this transition"):
        lock_frame(
            packet=packet,
            family="safety",
            frame=frame,
            assist_acceptances=[
                {
                    "target": "threshold.hold_reason",
                    "model": "gpt-4.1-mini",
                    "disposition": "accepted",
                    "proposed_value_hash": _h(proposed_text),
                    "final_value_hash": _h(proposed_text),
                    "proposal_receipt": _receipt(
                        packet,
                        target="threshold.hold_reason",
                        proposed_text=proposed_text,
                    ),
                    "summary": "Wrong transition.",
                }
            ],
        )


def test_assist_disposition_records_rejected_without_final_hash(monkeypatch) -> None:
    monkeypatch.setenv("NEPSIS_OPERATOR_PROPOSAL_RECEIPT_SECRET", _PROPOSAL_SECRET)
    packet = start_operator_packet()
    frame = _operator_frame()
    proposed_text = "carry this forward later"

    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=frame,
        assist_acceptances=[
            {
                "target": "next_frame.text",
                "model": "gpt-4.1-mini",
                "disposition": "rejected",
                "proposed_value_hash": _h(proposed_text),
                "proposal_receipt": _receipt(packet, target="next_frame.text", proposed_text=proposed_text),
                "summary": "Declined carry-forward suggestion.",
            }
        ],
    )

    traced = locked["audit_trace"][-1]["arguments"]["assist_acceptances"][0]
    assert traced["target"] == "next_frame.text"
    assert traced["disposition"] == "rejected"
    assert traced["final_value_hash"] == ""


def test_assist_rationale_segment_vectors_are_exact_case_and_pipe_delimited() -> None:
    rationale = "Red channel: avoid harm | Blue channel: move carefully | Uncertainty: report quality"

    assert _read_rationale_segment(rationale, "Red channel") == "avoid harm"
    assert _read_rationale_segment(rationale, "Blue channel") == "move carefully"
    assert _read_rationale_segment(rationale, "Uncertainty") == "report quality"
    assert _read_rationale_segment("red channel: avoid harm | Blue channel: x", "Red channel") == ""
    assert _read_rationale_segment("Red channel: avoid | embedded pipe | Blue channel: x", "Red channel") == "avoid"
    assert _read_rationale_segment("Red channel: avoid harm", "Uncertainty") == ""


def test_stateless_operator_packet_abandon_returns_noncommitted_fragment() -> None:
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame=_operator_frame(),
        governance_costs={"c_fp": 1, "c_fn": 9},
    )

    abandoned = abandon_packet(packet=locked, reason="Frame was too broad.")

    assert abandoned["schema_id"] == "nepsis.operator_packet"
    assert abandoned["phase"] == "frame_draft"
    assert abandoned["audit_trace"] == []
    assert abandoned["last_abandoned_packet"]["schema_id"] == "nepsis.operator_abandoned_loop"
    assert abandoned["last_abandoned_packet"]["reason"] == "Frame was too broad."
