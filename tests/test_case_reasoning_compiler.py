from __future__ import annotations

import copy

from nepsis_cgn.api import operator_packet as operator_packet_module
from nepsis_cgn.api.operator_packet import (
    lock_frame,
    lock_report,
    run_report,
    start_operator_packet,
)
from nepsis_cgn.core.case_reasoning import (
    compile_case_reasoning,
    detect_false_reassurance_tokens,
    prompt_hash,
    validate_case_reasoning,
)


def _frame() -> dict[str, object]:
    return {
        "frame_id": "frame-test",
        "text": "No PHI. Could delayed worsening after trauma represent NSTI?",
        "objective_type": "sensemake",
        "domain": "safety",
        "time_horizon": "short",
        "rationale_for_change": (
            "Red channel: missed NSTI | "
            "Blue channel: traumatic injury only after RED closure | "
            "Uncertainty: delayed worsening trajectory"
        ),
        "constraints_hard": ["No PHI.", "Preserve RED before BLUE."],
        "constraints_soft": ["Keep audit concise."],
    }


def _nsti_prompt() -> str:
    return (
        "No PHI. A1 chest wall deep infection test. Surface story: 40s male with swelling "
        "after a fall onto a metal fence 7 to 10 days prior. Key trajectory: initial pain, "
        "partial settling, then secondary worsening with increasing pain, swelling, erythema, "
        "warmth, high WBC, and elevated lactate. CT shows gas deep to the pectoral muscle. "
        "Authority pushback: radiology favors traumatic gas from rib fracture. "
        "Non-closure: no abscess, no obvious wound, rib fracture, radiology interpretation, "
        "and no shock do not close RED. Closure requires surgical exploration or a definitive "
        "alternative explaining the entire trajectory."
    )


def _model_v1_packet(source: str, *, frame_id: str) -> dict[str, object]:
    input_hash = prompt_hash(source)
    domain_red_hazard = {
        "hazard": "missed battery thermal runaway",
        "mechanism_of_harm": "delayed isolation of a progressively heating battery pack",
        "time_sensitivity": "hours",
        "closure_requirement": "temperature stabilization under observation or direct safe isolation",
    }
    closure_condition = {
        "required_to_close": "Observed cooling trend after isolation or direct technical exclusion of thermal runaway.",
        "acceptable_closure_modes": ["direct isolation", "temperature trend reversal", "definitive technical exclusion"],
        "current_closure_status": "not_satisfied",
    }
    blue_frame = {
        "name": "ordinary charging fault",
        "description": "The surface story treats the alert as a benign charger or sensor issue.",
        "supporting_evidence": ["charging fault alert", "no visible flame"],
        "unexplained_or_weakly_explained_evidence": ["progressive temperature rise", "chemical odor"],
    }
    trajectory_signal = {
        "expected_curve_under_blue_frame": "A benign charging fault should stabilize after unplugging.",
        "observed_curve": "Temperature continues rising after unplugging with chemical odor.",
        "violation": "Continued heating violates the benign charging-fault curve.",
        "interpretation": "The red hazard remains open until direct isolation or cooling trend closes it.",
    }
    authority_pushback = [
        {
            "source": "maintenance lead",
            "claim": "it is probably just a sensor issue",
            "what_it_explains": ["why the alert was initially downplayed"],
            "what_it_does_not_close": ["continued temperature rise", "chemical odor", "thermal runaway"],
            "closure_status": "non_closing",
        }
    ]
    false_reassurance_tokens = [
        {
            "token": "no visible flame",
            "why_reassuring": "no active fire is seen",
            "why_non_closing": "Thermal runaway can precede flame and still require immediate isolation.",
        }
    ]
    return {
        "schema_id": "nepsis.case_reasoning_compiler",
        "schema_version": "0.1.0",
        "compiler_source": "model_v1",
        "input_frame_id": frame_id,
        "input_prompt_hash": input_hash,
        "compiler_valid": False,
        "validation_errors": [],
        "validation_warnings": [],
        "case_id": "custom",
        "domain": "safety",
        "runtime_safety_constraints": ["No PHI or patient-identifiable data.", "Preserve source facts."],
        "surface_story": "Battery pack alert is framed as a routine charger or sensor issue.",
        "blue_frame": blue_frame,
        "red_frame": {
            "name": "battery thermal runaway",
            "description": "Progressive heating can become fire or toxic exposure if not isolated.",
            "supporting_evidence": ["progressive temperature rise", "chemical odor"],
            "unexplained_or_weakly_explained_evidence": ["no visible flame"],
        },
        "red_channel_question": "Could the battery pack be entering thermal runaway?",
        "domain_catastrophic_outcome": "Missed battery thermal runaway causing preventable fire, toxic exposure, injury, or facility damage.",
        "domain_red_hazard": domain_red_hazard,
        "mechanism_of_harm": "Delayed isolation allows heat generation to outrun the benign charger-fault frame.",
        "time_sensitivity": "hours",
        "trajectory_signal": trajectory_signal,
        "authority_pushback": authority_pushback,
        "false_reassurance_tokens": false_reassurance_tokens,
        "non_closure_evidence": [
            {
                "claim_or_observation": "no visible flame",
                "why_non_closing": "Absence of flame does not close progressive heating or chemical odor.",
            }
        ],
        "closure_condition": closure_condition,
        "current_red_status": "open",
        "closure_basis": "",
        "decision_reason": "The thermal-runaway red channel remains open because continued heating and chemical odor are not closed by a sensor-fault explanation.",
        "recommended_threshold_action": "escalate_red",
        "reasoning_quality_flags": {
            "authority_substitution_detected": True,
            "trajectory_violation_detected": True,
            "frame_tension_detected": True,
            "false_reassurance_risk_detected": True,
            "missing_closure_condition": False,
        },
        "governor": {
            "input_frame_id": frame_id,
            "input_prompt_hash": input_hash,
            "compiler_source": "model_v1",
            "validation_status": "pending",
            "zeroback": {"reset_required": False, "reason": ""},
        },
        "nodes": {
            "intake_boundary": {
                "source_facts": [source],
                "user_query": source,
                "runtime_safety_constraints": ["No PHI or patient-identifiable data.", "Preserve source facts."],
                "input_prompt_hash": input_hash,
                "privacy_boundary": "no_phi_acknowledged",
            },
            "red": {
                "domain_red_hazard": domain_red_hazard,
                "domain_catastrophic_outcome": "Missed battery thermal runaway causing preventable fire, toxic exposure, injury, or facility damage.",
                "red_channel_question": "Could the battery pack be entering thermal runaway?",
                "closure_condition": closure_condition,
            },
            "blue": {
                "surface_story": "Battery pack alert is framed as a routine charger or sensor issue.",
                "blue_frame": blue_frame,
            },
            "trajectory_spc": {
                "trajectory_signal": trajectory_signal,
                "time_sensitivity": "hours",
                "drift_signal": "continued heating after unplugging",
            },
            "authority_reassurance": {
                "authority_pushback": authority_pushback,
                "false_reassurance_tokens": false_reassurance_tokens,
                "non_closure_evidence": [
                    {
                        "claim_or_observation": "no visible flame",
                        "why_non_closing": "Absence of flame does not close progressive heating or chemical odor.",
                    }
                ],
            },
            "closure": {
                "current_red_status": "open",
                "closure_basis": "",
                "closure_condition": closure_condition,
            },
            "zeroback_reset": {
                "reset_required": False,
                "triggers": [],
                "reason": "",
            },
        },
    }


