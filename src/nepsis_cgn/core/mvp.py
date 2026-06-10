from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from .state_feedback import build_state_feedback
from .still import build_still_pathway

MvpCaseId = Literal["jailing", "clinical"]
MVP_PACKET_SCHEMA_ID = "nepsis.mvp_packet"
MVP_PACKET_SCHEMA_VERSION = "0.1.6"


def build_nepsis_mvp_packet(
    *,
    case_id: MvpCaseId = "jailing",
    input_text: Optional[str] = None,
) -> dict[str, Any]:
    if case_id == "jailing":
        return _build_jailing_packet(input_text=input_text)
    if case_id == "clinical":
        return _build_clinical_packet(input_text=input_text)
    raise ValueError("case_id must be one of: jailing, clinical")


def _base_packet(*, case_id: MvpCaseId, input_text: str) -> dict[str, Any]:
    return {
        "schema_id": MVP_PACKET_SCHEMA_ID,
        "schema_version": MVP_PACKET_SCHEMA_VERSION,
        "packet_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "case_id": case_id,
        "input_text": input_text,
    }


def _contradiction_density_from_count(contradictions: list[dict[str, Any]]) -> float:
    count = len(contradictions)
    if count == 0:
        return 0.0
    return count / float(count + 1)


def _build_density_channels(contradictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    channels: dict[str, dict[str, Any]] = {}
    for item in contradictions:
        level = str(item.get("level") or "untyped")
        channel = channels.setdefault(
            level,
            {
                "contradiction_count": 0,
                "open_count": 0,
                "resolved_count": 0,
                "contradiction_density": 0.0,
                "runtime_gate_input": False,
            },
        )
        channel["contradiction_count"] += 1
        if str(item.get("status") or "").startswith("resolved"):
            channel["resolved_count"] += 1
        else:
            channel["open_count"] += 1

    for channel in channels.values():
        channel["contradiction_density"] = _contradiction_density_from_count(
            [{}] * int(channel["contradiction_count"])
        )
    return channels


def _build_contradiction_monitor(
    *,
    contradictions: list[dict[str, Any]],
    stability_status: str,
) -> dict[str, Any]:
    return {
        "contradictions": contradictions,
        "contradiction_density": _contradiction_density_from_count(contradictions),
        "density_basis": {
            "model": "saturating_count_v1",
            "formula": "contradiction_count / (contradiction_count + 1)",
            "contradiction_count": len(contradictions),
            "aggregate_role": "demo_only_scalar_summary",
            "runtime_gate_input": False,
            "runtime_gate_note": (
                "Frozen MVP demo score only; runtime governance derives contradiction_density "
                "from evaluated constraint violations."
            ),
            "channel_note": "Typed density channels preserve object/meta/action-threshold distinctions.",
        },
        "density_channels": _build_density_channels(contradictions),
        "stability_status": stability_status,
    }


def _build_retessellation_state(
    *,
    required: bool,
    completed: bool,
    trigger_event_order: int | None,
    completed_event_order: int | None,
    remaining_obligation: str,
) -> dict[str, Any]:
    if not required:
        return {
            "status": "not_required",
            "required": False,
            "completed_in_packet": False,
            "trigger_event_order": None,
            "completed_event_order": None,
            "remaining_obligation": remaining_obligation,
        }
    return {
        "status": "completed_in_packet" if completed else "required_pending",
        "required": True,
        "completed_in_packet": completed,
        "trigger_event_order": trigger_event_order,
        "completed_event_order": completed_event_order,
        "remaining_obligation": remaining_obligation,
    }


def _build_jailing_packet(*, input_text: Optional[str]) -> dict[str, Any]:
    text = input_text or (
        "Canonical Jailing/Jingall case: source constraint says the required name is JINGALL, "
        "but the candidate answer collapses to the familiar word JAILING."
    )
    candidate = "JAILING" if "JAILING" in text.upper() else "unknown_candidate"
    target = "JINGALL"
    contradiction = candidate != "unknown_candidate" and candidate != target
    contradictions = [
        {
            "id": "candidate_token_mismatch",
            "type": "constraint contradiction",
            "level": "object",
            "status": "resolved_in_packet",
            "observation": "candidate_token=JAILING",
            "conflicts_with": "Hard constraint requires JINGALL",
            "introduced_at_order": 5,
            "resolution_event_order": 11,
        },
        {
            "id": "missing_proper_token_hypothesis",
            "type": "missing-denominator contradiction",
            "level": "meta",
            "status": "resolved_in_packet",
            "observation": "BLUE initially considered fluent word completion",
            "conflicts_with": "hypothesis set omitted exact proper-token preservation",
            "introduced_at_order": 6,
            "resolution_event_order": 9,
        },
    ] if contradiction else []

    packet = _base_packet(case_id="jailing", input_text=text)
    packet.update(
        {
            "observations": [
                "source_token=JINGALL",
                f"candidate_token={candidate}",
                "candidate looks like a plausible common word",
            ],
            "constraints": [
                "Hard constraint: preserve the source token JINGALL exactly.",
                "Hard constraint: do not normalize a proper token into a plausible nearby word.",
                "Must-not-miss hazard: cosmetic fluency cannot override source identity.",
            ],
            "red_channel": {
                "active_hazards": [
                    {
                        "id": "proper_token_substitution",
                        "severity": "hard_stop",
                        "hazard": "Candidate changes JINGALL into JAILING.",
                        "constraint": "source token must be preserved exactly",
                    }
                ]
                if contradiction
                else [],
                "ruled_out_hazards": [],
                "missing_discriminators": [
                    "Confirm source spelling from the prompt or authoritative record.",
                    "Compare candidate token character-by-character against the governed token.",
                ],
                "escalation_required": contradiction,
                "rationale": "RED runs first because source-token preservation is a hard constraint, not a style preference.",
            },
            "still": build_still_pathway(
                checkpoint_1_trigger_status="hold_or_bounded_blue" if contradiction else "blue_allowed",
                checkpoint_1_reason="Source-token constraint risk remains active; BLUE may explain but cannot clear RED."
                if contradiction
                else "No RED blocker detected before BLUE.",
                checkpoint_1_required_before_commitment=[
                    "source token verified",
                    "RED source-preservation constraint preserved",
                ],
                checkpoint_2_reason="Constraint contradiction and denominator collapse require retessellation."
                if contradiction
                else "No contradiction or denominator collapse found after BLUE.",
                checkpoint_2_required_before_commitment=[
                    "candidate token matches governed token exactly",
                    "retessellated hypothesis set includes proper-token preservation",
                    "no cosmetic rename hypothesis remains live",
                ],
                red_escalation_required=contradiction,
                contradiction_present=contradiction,
                denominator_collapse_detected=contradiction,
                non_quiescence_possible=contradiction,
                zeroback_triggered=contradiction,
                learning_notes=[
                    "Fluent plausibility is not permission to overwrite governed tokens.",
                    "Exact source constraints must survive BLUE optimization.",
                ],
            ),
            "blue_channel": {
                "hypotheses": [
                    {
                        "id": "constraint_preserving_token",
                        "label": "JINGALL is the required answer.",
                        "likelihood": "high_support",
                        "post_constraint_standing": "dominant_after_red_constraint",
                        "action_priority": "commit_after_exact_token_match",
                        "supporting_features": ["source token is explicit", "hard constraint names exact preservation"],
                        "contradicting_features": ["candidate answer used JAILING"],
                        "needed_discriminators": ["source-token verification"],
                        "action_threshold": "commit only after exact-token match",
                    },
                    {
                        "id": "plausible_word_collapse",
                        "label": "JAILING is a fluent but invalid normalization.",
                        "likelihood": "surface_plausible_only",
                        "post_constraint_standing": "rejected_by_constraint",
                        "action_priority": "blocked_by_red_boundary",
                        "supporting_features": ["candidate is a familiar English word"],
                        "contradicting_features": ["violates exact source-token constraint"],
                        "needed_discriminators": ["none; hard constraint already decides"],
                        "action_threshold": "blocked by RED",
                    },
                ],
                "evaluation_axes": {
                    "support": {
                        "description": "Evidence or plausibility support only; not action priority.",
                        "by_hypothesis": {
                            "constraint_preserving_token": "high",
                            "plausible_word_collapse": "surface_plausible_only",
                        },
                    },
                    "action_priority": {
                        "description": "RED/threshold action class only; not a likelihood magnitude.",
                        "by_hypothesis": {
                            "constraint_preserving_token": "commit_after_exact_token_match",
                            "plausible_word_collapse": "blocked_by_red_boundary",
                        },
                    },
                },
                "supporting_features": ["exact source token exists", "candidate mismatch is observable"],
                "contradicting_features": ["candidate changes governed token"],
                "needed_discriminators": ["exact source-token comparison"],
            },
            "contradiction_monitor": _build_contradiction_monitor(
                contradictions=contradictions,
                stability_status="unstable_retest_required" if contradiction else "stable",
            ),
            "denominator_collapse": {
                "detected": contradiction,
                "missing_hypothesis_classes": [
                    "proper-token preservation",
                    "orthographic trap / near-word substitution",
                ]
                if contradiction
                else [],
                "retessellation_required": contradiction,
            },
            "retessellation_state": _build_retessellation_state(
                required=contradiction,
                completed=contradiction,
                trigger_event_order=8 if contradiction else None,
                completed_event_order=9 if contradiction else None,
                remaining_obligation="next-cycle source-token verification remains pending in the MVP packet"
                if contradiction
                else "no retessellation obligation in this deterministic packet",
            ),
            "voronoi_commitment": {
                "recommended_action": "Reject JAILING; preserve JINGALL as the governed answer.",
                "threshold_basis": "Hard constraint beats fluency and support-only likelihood.",
                "consequence_weighting": "False acceptance violates the core case rule; false rejection is repairable.",
            },
            "non_quiescence": {
                "wrong_manifold_possible": contradiction,
                "reason": "A fluent-word manifold explains JAILING but cannot satisfy the source-token constraint.",
                "next_required_move": "Retessellate around exact-token preservation before final answer.",
            },
            "zeroback": {
                "triggered": contradiction,
                "reason": "Reset from plausible-word completion to governed-token comparison.",
                "reset_scope": "Keep observations and hard constraints; rebuild hypotheses and discard cosmetic rename.",
            },
            "state_feedback": build_state_feedback(
                timestamp_or_phase="mvp_post_commitment_packet",
                active_frame="governed token constraint",
                active_constraints=[
                    "preserve source token JINGALL exactly",
                    "do not substitute fluent plausibility for source identity",
                ],
                active_hazards=["proper_token_substitution"] if contradiction else [],
                current_commitment="Reject JAILING; preserve JINGALL as the governed answer.",
                uncertainty_level="constraint_conflict_active" if contradiction else "low",
                expected_time_window="next response or source-token verification step",
                expected_changes=[
                    "valid output preserves source-token identity",
                    "fluent near-word substitution remains blocked",
                ],
                expected_discriminators=[
                    "source-token verification",
                    "character-level candidate comparison",
                ],
                expected_resolution_signs=[
                    "output token equals JINGALL",
                    "audit trace keeps exact-token constraint active",
                ],
                failure_conditions=[
                    "response rewrites JINGALL",
                    "response overwrites the governed token",
                    "response treats fluent plausibility as permission",
                ],
                loop_status="pending_observation",
                loop_rationale=(
                    "Retessellation completed inside the MVP packet; the remaining obligation is next-cycle source-token verification."
                )
                if contradiction
                else "No next observation has been collected inside the MVP packet.",
                next_observation_required="Verify whether the produced output preserves JINGALL exactly.",
                delta_reason="No observed next state is available in the MVP; future output must be checked against source-token preservation.",
                audit_events=[
                    "Declared expected next-state constraint for governed-token preservation.",
                    "Defined failure conditions that would force hold or retessellation.",
                ],
            ),
            "audit_trace": [
                _event(1, "signal_intake", "Parsed source token, candidate token, and governing rule."),
                _event(2, "red_channel", "Applied exact-token hard constraint before optimization."),
                _event(3, "still_checkpoint_1", "Held naive BLUE entry; allowed bounded BLUE for audit only."),
                _event(4, "blue_channel", "Compared constraint-preserving and fluent-word hypotheses inside RED boundary."),
                _event(5, "contradiction_monitor", "Classified candidate/source mismatch as constraint contradiction."),
                _event(6, "denominator_collapse", "Detected missing proper-token hypothesis class."),
                _event(7, "non_quiescence", "Marked wrong-manifold risk from fluent-word reasoning."),
                _event(8, "still_checkpoint_2", "Set commitment readiness to retessellate."),
                _event(9, "retessellation", "Rebuilt hypothesis space around exact source-token preservation."),
                _event(10, "zeroback", "Reset from plausible-word completion to governed-token comparison."),
                _event(11, "voronoi_commitment", "Selected action by hard constraint and consequence, not by fluency."),
                _event(12, "state_feedback", "Declared next-state observations and failure conditions for the active frame."),
            ],
            "final_output": {
                "concise_recommendation": "Do not accept JAILING. Return or preserve JINGALL unless source verification changes.",
                "caveats": ["This demo is deterministic and constraint-scaffolded; it is not an LLM answer."],
                "required_next_discriminators": ["source-token verification", "character-level candidate comparison"],
            },
            "demo_limitations": [
                {
                    "id": "hard_red_demo_case",
                    "limitation": "The Jailing/Jingall packet demonstrates a hard RED constraint case where RED decides once the governed token is accepted as authoritative.",
                    "implication": "It does not prove the detector can find every missing hypothesis class in harder source-integrity cases.",
                },
                {
                    "id": "source_token_corruption_not_detected",
                    "limitation": "The MVP assumes JINGALL is the authoritative source token; it does not demonstrate detection of the harder variant where the source token itself is corrupted and JAILING is true.",
                    "implication": "Source-token verification remains an explicit next-cycle obligation rather than a completed runtime observation.",
                },
            ],
        }
    )
    return packet


def _build_clinical_packet(*, input_text: Optional[str]) -> dict[str, Any]:
    text = input_text or (
        "Clinical demo: back pain with radicular spasm plus saddle anesthesia and new bladder dysfunction."
    )
    lowered = text.lower()
    red_flags = [
        label
        for label, present in (
            ("saddle_anesthesia", "saddle" in lowered),
            ("bladder_dysfunction", "bladder" in lowered or "retention" in lowered),
            ("bilateral_weakness", "bilateral" in lowered and "weak" in lowered),
            ("fever", "fever" in lowered),
        )
        if present
    ]
    red_active = bool(red_flags)
    contradictions = [
        {
            "id": "benign_closure_vs_red_flags",
            "type": "action-threshold contradiction",
            "level": "action_threshold",
            "status": "open_pending_discriminators",
            "observation": "benign spasm narrative competes with red flags",
            "conflicts_with": "RED escalation threshold crossed by consequence",
            "introduced_at_order": 5,
            "resolution_event_order": None,
        }
    ] if red_active else []

    packet = _base_packet(case_id="clinical", input_text=text)
    packet.update(
        {
            "observations": [
                "radicular pain/spasm narrative present",
                *(f"red_flag={flag}" for flag in red_flags),
            ],
            "constraints": [
                "Hard constraint: cauda equina red flags cannot be set aside as benign spasm.",
                "Must-not-miss hazard: neurologic compromise with bladder/saddle symptoms.",
                "Blue optimization may only run after red flags are escalated or explicitly ruled out.",
            ],
            "red_channel": {
                "active_hazards": [
                    {
                        "id": "cauda_equina_must_not_miss",
                        "severity": "red",
                        "hazard": "Potential cauda equina syndrome.",
                        "features": red_flags,
                    }
                ]
                if red_active
                else [],
                "ruled_out_hazards": [],
                "missing_discriminators": [
                    "post-void residual",
                    "focused saddle sensory exam",
                    "lower-extremity motor/reflex exam",
                    "urgent imaging pathway availability",
                ],
                "escalation_required": red_active,
                "rationale": "RED runs first because neurologic red flags dominate action threshold under uncertainty.",
            },
            "still": build_still_pathway(
                checkpoint_1_trigger_status="escalation_preserved" if red_active else "blue_allowed",
                checkpoint_1_reason="High-consequence RED hazard remains active; BLUE cannot downgrade escalation."
                if red_active
                else "No RED blocker detected before BLUE.",
                checkpoint_1_required_before_commitment=[
                    "red flags explicitly escalated or ruled out",
                    "RED hazard status preserved through BLUE reasoning",
                ],
                checkpoint_2_reason="Red-flag contradiction and denominator collapse require retessellation."
                if red_active
                else "No contradiction or denominator collapse found after BLUE.",
                checkpoint_2_required_before_commitment=[
                    "post-void residual reviewed",
                    "focused neurologic exam reviewed",
                    "compressive neurologic emergency represented in hypothesis set",
                ],
                red_escalation_required=red_active,
                contradiction_present=red_active,
                denominator_collapse_detected=red_active,
                non_quiescence_possible=red_active,
                zeroback_triggered=red_active,
                learning_notes=[
                    "Benign narrative cannot close while red-flag discriminators remain unresolved.",
                    "High-consequence uncertainty keeps RED authority active through BLUE reasoning.",
                ],
            ),
            "blue_channel": {
                "hypotheses": [
                    {
                        "id": "benign_radicular_spasm",
                        "label": "Mechanical/radicular spasm",
                        "likelihood": "medium_support",
                        "post_constraint_standing": "plausible_but_red_bounded",
                        "action_priority": "bounded_until_red_flags_resolved",
                        "supporting_features": ["radicular pain", "spasm narrative"],
                        "contradicting_features": red_flags,
                        "needed_discriminators": ["neuro exam", "post-void residual"],
                        "action_threshold": "treat only after red flags addressed",
                    },
                    {
                        "id": "cauda_equina",
                        "label": "Cauda equina / compressive neurologic emergency",
                        "likelihood": "uncertain_support",
                        "post_constraint_standing": "action_dominant_by_consequence" if red_active else "low_support",
                        "action_priority": "red-action-dominant" if red_active else "low",
                        "supporting_features": red_flags,
                        "contradicting_features": [],
                        "needed_discriminators": ["urgent MRI / specialist pathway"],
                        "action_threshold": "escalate before benign closure",
                    },
                ],
                "evaluation_axes": {
                    "support": {
                        "description": "Evidence or plausibility support only; not action priority.",
                        "by_hypothesis": {
                            "benign_radicular_spasm": "medium",
                            "cauda_equina": "uncertain",
                        },
                    },
                    "action_priority": {
                        "description": "RED/threshold action class only; not a likelihood magnitude.",
                        "by_hypothesis": {
                            "benign_radicular_spasm": "bounded_until_red_flags_resolved",
                            "cauda_equina": "red-action-dominant" if red_active else "low",
                        },
                    },
                },
                "supporting_features": ["radicular pain", "spasm"],
                "contradicting_features": red_flags,
                "needed_discriminators": ["post-void residual", "focused neurologic exam"],
            },
            "contradiction_monitor": _build_contradiction_monitor(
                contradictions=contradictions,
                stability_status="hold_for_discriminator" if red_active else "stable",
            ),
            "denominator_collapse": {
                "detected": red_active,
                "missing_hypothesis_classes": ["compressive neurologic emergency"] if red_active else [],
                "retessellation_required": red_active,
            },
            "retessellation_state": _build_retessellation_state(
                required=red_active,
                completed=red_active,
                trigger_event_order=8 if red_active else None,
                completed_event_order=9 if red_active else None,
                remaining_obligation="next-cycle clinical discriminator verification remains pending in the MVP packet"
                if red_active
                else "no retessellation obligation in this deterministic packet",
            ),
            "voronoi_commitment": {
                "recommended_action": "Escalate red-flag pathway; do not finalize as benign spasm yet."
                if red_active
                else "Proceed with blue-channel optimization while monitoring for red flags.",
                "threshold_basis": "Consequence-weighted threshold, not most-likely diagnosis.",
                "consequence_weighting": "Missed neurologic emergency dominates unnecessary escalation cost.",
            },
            "non_quiescence": {
                "wrong_manifold_possible": red_active,
                "reason": "Benign spasm manifold cannot absorb bladder/saddle red flags without contradiction.",
                "next_required_move": "Gather discriminators or escalate; do not calmly finalize.",
            },
            "zeroback": {
                "triggered": red_active,
                "reason": "Reset from benign-pain manifold to must-not-miss neurologic emergency frame.",
                "reset_scope": "Keep symptoms and red flags; reset priors and rebuild hypotheses.",
            },
            "state_feedback": build_state_feedback(
                timestamp_or_phase="mvp_post_commitment_packet",
                active_frame="high-consequence red-flag clinical uncertainty",
                active_constraints=[
                    "red flags cannot be set aside as benign spasm",
                    "BLUE optimization cannot downgrade unresolved RED hazard",
                ],
                active_hazards=["cauda_equina_must_not_miss"] if red_active else [],
                current_commitment="Escalate red-flag pathway; do not finalize as benign spasm yet."
                if red_active
                else "Proceed with blue-channel optimization while monitoring for red flags.",
                uncertainty_level="high_consequence_unresolved" if red_active else "moderate",
                expected_time_window="next discriminator collection step",
                expected_changes=[
                    "discriminating data stabilizes benign frame only if red flags are resolved",
                    "RED remains active while bladder/saddle findings are unresolved",
                ],
                expected_discriminators=[
                    "post-void residual",
                    "focused saddle sensory exam",
                    "lower-extremity motor/reflex exam",
                    "urgent imaging or specialist decision",
                ],
                expected_resolution_signs=[
                    "red-flag discriminators documented",
                    "benign closure occurs only after RED hazard is ruled out",
                ],
                failure_conditions=[
                    "worsening vitals or neurologic state",
                    "unresolved red flags",
                    "missing discriminator",
                    "benign closure despite active RED hazard",
                ],
                loop_status="pending_observation",
                loop_rationale=(
                    "Retessellation completed inside the MVP packet; the remaining obligation is next-cycle discriminator verification."
                )
                if red_active
                else "No next observation has been collected inside the MVP packet.",
                next_observation_required="Obtain and compare red-flag discriminators against the expected trajectory.",
                delta_reason="No observed next state is available in the MVP; the next clinical state must be checked against unresolved RED hazards.",
                audit_events=[
                    "Declared expected next-state trajectory for high-consequence red-flag uncertainty.",
                    "Defined failure conditions that would force hold, retessellation, or ZeroBack.",
                ],
            ),
            "audit_trace": [
                _event(1, "signal_intake", "Parsed pain narrative and red-flag observations."),
                _event(2, "red_channel", "Screened must-not-miss neurologic hazards before BLUE."),
                _event(3, "still_checkpoint_1", "Preserved RED escalation before bounded BLUE analysis."),
                _event(4, "blue_channel", "Compared benign and catastrophic hypotheses inside RED boundary."),
                _event(5, "contradiction_monitor", "Classified benign closure vs red flags as action-threshold contradiction."),
                _event(6, "denominator_collapse", "Detected omitted emergency class if only benign spasm is considered."),
                _event(7, "non_quiescence", "Marked wrong-manifold risk from benign closure."),
                _event(8, "still_checkpoint_2", "Set commitment readiness to retessellate."),
                _event(9, "retessellation", "Rebuilt hypothesis space to include compressive neurologic emergency."),
                _event(10, "zeroback", "Reset from benign-pain manifold to must-not-miss emergency frame."),
                _event(11, "voronoi_commitment", "Committed to escalation/hold based on consequence-weighted threshold."),
                _event(12, "state_feedback", "Declared next-state observations and failure conditions for the active frame."),
            ],
            "final_output": {
                "concise_recommendation": "Do not close as benign spasm. Escalate or obtain the red-flag discriminators now."
                if red_active
                else "No red flags found in this text; continue blue-channel work with explicit red-flag monitoring.",
                "caveats": ["Deterministic MVP scaffold; not medical advice or a diagnosis."],
                "required_next_discriminators": [
                    "post-void residual",
                    "focused saddle sensory exam",
                    "motor/reflex exam",
                    "urgent imaging/specialist decision",
                ],
            },
            "demo_limitations": [
                {
                    "id": "deterministic_red_flag_scaffold",
                    "limitation": "The clinical MVP packet is a deterministic red-flag governance scaffold, not a clinical diagnostic runtime.",
                    "implication": "It demonstrates escalation preservation and pending discriminator obligations without observing a live clinical next state.",
                }
            ],
        }
    )
    return packet


def _event(order: int, stage: str, summary: str) -> dict[str, Any]:
    return {"order": order, "stage": stage, "summary": summary}


__all__ = [
    "MVP_PACKET_SCHEMA_ID",
    "MVP_PACKET_SCHEMA_VERSION",
    "MvpCaseId",
    "build_nepsis_mvp_packet",
]
