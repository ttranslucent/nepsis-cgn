from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Literal, Optional
from uuid import uuid4

from .state_feedback import build_state_feedback
from .still import build_still_pathway

MvpCaseId = Literal["jailing", "clinical"]
MVP_PACKET_SCHEMA_ID = "nepsis.mvp_packet"
MVP_PACKET_SCHEMA_VERSION = "0.1.5"
_TOKEN_PATTERN = r"([A-Za-z][A-Za-z0-9_-]{1,})"


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


def _normalize_demo_token(value: str) -> str:
    return value.strip(" \t\n\r\"'`.,;:()[]{}").upper()


def _extract_token_pair(
    text: str,
    *,
    default_source: str,
    default_candidate: str | None,
) -> tuple[str, str | None]:
    patterns = [
        rf"\bsource[_\s-]*token\s*[:=]\s*{_TOKEN_PATTERN}.*?\bcandidate[_\s-]*token\s*[:=]\s*{_TOKEN_PATTERN}",
        rf"\bsource\s+(?:token\s+)?(?:says|is)\s+{_TOKEN_PATTERN}.*?\b(?:model|answer|candidate|output)\s+(?:answered|says|used|is)\s+{_TOKEN_PATTERN}",
        rf"\brequired\s+name\s+is\s+{_TOKEN_PATTERN}.*?\bcandidate\s+answer\s+collapses\s+to\s+(?:the\s+\w+\s+word\s+)?{_TOKEN_PATTERN}",
        rf"\bsource(?:[_\s-]*token)?\s*(?::|=|says|is)?\s*{_TOKEN_PATTERN}.*?\b(?:candidate|answer|model|output)(?:[_\s-]*token)?\s*(?::|=|answered|says|used|is)?\s*{_TOKEN_PATTERN}",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return _normalize_demo_token(match.group(1)), _normalize_demo_token(match.group(2))

    upper_text = text.upper()
    source = default_source
    candidate = default_candidate
    if default_source in upper_text:
        source = default_source
    if default_candidate and default_candidate in upper_text:
        candidate = default_candidate
    return source, candidate


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
            "runtime_gate_input": False,
            "runtime_gate_note": (
                "Frozen MVP demo score only; runtime governance derives contradiction_density "
                "from evaluated constraint violations."
            ),
        },
        "stability_status": stability_status,
    }


def _build_jailing_packet(*, input_text: Optional[str]) -> dict[str, Any]:
    text = input_text or (
        "Canonical Jailing/Jingall case: source constraint says the required name is JINGALL, "
        "but the candidate answer collapses to the familiar word JAILING."
    )
    source_token, candidate = _extract_token_pair(text, default_source="JINGALL", default_candidate="JAILING")
    candidate_observation = candidate or "unknown_candidate"
    contradiction = candidate is not None and candidate != source_token
    contradictions = [
        {
            "type": "constraint contradiction",
            "observation": f"candidate_token={candidate}",
            "conflicts_with": f"Hard constraint requires {source_token}",
        },
        {
            "type": "missing-denominator contradiction",
            "observation": "BLUE initially considered fluent word completion",
            "conflicts_with": "hypothesis set omitted exact proper-token preservation",
        },
    ] if contradiction else []

    packet = _base_packet(case_id="jailing", input_text=text)
    packet.update(
        {
            "observations": [
                f"source_token={source_token}",
                f"candidate_token={candidate_observation}",
                "candidate looks like a plausible common word",
            ],
            "constraints": [
                f"Hard constraint: preserve the source token {source_token} exactly.",
                "Hard constraint: do not normalize a proper token into a plausible nearby word.",
                "Must-not-miss hazard: cosmetic fluency cannot override source identity.",
            ],
            "red_channel": {
                "active_hazards": [
                    {
                        "id": "proper_token_substitution",
                        "severity": "hard_stop",
                        "hazard": f"Candidate changes {source_token} into {candidate}.",
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
                        "label": f"{source_token} is the required answer.",
                        "likelihood": "dominant_after_red_constraint",
                        "supporting_features": ["source token is explicit", "hard constraint names exact preservation"],
                        "contradicting_features": [f"candidate answer used {candidate_observation}"],
                        "needed_discriminators": ["source-token verification"],
                        "action_threshold": "commit only after exact-token match",
                    },
                    {
                        "id": "plausible_word_collapse",
                        "label": f"{candidate_observation} is a fluent but invalid normalization.",
                        "likelihood": "rejected_by_constraint",
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
            "voronoi_commitment": {
                "recommended_action": (
                    f"Reject {candidate}; preserve {source_token} as the governed answer."
                    if contradiction
                    else f"Preserve {source_token}; no conflicting candidate was identified."
                ),
                "threshold_basis": "Hard constraint beats fluency and likelihood.",
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
                    f"preserve source token {source_token} exactly",
                    "do not substitute fluent plausibility for source identity",
                ],
                active_hazards=["proper_token_substitution"] if contradiction else [],
                current_commitment=(
                    f"Reject {candidate}; preserve {source_token} as the governed answer."
                    if contradiction
                    else f"Preserve {source_token}; no conflicting candidate was identified."
                ),
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
                    f"output token equals {source_token}",
                    "audit trace keeps exact-token constraint active",
                ],
                failure_conditions=[
                    f"response rewrites {source_token}",
                    "response overwrites the governed token",
                    "response treats fluent plausibility as permission",
                ],
                loop_status="retessellate" if contradiction else "pending_observation",
                loop_rationale="Current contradiction and denominator collapse require retessellation before closure."
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
                "concise_recommendation": (
                    f"Do not accept {candidate}. Return or preserve {source_token} unless source verification changes."
                    if contradiction
                    else f"Preserve {source_token}; no conflicting candidate was identified in this query."
                ),
                "caveats": ["This demo is deterministic and constraint-scaffolded; it is not an LLM answer."],
                "required_next_discriminators": ["source-token verification", "character-level candidate comparison"],
            },
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
            "type": "action-threshold contradiction",
            "observation": "benign spasm narrative competes with red flags",
            "conflicts_with": "RED escalation threshold crossed by consequence",
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
                        "likelihood": "plausible_but_red_bounded",
                        "supporting_features": ["radicular pain", "spasm narrative"],
                        "contradicting_features": red_flags,
                        "needed_discriminators": ["neuro exam", "post-void residual"],
                        "action_threshold": "treat only after red flags addressed",
                    },
                    {
                        "id": "cauda_equina",
                        "label": "Cauda equina / compressive neurologic emergency",
                        "likelihood": "action_dominant_by_consequence",
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
                loop_status="retessellate" if red_active else "pending_observation",
                loop_rationale="Current RED hazard and denominator collapse require retessellation before benign closure."
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