def test_deterministic_compiler_emits_subagent_nodes() -> None:
    source = _nsti_prompt()

    compiler = compile_case_reasoning(
        source,
        case_id="medical_a1_chest_wall_nsti_after_blunt_trauma",
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )

    assert compiler["governor"]["input_frame_id"] == "frame-1"
    assert compiler["governor"]["input_prompt_hash"] == prompt_hash(source)
    assert set(compiler["nodes"]) == {
        "intake_boundary",
        "red",
        "blue",
        "trajectory_spc",
        "authority_reassurance",
        "closure",
        "zeroback_reset",
    }
    assert compiler["nodes"]["red"]["domain_red_hazard"] == compiler["domain_red_hazard"]
    assert compiler["nodes"]["blue"]["surface_story"] == compiler["surface_story"]
    assert compiler["nodes"]["trajectory_spc"]["trajectory_signal"] == compiler["trajectory_signal"]
    assert compiler["nodes"]["authority_reassurance"]["false_reassurance_tokens"] == compiler["false_reassurance_tokens"]
    assert compiler["nodes"]["closure"]["current_red_status"] == compiler["current_red_status"]


def test_node_top_level_mismatch_blocks_validation() -> None:
    source = _nsti_prompt()
    compiler = compile_case_reasoning(
        source,
        case_id="medical_a1_chest_wall_nsti_after_blunt_trauma",
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )
    broken = copy.deepcopy(compiler)
    broken["nodes"]["red"]["domain_red_hazard"]["hazard"] = "runtime safety receipt"

    validation = validate_case_reasoning(
        broken,
        source_text=source,
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )

    assert validation["status"] == "BLOCK"
    assert "domain_red_hazard must match nodes.red.domain_red_hazard" in validation["errors"]


