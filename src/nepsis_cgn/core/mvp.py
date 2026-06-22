from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from .state_feedback import build_state_feedback
from .still import build_still_pathway

MvpCaseId = Literal["jailing", "sea_ivdu", "wirecard"]
MVP_PACKET_SCHEMA_ID = "nepsis.mvp_packet"
MVP_PACKET_SCHEMA_VERSION = "0.2.0"
PUBLIC_MVP_CASE_IDS: tuple[MvpCaseId, ...] = ("jailing", "sea_ivdu", "wirecard")
PUBLIC_MVP_RELEASE = {
    "release_id": "public_mvp_v0.4",
    "label": "Public MVP v0.4",
    "mode": "deterministic_packet_proof",
    "model_free": True,
    "login_required": False,
    "api_key_required": False,
}


def build_nepsis_mvp_packet(
    *,
    case_id: MvpCaseId = "jailing",
    input_text: Optional[str] = None,
) -> dict[str, Any]:
    if case_id == "jailing":
        return _build_jailing_packet(input_text=input_text)
    if case_id == "sea_ivdu":
        return _build_sea_ivdu_packet(input_text=input_text)
    if case_id == "wirecard":
        return _build_wirecard_packet(input_text=input_text)
    raise ValueError("case_id must be one of: jailing, sea_ivdu, wirecard")