def test_missing_red_node_blocks_validation() -> None:
    source = _nsti_prompt()
    compiler = compile_case_reasoning(
        source,
        case_id="medical_a1_chest_wall_nsti_after_blunt_trauma",
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )
    broken = copy.deepcopy(compiler)
    del broken["nodes"]["red"]

    validation = validate_case_reasoning(
        broken,
        source_text=source,
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )

    assert validation["status"] == "BLOCK"
    assert "nodes.red is required" in validation["errors"]


def test_runtime_safety_cannot_pass_as_domain_hazard() -> None:
    source = _nsti_prompt()
    compiler = compile_case_reasoning(
        source,
        case_id="medical_a1_chest_wall_nsti_after_blunt_trauma",
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )
    broken = copy.deepcopy(compiler)
    broken["domain_catastrophic_outcome"] = "Preserve no-PHI boundary, source facts, and hard safety constraints."

    validation = validate_case_reasoning(
        broken,
        source_text=source,
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )

    assert validation["status"] == "BLOCK"
    assert "domain_catastrophic_outcome must describe domain harm, not runtime/process safety" in validation["errors"]


def test_generic_process_receipt_cannot_pass_as_decision_reason() -> None:
    source = _nsti_prompt()
    compiler = compile_case_reasoning(
        source,
        case_id="medical_a1_chest_wall_nsti_after_blunt_trauma",
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )
    broken = copy.deepcopy(compiler)
    broken["decision_reason"] = "Operator review is required before recommendation."

    validation = validate_case_reasoning(
        broken,
        source_text=source,
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )

    assert validation["status"] == "BLOCK"
    assert "decision_reason must be case-specific and cannot be a process receipt" in validation["errors"]


def test_authority_cue_requires_authority_pushback() -> None:
    source = _nsti_prompt()
    compiler = compile_case_reasoning(
        source,
        case_id="medical_a1_chest_wall_nsti_after_blunt_trauma",
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )
    broken = copy.deepcopy(compiler)
    broken["authority_pushback"] = []

    validation = validate_case_reasoning(
        broken,
        source_text=source,
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )

    assert validation["status"] == "BLOCK"
    assert "authority cues require authority_pushback entries" in validation["errors"]


def test_false_reassurance_tokens_are_distinct_from_authority() -> None:
    tokens = detect_false_reassurance_tokens(
        "No PHI. There is no crepitus, no shock, no abscess on ultrasound, and normal x-ray."
    )

    assert {token["token"] for token in tokens} >= {"no crepitus", "no shock", "no abscess", "normal x-ray"}
    assert all(token["why_non_closing"] for token in tokens)


def test_temporal_course_requires_trajectory_signal() -> None:
    source = _nsti_prompt()
    compiler = compile_case_reasoning(
        source,
        case_id="medical_a1_chest_wall_nsti_after_blunt_trauma",
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )
    broken = copy.deepcopy(compiler)
    broken["trajectory_signal"]["violation"] = ""

    validation = validate_case_reasoning(
        broken,
        source_text=source,
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )

    assert validation["status"] == "BLOCK"
    assert "temporal course requires trajectory_signal.violation" in validation["errors"]


def test_invalid_case_reasoning_blocks_threshold_event() -> None:
    source = _nsti_prompt()
    packet = start_operator_packet()
    locked = lock_frame(packet=packet, family="safety", frame=_frame(), governance_costs={"c_fp": 1, "c_fn": 9})
    frame_id = str(locked["frame"]["frame_id"])
    compiler = compile_case_reasoning(
        source,
        case_id="medical_a1_chest_wall_nsti_after_blunt_trauma",
        frame_id=frame_id,
        input_prompt_hash=prompt_hash(source),
    )
    compiler["decision_reason"] = "Operator review is required before recommendation."
    reported = run_report(
        packet=locked,
        report_text="obs: delayed worsening\nobs: radiology favors traumatic gas",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation={
            "case_id": "medical_a1_chest_wall_nsti_after_blunt_trauma",
            "case_reasoning_source_text": source,
            "case_reasoning": compiler,
            "report_synced": True,
            "contradictions_status": "none_identified",
        },
    )

    report_locked = lock_report(packet=reported)

    assert report_locked["schema_id"] == "nepsis.phase_rejection"
    assert [entry["event"] for entry in reported["audit_trace"]] == ["LOCK_FRAME", "RUN_REPORT"]


def test_true_closure_deescalates_without_red_escalation() -> None:
    source = (
        "No PHI. True closure case. Traumatic subcutaneous air occurred immediately after an open wound. "
        "Pain improves, vitals and labs are normal, and there is no progression. Operative wound exploration "
        "shows viable fascia and muscle, no necrotic tissue, no purulence, and no tracking infection."
    )

    compiler = compile_case_reasoning(
        source,
        case_id="medical_true_closure_traumatic_air_explored",
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )

    assert compiler["current_red_status"] == "closed"
    assert compiler["closure_condition"]["current_closure_status"] == "satisfied"
    assert compiler["recommended_threshold_action"] == "deescalate"
    assert compiler["recommended_threshold_action"] != "escalate_red"


def test_uncertain_status_requests_more_data() -> None:
    source = (
        "No PHI. Uncertain red-channel case. The surface story is early localized pain with limited data. "
        "There is no clear authority pushback and no temporal progression yet. The dangerous frame is possible "
        "early deep infection, but current evidence is insufficient to classify RED as open or closed."
    )

    compiler = compile_case_reasoning(
        source,
        case_id="medical_uncertain_early_deep_infection",
        frame_id="frame-1",
        input_prompt_hash=prompt_hash(source),
    )

    assert compiler["current_red_status"] == "uncertain"
    assert compiler["recommended_threshold_action"] == "request_more_data"


def test_model_v1_non_fixture_packet_runs_through_operator_flow() -> None:
    source = (
        "No PHI. A battery storage cabinet reports a charging fault. The pack is unplugged, "
        "but temperature continues rising and staff notice a chemical odor. Maintenance says "
        "it is probably just a sensor issue because there is no visible flame."
    )
    packet = start_operator_packet()
    locked = lock_frame(
        packet=packet,
        family="safety",
        frame={
            "text": source,
            "objective_type": "sensemake",
            "domain": "safety",
            "time_horizon": "short",
            "rationale_for_change": (
                "Red channel: missed battery thermal runaway | "
                "Blue channel: charger fault only after RED closure | "
                "Uncertainty: continued heating after unplugging"
            ),
            "constraints_hard": ["No PHI.", "Preserve RED before BLUE."],
            "constraints_soft": ["Keep audit concise."],
        },
        governance_costs={"c_fp": 1, "c_fn": 9},
    )
    frame_id = str(locked["frame"]["frame_id"])
    model_packet = _model_v1_packet(source, frame_id=frame_id)

    reported = run_report(
        packet=locked,
        report_text="obs: continued heating after unplugging\nobs: maintenance says sensor issue",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation={
            "case_id": "custom",
            "case_reasoning_source_text": source,
            "case_reasoning": model_packet,
            "report_synced": True,
            "contradictions_status": "none_identified",
        },
    )
    report_locked = lock_report(packet=reported)
    threshold = operator_packet_module.set_threshold_decision_from_case_reasoning(packet=report_locked)

    assert [entry["event"] for entry in threshold["audit_trace"]] == [
        "LOCK_FRAME",
        "RUN_REPORT",
        "LOCK_REPORT",
        "SET_THRESHOLD_DECISION",
    ]
    compiler = threshold["latest_audit"]["interpretation"]["packet"]["case_reasoning"]
    assert compiler["compiler_source"] == "model_v1"
    assert compiler["compiler_valid"] is True
    assert compiler["nodes"]["red"]["domain_red_hazard"]["hazard"] == "missed battery thermal runaway"
    assert threshold["latest_audit"]["threshold"]["packet"]["recommended_threshold_action"] == "escalate_red"


def test_invalid_compiler_marks_zeroback_reset_and_blocks_threshold_event() -> None:
    source = _nsti_prompt()
    packet = start_operator_packet()
    locked = lock_frame(packet=packet, family="safety", frame=_frame(), governance_costs={"c_fp": 1, "c_fn": 9})
    frame_id = str(locked["frame"]["frame_id"])
    compiler = compile_case_reasoning(
        source,
        case_id="medical_a1_chest_wall_nsti_after_blunt_trauma",
        frame_id=frame_id,
        input_prompt_hash=prompt_hash(source),
    )
    del compiler["nodes"]["red"]

    reported = run_report(
        packet=locked,
        report_text="obs: delayed worsening\nobs: radiology favors traumatic gas",
        sign={"critical_signal": True, "policy_violation": False},
        interpretation={
            "case_id": "medical_a1_chest_wall_nsti_after_blunt_trauma",
            "case_reasoning_source_text": source,
            "case_reasoning": compiler,
            "report_synced": True,
            "contradictions_status": "none_identified",
        },
    )
    report_locked = lock_report(packet=reported)

    rejected_compiler = reported["latest_audit"]["interpretation"]["packet"]["case_reasoning"]
    assert rejected_compiler["nodes"]["zeroback_reset"]["reset_required"] is True
    assert report_locked["schema_id"] == "nepsis.phase_rejection"
    assert [entry["event"] for entry in reported["audit_trace"]] == ["LOCK_FRAME", "RUN_REPORT"]