def _base_packet(*, case_id: MvpCaseId, input_text: str) -> dict[str, Any]:
    return {
        "schema_id": MVP_PACKET_SCHEMA_ID,
        "schema_version": MVP_PACKET_SCHEMA_VERSION,
        "packet_id": str(uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "case_id": case_id,
        "input_text": input_text,
        "public_release": {
            **PUBLIC_MVP_RELEASE,
            "supported_cases": list(PUBLIC_MVP_CASE_IDS),
        },
    }


def _contradiction_density_from_count(contradictions: list[dict[str, Any]]) -> float:
    count = len(contradictions)
    if count == 0:
        return 0.0
    return count / float(count + 1)


def _build_density_channels(
    contradictions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
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
    contradictions = (
        [
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
        ]
        if contradiction
        else []
    )

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
                "active_hazards": (
                    [
                        {
                            "id": "proper_token_substitution",
                            "severity": "hard_stop",
                            "hazard": "Candidate changes JINGALL into JAILING.",
                            "constraint": "source token must be preserved exactly",
                        }
                    ]
                    if contradiction
                    else []
                ),
                "ruled_out_hazards": [],
                "missing_discriminators": [
                    "Confirm source spelling from the prompt or authoritative record.",
                    "Compare candidate token character-by-character against the governed token.",
                ],
                "escalation_required": contradiction,
                "rationale": "RED runs first because source-token preservation is a hard constraint, not a style preference.",
            },
            "still": build_still_pathway(
                checkpoint_1_trigger_status=(
                    "hold_or_bounded_blue" if contradiction else "blue_allowed"
                ),
                checkpoint_1_reason=(
                    "Source-token constraint risk remains active; BLUE may explain but cannot clear RED."
                    if contradiction
                    else "No RED blocker detected before BLUE."
                ),
                checkpoint_1_required_before_commitment=[
                    "source token verified",
                    "RED source-preservation constraint preserved",
                ],
                checkpoint_2_reason=(
                    "Constraint contradiction and denominator collapse require retessellation."
                    if contradiction
                    else "No contradiction or denominator collapse found after BLUE."
                ),
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
                        "supporting_features": [
                            "source token is explicit",
                            "hard constraint names exact preservation",
                        ],
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
                        "contradicting_features": [
                            "violates exact source-token constraint"
                        ],
                        "needed_discriminators": [
                            "none; hard constraint already decides"
                        ],
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
                "supporting_features": [
                    "exact source token exists",
                    "candidate mismatch is observable",
                ],
                "contradicting_features": ["candidate changes governed token"],
                "needed_discriminators": ["exact source-token comparison"],
            },
            "contradiction_monitor": _build_contradiction_monitor(
                contradictions=contradictions,
                stability_status=(
                    "unstable_retest_required" if contradiction else "stable"
                ),
            ),
            "denominator_collapse": {
                "detected": contradiction,
                "missing_hypothesis_classes": (
                    [
                        "proper-token preservation",
                        "orthographic trap / near-word substitution",
                    ]
                    if contradiction
                    else []
                ),
                "retessellation_required": contradiction,
            },
            "retessellation_state": _build_retessellation_state(
                required=contradiction,
                completed=contradiction,
                trigger_event_order=8 if contradiction else None,
                completed_event_order=9 if contradiction else None,
                remaining_obligation=(
                    "next-cycle source-token verification remains pending in the MVP packet"
                    if contradiction
                    else "no retessellation obligation in this deterministic packet"
                ),
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
                uncertainty_level=(
                    "constraint_conflict_active" if contradiction else "low"
                ),
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
                    (
                        "Retessellation completed inside the MVP packet; the remaining obligation is next-cycle source-token verification."
                    )
                    if contradiction
                    else "No next observation has been collected inside the MVP packet."
                ),
                next_observation_required="Verify whether the produced output preserves JINGALL exactly.",
                delta_reason="No observed next state is available in the MVP; future output must be checked against source-token preservation.",
                audit_events=[
                    "Declared expected next-state constraint for governed-token preservation.",
                    "Defined failure conditions that would force hold or retessellation.",
                ],
            ),
            "audit_trace": [
                _event(
                    1,
                    "signal_intake",
                    "Parsed source token, candidate token, and governing rule.",
                ),
                _event(
                    2,
                    "red_channel",
                    "Applied exact-token hard constraint before optimization.",
                ),
                _event(
                    3,
                    "still_checkpoint_1",
                    "Held naive BLUE entry; allowed bounded BLUE for audit only.",
                ),
                _event(
                    4,
                    "blue_channel",
                    "Compared constraint-preserving and fluent-word hypotheses inside RED boundary.",
                ),
                _event(
                    5,
                    "contradiction_monitor",
                    "Classified candidate/source mismatch as constraint contradiction.",
                ),
                _event(
                    6,
                    "denominator_collapse",
                    "Detected missing proper-token hypothesis class.",
                ),
                _event(
                    7,
                    "non_quiescence",
                    "Marked wrong-manifold risk from fluent-word reasoning.",
                ),
                _event(
                    8, "still_checkpoint_2", "Set commitment readiness to retessellate."
                ),
                _event(
                    9,
                    "retessellation",
                    "Rebuilt hypothesis space around exact source-token preservation.",
                ),
                _event(
                    10,
                    "zeroback",
                    "Reset from plausible-word completion to governed-token comparison.",
                ),
                _event(
                    11,
                    "voronoi_commitment",
                    "Selected action by hard constraint and consequence, not by fluency.",
                ),
                _event(
                    12,
                    "state_feedback",
                    "Declared next-state observations and failure conditions for the active frame.",
                ),
            ],
            "final_output": {
                "concise_recommendation": "Do not accept JAILING. Return or preserve JINGALL unless source verification changes.",
                "caveats": [
                    "This demo is deterministic and constraint-scaffolded; it is not an LLM answer."
                ],
                "required_next_discriminators": [
                    "source-token verification",
                    "character-level candidate comparison",
                ],
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


def _build_sea_ivdu_packet(*, input_text: Optional[str]) -> dict[str, Any]:
    text = input_text or (
        "Public MVP v0.4 SEA case: 40s male with non-radicular back pain and history of drug use disorder "
        "including intravenous use. No fever, neurologic deficit, labs, or imaging are supplied in the initial story."
    )
    red_active = True
    contradictions = [
        {
            "id": "benign_back_pain_closure_vs_ivdu_sea_risk",
            "type": "action-threshold contradiction",
            "level": "action_threshold",
            "status": "open_pending_discriminators",
            "observation": "non-radicular benign back-pain narrative competes with intravenous-use SEA risk",
            "conflicts_with": "RED closure requires MRI-level evaluation or a definitive alternative explanation",
            "introduced_at_order": 5,
            "resolution_event_order": None,
        }
    ]

    packet = _base_packet(case_id="sea_ivdu", input_text=text)
    packet.update(
        {
            "observations": [
                "patient=40s_male",
                "pain_pattern=non_radicular_back_pain",
                "risk_feature=history_of_drug_use_disorder_including_intravenous_use",
                "not_supplied=fever",
                "not_supplied=neurologic_deficit",
                "not_supplied=labs",
                "not_supplied=imaging",
            ],
            "constraints": [
                "Hard constraint: intravenous-use history keeps spinal epidural abscess RED open.",
                "Hard constraint: absence of radicular pain does not close SEA risk.",
                "Closure requires MRI-level evaluation or a definitive alternative explanation.",
                "BLUE optimization may only run inside the active SEA RED boundary.",
            ],
            "red_channel": {
                "active_hazards": [
                    {
                        "id": "spinal_epidural_abscess_must_not_miss",
                        "severity": "red",
                        "hazard": "Potential spinal epidural abscess or occult spinal infection.",
                        "features": ["intravenous_use_history"],
                        "closure_requirement": "MRI-level evaluation or definitive alternative explanation",
                    }
                ],
                "ruled_out_hazards": [],
                "missing_discriminators": [
                    "MRI-level evaluation",
                    "definitive alternative explanation for intravenous-use risk",
                    "inflammatory markers and blood-culture context",
                    "focused neurologic reassessment",
                ],
                "escalation_required": red_active,
                "rationale": (
                    "RED runs first because intravenous use is a decisive SEA risk feature; the benign non-radicular "
                    "story cannot close the hazard without the required discriminators."
                ),
            },
            "still": build_still_pathway(
                checkpoint_1_trigger_status="escalation_preserved",
                checkpoint_1_reason="Intravenous-use SEA risk remains active; BLUE cannot downgrade the RED hold.",
                checkpoint_1_required_before_commitment=[
                    "intravenous-use risk feature preserved",
                    "SEA hazard status preserved through BLUE reasoning",
                ],
                checkpoint_2_reason="Benign closure and missing SEA discriminators require retessellation.",
                checkpoint_2_required_before_commitment=[
                    "MRI-level evaluation reviewed or explicitly obtained",
                    "definitive alternative explanation represented",
                    "SEA remains in the hypothesis set until closure threshold is met",
                ],
                red_escalation_required=red_active,
                contradiction_present=red_active,
                denominator_collapse_detected=red_active,
                non_quiescence_possible=red_active,
                zeroback_triggered=red_active,
                learning_notes=[
                    "One decisive risk feature can preserve RED even without fever or neurologic deficit in the story.",
                    "Non-radicular pain is not a closure discriminator for SEA when intravenous-use risk is present.",
                ],
            ),
            "blue_channel": {
                "hypotheses": [
                    {
                        "id": "benign_non_radicular_back_pain",
                        "label": "Benign non-radicular back pain",
                        "likelihood": "surface_plausible",
                        "post_constraint_standing": "red_bounded",
                        "action_priority": "blocked_until_sea_closed",
                        "supporting_features": [
                            "non-radicular pain",
                            "no fever supplied",
                            "no neurologic deficit supplied",
                        ],
                        "contradicting_features": ["intravenous_use_history"],
                        "needed_discriminators": [
                            "MRI-level evaluation",
                            "definitive alternative explanation",
                        ],
                        "action_threshold": "cannot close while SEA RED remains open",
                    },
                    {
                        "id": "spinal_epidural_abscess",
                        "label": "Spinal epidural abscess / occult spinal infection",
                        "likelihood": "uncertain_support",
                        "post_constraint_standing": "action_dominant_by_risk_feature",
                        "action_priority": "red-action-dominant",
                        "supporting_features": ["intravenous_use_history"],
                        "contradicting_features": [
                            "no fever supplied",
                            "no neurologic deficit supplied",
                        ],
                        "needed_discriminators": ["MRI-level evaluation"],
                        "action_threshold": "hold benign closure until RED closure threshold is met",
                    },
                ],
                "evaluation_axes": {
                    "support": {
                        "description": "Evidence or plausibility support only; not action priority.",
                        "by_hypothesis": {
                            "benign_non_radicular_back_pain": "surface_plausible",
                            "spinal_epidural_abscess": "uncertain",
                        },
                    },
                    "action_priority": {
                        "description": "RED/threshold action class only; not a likelihood magnitude.",
                        "by_hypothesis": {
                            "benign_non_radicular_back_pain": "blocked_until_sea_closed",
                            "spinal_epidural_abscess": "red-action-dominant",
                        },
                    },
                },
                "supporting_features": ["non-radicular pain narrative"],
                "contradicting_features": ["intravenous_use_history"],
                "needed_discriminators": [
                    "MRI-level evaluation",
                    "definitive alternative explanation",
                ],
            },
            "contradiction_monitor": _build_contradiction_monitor(
                contradictions=contradictions,
                stability_status="hold_for_mri_level_evaluation",
            ),
            "denominator_collapse": {
                "detected": red_active,
                "missing_hypothesis_classes": [
                    "spinal epidural abscess / occult spinal infection"
                ],
                "retessellation_required": red_active,
            },
            "retessellation_state": _build_retessellation_state(
                required=red_active,
                completed=red_active,
                trigger_event_order=8,
                completed_event_order=9,
                remaining_obligation="next-cycle SEA closure discriminator verification remains pending in the MVP packet",
            ),
            "voronoi_commitment": {
                "recommended_action": (
                    "Hold benign closure; MRI-level evaluation is required to close RED or a definitive alternative "
                    "must explain the intravenous-use risk."
                ),
                "threshold_basis": "Consequence-weighted RED threshold from decisive risk feature, not most-likely pain story.",
                "consequence_weighting": "Missed SEA dominates the cost of evaluation in this public proof case.",
            },
            "non_quiescence": {
                "wrong_manifold_possible": red_active,
                "reason": "Benign back-pain manifold cannot absorb intravenous-use SEA risk without a closure discriminator.",
                "next_required_move": "Retessellate around SEA hazard and obtain closure discriminators before commitment.",
            },
            "zeroback": {
                "triggered": red_active,
                "reason": "Reset from benign back-pain closure to must-not-miss SEA frame.",
                "reset_scope": "Keep pain pattern and risk feature; rebuild hypotheses around SEA closure threshold.",
            },
            "state_feedback": build_state_feedback(
                timestamp_or_phase="mvp_post_commitment_packet",
                active_frame="SEA red-channel risk from intravenous use",
                active_constraints=[
                    "intravenous-use history keeps SEA RED open",
                    "absence of radicular pain does not close SEA risk",
                    "BLUE optimization cannot downgrade unresolved SEA hazard",
                ],
                active_hazards=["spinal_epidural_abscess_must_not_miss"],
                current_commitment="Hold benign closure; MRI-level evaluation is required to close RED.",
                uncertainty_level="high_consequence_unresolved",
                expected_time_window="next SEA closure discriminator collection step",
                expected_changes=[
                    "SEA hazard closes only after MRI-level evaluation or definitive alternative explanation",
                    "RED remains active while closure discriminators are missing",
                ],
                expected_discriminators=[
                    "MRI-level evaluation",
                    "definitive alternative explanation",
                    "inflammatory markers and blood-culture context",
                ],
                expected_resolution_signs=[
                    "MRI-level evaluation addresses SEA hazard",
                    "definitive alternative explains the intravenous-use risk without silent benign closure",
                ],
                failure_conditions=[
                    "benign closure despite intravenous-use risk",
                    "MRI-level evaluation missing",
                    "risk feature omitted from final action threshold",
                    "public packet presented as medical advice",
                ],
                loop_status="pending_observation",
                loop_rationale=(
                    "Retessellation completed inside the MVP packet; the remaining obligation is next-cycle SEA "
                    "closure discriminator verification."
                ),
                next_observation_required="Verify whether MRI-level evaluation or a definitive alternative closes SEA RED.",
                delta_reason=(
                    "No observed next state is available in the MVP; the next clinical state must be checked against "
                    "the unresolved SEA RED hazard."
                ),
                audit_events=[
                    "Declared expected next-state trajectory for SEA risk from intravenous use.",
                    "Defined failure conditions that would force hold, retessellation, or ZeroBack.",
                ],
            ),
            "audit_trace": [
                _event(
                    1,
                    "signal_intake",
                    "Parsed non-radicular back pain and intravenous-use history.",
                ),
                _event(
                    2, "red_channel", "Preserved SEA must-not-miss hazard before BLUE."
                ),
                _event(
                    3,
                    "still_checkpoint_1",
                    "Held benign closure while RED SEA risk remained active.",
                ),
                _event(
                    4,
                    "blue_channel",
                    "Compared benign back pain and SEA hypotheses inside RED boundary.",
                ),
                _event(
                    5,
                    "contradiction_monitor",
                    "Classified benign closure vs IVDU SEA risk as action-threshold contradiction.",
                ),
                _event(
                    6,
                    "denominator_collapse",
                    "Detected omitted occult spinal infection class if only benign pain is considered.",
                ),
                _event(
                    7,
                    "non_quiescence",
                    "Marked wrong-manifold risk from benign closure.",
                ),
                _event(
                    8, "still_checkpoint_2", "Set commitment readiness to retessellate."
                ),
                _event(
                    9,
                    "retessellation",
                    "Rebuilt hypothesis space to include SEA closure threshold.",
                ),
                _event(
                    10,
                    "zeroback",
                    "Reset from benign pain manifold to SEA red-channel frame.",
                ),
                _event(
                    11,
                    "voronoi_commitment",
                    "Committed to RED hold based on consequence-weighted threshold.",
                ),
                _event(
                    12,
                    "state_feedback",
                    "Declared next-state observations and failure conditions for the active frame.",
                ),
            ],
            "final_output": {
                "concise_recommendation": (
                    "Do not close as benign back pain. MRI-level evaluation is required to close RED, unless a "
                    "definitive alternative explanation safely accounts for the intravenous-use risk."
                ),
                "caveats": [
                    "Deterministic public MVP scaffold; not medical advice or a diagnosis."
                ],
                "required_next_discriminators": [
                    "MRI-level evaluation",
                    "definitive alternative explanation",
                    "infection-marker and culture context",
                ],
            },
            "demo_limitations": [
                {
                    "id": "deterministic_sea_red_scaffold",
                    "limitation": (
                        "The SEA packet is a deterministic public governance scaffold, not a diagnostic runtime or "
                        "clinical recommendation."
                    ),
                    "implication": (
                        "It demonstrates RED preservation from a decisive risk feature without observing a live "
                        "patient state or test result."
                    ),
                }
            ],
        }
    )
    return packet


def _build_wirecard_packet(*, input_text: Optional[str]) -> dict[str, Any]:
    text = input_text or (
        "Public MVP v0.4 Wirecard case: reported cash balances are supported by auditor language, market confidence, "
        "and management assurance, but the cash is not independently verified through bank or custodian evidence."
    )
    red_active = True
    contradictions = [
        {
            "id": "authority_assurance_vs_unverified_cash",
            "type": "action-threshold contradiction",
            "level": "action_threshold",
            "status": "open_pending_discriminators",
            "observation": "authority assurances and reported balances compete with missing independent cash evidence",
            "conflicts_with": "RED closure requires independently verifiable bank or custodian evidence",
            "introduced_at_order": 5,
            "resolution_event_order": None,
        }
    ]

    packet = _base_packet(case_id="wirecard", input_text=text)
    packet.update(
        {
            "observations": [
                "reported_cash_balance=large",
                "authority_signal=auditor_language",
                "authority_signal=management_assurance",
                "authority_signal=market_confidence",
                "missing=independent_bank_or_custodian_evidence",
            ],
            "constraints": [
                "Hard constraint: authority language cannot verify cash.",
                "Hard constraint: reported balances remain RED-open until independently verified.",
                "Closure requires independent bank or custodian confirmation or a definitive alternative explanation.",
                "BLUE optimization may only run inside the unverifiable-cash RED boundary.",
            ],
            "red_channel": {
                "active_hazards": [
                    {
                        "id": "unverifiable_cash_must_not_miss",
                        "severity": "red",
                        "hazard": "Material reported cash may be unverifiable.",
                        "features": ["missing_independent_bank_or_custodian_evidence"],
                        "closure_requirement": "independently verifiable bank or custodian evidence",
                    }
                ],
                "ruled_out_hazards": [],
                "missing_discriminators": [
                    "independent bank or custodian confirmation",
                    "direct cash balance evidence from controlled account source",
                    "reconciled third-party statement trail",
                    "definitive alternative explanation for the verification gap",
                ],
                "escalation_required": red_active,
                "rationale": (
                    "RED runs first because reported cash without independent bank or custodian evidence is a governing "
                    "verification hazard; authority signals cannot close it."
                ),
            },
            "still": build_still_pathway(
                checkpoint_1_trigger_status="escalation_preserved",
                checkpoint_1_reason="Unverifiable-cash RED hazard remains active; BLUE cannot treat authority as proof.",
                checkpoint_1_required_before_commitment=[
                    "cash verification gap preserved",
                    "authority assurances kept separate from independent evidence",
                ],
                checkpoint_2_reason="Authority-based closure and missing cash evidence require retessellation.",
                checkpoint_2_required_before_commitment=[
                    "independent bank or custodian confirmation reviewed",
                    "verification source lineage represented",
                    "unverifiable-cash gap remains in the hypothesis set until closed",
                ],
                red_escalation_required=red_active,
                contradiction_present=red_active,
                denominator_collapse_detected=red_active,
                non_quiescence_possible=red_active,
                zeroback_triggered=red_active,
                learning_notes=[
                    "Authority, market confidence, and fluent audit language are not cash evidence.",
                    "The governed denominator must include the missing-verification hypothesis class.",
                ],
            ),
            "blue_channel": {
                "hypotheses": [
                    {
                        "id": "reported_cash_valid",
                        "label": "Reported cash balance is valid",
                        "likelihood": "reported_support",
                        "post_constraint_standing": "blocked_until_independently_verified",
                        "action_priority": "blocked_by_red_boundary",
                        "supporting_features": [
                            "reported balance",
                            "auditor language",
                            "management assurance",
                        ],
                        "contradicting_features": [
                            "missing independent bank or custodian evidence"
                        ],
                        "needed_discriminators": [
                            "independent bank or custodian confirmation"
                        ],
                        "action_threshold": "cannot close while cash verification gap remains",
                    },
                    {
                        "id": "unverifiable_cash_gap",
                        "label": "Reported cash is unverifiable",
                        "likelihood": "uncertain_support",
                        "post_constraint_standing": "action_dominant_by_evidence_gap",
                        "action_priority": "red-action-dominant",
                        "supporting_features": [
                            "missing independent bank or custodian evidence"
                        ],
                        "contradicting_features": [
                            "authority assurances",
                            "market confidence",
                        ],
                        "needed_discriminators": [
                            "independently verifiable bank or custodian evidence"
                        ],
                        "action_threshold": "hold acceptance until independent evidence closes RED",
                    },
                ],
                "evaluation_axes": {
                    "support": {
                        "description": "Evidence or plausibility support only; not action priority.",
                        "by_hypothesis": {
                            "reported_cash_valid": "reported_support",
                            "unverifiable_cash_gap": "uncertain",
                        },
                    },
                    "action_priority": {
                        "description": "RED/threshold action class only; not a likelihood magnitude.",
                        "by_hypothesis": {
                            "reported_cash_valid": "blocked_by_red_boundary",
                            "unverifiable_cash_gap": "red-action-dominant",
                        },
                    },
                },
                "supporting_features": [
                    "reported balance",
                    "authority language",
                    "market confidence",
                ],
                "contradicting_features": [
                    "missing independent bank or custodian evidence"
                ],
                "needed_discriminators": ["independent bank or custodian confirmation"],
            },
            "contradiction_monitor": _build_contradiction_monitor(
                contradictions=contradictions,
                stability_status="hold_for_independent_cash_verification",
            ),
            "denominator_collapse": {
                "detected": red_active,
                "missing_hypothesis_classes": [
                    "unverifiable reported cash / verification gap"
                ],
                "retessellation_required": red_active,
            },
            "retessellation_state": _build_retessellation_state(
                required=red_active,
                completed=red_active,
                trigger_event_order=8,
                completed_event_order=9,
                remaining_obligation="next-cycle independent cash verification remains pending in the MVP packet",
            ),
            "voronoi_commitment": {
                "recommended_action": (
                    "Hold acceptance of reported cash until independently verifiable bank or custodian evidence closes RED."
                ),
                "threshold_basis": "Verification threshold, not authority confidence or narrative fluency.",
                "consequence_weighting": "False acceptance of unverifiable cash dominates reputational or market-comfort costs.",
            },
            "non_quiescence": {
                "wrong_manifold_possible": red_active,
                "reason": "Authority-trust manifold cannot absorb a missing-cash-evidence gap without contradiction.",
                "next_required_move": "Retessellate around independent verification before accepting the reported balance.",
            },
            "zeroback": {
                "triggered": red_active,
                "reason": "Reset from authority-assurance closure to independent-cash-verification frame.",
                "reset_scope": "Keep reported balances and authority signals; rebuild hypotheses around evidence custody.",
            },
            "state_feedback": build_state_feedback(
                timestamp_or_phase="mvp_post_commitment_packet",
                active_frame="unverifiable cash red-channel governance",
                active_constraints=[
                    "authority language cannot verify cash",
                    "reported balances remain RED-open without independent evidence",
                    "BLUE optimization cannot downgrade unresolved verification hazard",
                ],
                active_hazards=["unverifiable_cash_must_not_miss"],
                current_commitment=(
                    "Hold acceptance of reported cash until independently verifiable bank or custodian evidence closes RED."
                ),
                uncertainty_level="material_verification_gap_unresolved",
                expected_time_window="next independent verification step",
                expected_changes=[
                    "cash hazard closes only after independent source evidence",
                    "authority-only assurances remain blocked by RED",
                ],
                expected_discriminators=[
                    "independent bank or custodian confirmation",
                    "controlled account source statement",
                    "reconciled third-party evidence trail",
                ],
                expected_resolution_signs=[
                    "bank or custodian evidence is independently verifiable",
                    "reported balance can be reconciled to a controlled source",
                ],
                failure_conditions=[
                    "authority assurance accepted as proof",
                    "cash balance accepted without independent evidence",
                    "verification source lineage missing",
                    "public packet presented as financial advice",
                ],
                loop_status="pending_observation",
                loop_rationale=(
                    "Retessellation completed inside the MVP packet; the remaining obligation is next-cycle independent "
                    "cash verification."
                ),
                next_observation_required="Verify whether independent bank or custodian evidence closes the cash RED.",
                delta_reason=(
                    "No observed next state is available in the MVP; the next financial governance state must be checked "
                    "against the unresolved cash-verification hazard."
                ),
                audit_events=[
                    "Declared expected next-state trajectory for unverifiable cash.",
                    "Defined failure conditions that would force hold, retessellation, or ZeroBack.",
                ],
            ),
            "audit_trace": [
                _event(
                    1,
                    "signal_intake",
                    "Parsed reported cash, authority signals, and missing independent evidence.",
                ),
                _event(
                    2, "red_channel", "Preserved unverifiable-cash hazard before BLUE."
                ),
                _event(
                    3,
                    "still_checkpoint_1",
                    "Held authority-based closure while cash RED remained active.",
                ),
                _event(
                    4,
                    "blue_channel",
                    "Compared reported-valid and unverifiable-cash hypotheses inside RED boundary.",
                ),
                _event(
                    5,
                    "contradiction_monitor",
                    "Classified authority assurance vs missing cash evidence as action-threshold contradiction.",
                ),
                _event(
                    6,
                    "denominator_collapse",
                    "Detected omitted verification-gap hypothesis class.",
                ),
                _event(
                    7,
                    "non_quiescence",
                    "Marked wrong-manifold risk from authority-trust closure.",
                ),
                _event(
                    8, "still_checkpoint_2", "Set commitment readiness to retessellate."
                ),
                _event(
                    9,
                    "retessellation",
                    "Rebuilt hypothesis space around independent cash evidence.",
                ),
                _event(
                    10,
                    "zeroback",
                    "Reset from authority assurance to cash-verification frame.",
                ),
                _event(
                    11,
                    "voronoi_commitment",
                    "Committed to RED hold based on independent verification threshold.",
                ),
                _event(
                    12,
                    "state_feedback",
                    "Declared next-state observations and failure conditions for the active frame.",
                ),
            ],
            "final_output": {
                "concise_recommendation": (
                    "Do not accept the reported cash as verified. RED stays open until independently verifiable bank "
                    "or custodian evidence closes the cash gap."
                ),
                "caveats": [
                    "Deterministic public MVP scaffold; not financial, accounting, or legal advice."
                ],
                "required_next_discriminators": [
                    "independent bank or custodian confirmation",
                    "controlled account source evidence",
                    "reconciled third-party evidence trail",
                ],
            },
            "demo_limitations": [
                {
                    "id": "deterministic_financial_red_scaffold",
                    "limitation": (
                        "The Wirecard packet is a deterministic public governance scaffold, not a financial, accounting, "
                        "or legal analysis."
                    ),
                    "implication": (
                        "It demonstrates authority-suppression and evidence-custody preservation without adjudicating "
                        "a live company or account record."
                    ),
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
    "PUBLIC_MVP_CASE_IDS",
    "MvpCaseId",
    "build_nepsis_mvp_packet",
]
