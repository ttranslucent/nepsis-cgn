from __future__ import annotations

import hashlib
from typing import Any, Mapping, Sequence
from urllib.parse import quote, urlsplit, urlunsplit

from nepsis_cgn.contracts.canonical_json import canonical_hash


MARKDOWN_EXPORT_VERSION = "nepsis.markdown_decision_journey@0.2.0"
CALIBRATION_MAX_TURNS = 4


class MarkdownReconstructionError(ValueError):
    pass


def verify_markdown_reconstruction(subject: Mapping[str, Any]) -> str:
    """Reconstruct and compare the claimed Markdown body and digest exactly."""

    claimed = subject.get("markdown")
    claimed_hash = subject.get("markdown_hash")
    if subject.get("markdown_included") is not True or not isinstance(claimed, str):
        raise MarkdownReconstructionError("full subject must include Markdown")
    if not isinstance(claimed_hash, str):
        raise MarkdownReconstructionError("subject markdown_hash is required")
    reconstructed = reconstruct_subject_markdown(subject)
    reconstructed_hash = markdown_sha256(reconstructed)
    if reconstructed != claimed:
        raise MarkdownReconstructionError(
            "subject Markdown does not match detached reconstruction"
        )
    if reconstructed_hash != claimed_hash:
        raise MarkdownReconstructionError(
            "subject markdown_hash does not match detached reconstruction"
        )
    return reconstructed


def reconstruct_subject_markdown(subject: Mapping[str, Any]) -> str:
    events = _object_array(subject.get("audit_events"), "audit_events")
    rows = _object_array(subject.get("artifact_rows"), "artifact_rows")
    state = _object(subject.get("decision_projection"), "decision_projection")
    phase = _object(subject.get("phase_projection"), "phase_projection")
    session_id = _text(subject.get("session_id"), "session_id")
    artifacts = _artifact_map(rows)
    return reconstruct_markdown(
        session_id=session_id,
        events=events,
        artifacts=artifacts,
        decision_projection=state,
        phase_projection=phase,
    )


def reconstruct_markdown(
    *,
    session_id: str,
    events: Sequence[Mapping[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    decision_projection: Mapping[str, Any],
    phase_projection: Mapping[str, Any],
) -> str:
    """Render 0.2 Markdown using only detached verified inputs."""

    event_rows = [dict(event) for event in events]
    artifact_map = {key: dict(value) for key, value in artifacts.items()}
    state = dict(decision_projection)
    phase = dict(phase_projection)
    if not event_rows:
        raise MarkdownReconstructionError("audit_events must not be empty")
    if state.get("initialized") is not True:
        raise MarkdownReconstructionError("actualization has not been initialized")
    calibration = _project_calibration_state(event_rows)

    frame = _artifact(artifact_map, state.get("frame_hash"), "active frame")
    frame_lineage = _artifact(
        artifact_map, state.get("frame_lineage_hash"), "frame lineage"
    )
    particle_lineage = _artifact(
        artifact_map, state.get("particle_lineage_hash"), "particle lineage"
    )
    population = (
        _artifact(
            artifact_map, state.get("current_population_hash"), "current population"
        )
        if state.get("current_population_hash")
        else None
    )
    if population is not None:
        particle_hashes = [row["artifact_hash"] for row in population["particle_refs"]]
    else:
        particle_hashes = sorted(
            node["artifact_hash"]
            for node in particle_lineage["nodes"]
            if node["state"] == "active"
        )
    particles = [
        _artifact(artifact_map, artifact_hash, "particle")
        for artifact_hash in particle_hashes
    ]
    particle_map = {particle["particle_id"]: particle for particle in particles}
    observations = [
        _artifact(artifact_map, artifact_hash, "observation")
        for artifact_hash in state.get("observation_hashes", [])
    ]
    prediction_episodes = _artifact_episodes(
        artifact_map,
        event_rows,
        event_type="pretest_predictions_frozen",
        artifact_field="predictions_hash",
    )
    update_episodes = _artifact_episodes(
        artifact_map,
        event_rows,
        event_type="population_updated",
        artifact_field="update_hash",
    )
    governance_episodes = _artifact_episodes(
        artifact_map,
        event_rows,
        event_type="governance_decision_created",
        artifact_field="governance_decision_hash",
    )
    research_episodes = _artifact_episodes(
        artifact_map,
        event_rows,
        event_type="calibration_research_completed",
        artifact_field="research_hash",
    )
    proposal_episodes = _artifact_episodes(
        artifact_map,
        event_rows,
        event_type="calibration_proposal_created",
        artifact_field="proposal_hash",
    )
    acceptance_episodes = _artifact_episodes(
        artifact_map,
        event_rows,
        event_type="calibration_proposal_dispositioned",
        artifact_field="acceptance_hash",
    )
    governance = (
        _artifact(
            artifact_map,
            state.get("governance_decision_hash"),
            "governance decision",
        )
        if state.get("governance_decision_hash")
        else None
    )

    lines = [
        "# Nepsis Decision Journey",
        "",
        f"- Export version: `{MARKDOWN_EXPORT_VERSION}`",
        f"- Session: `{_inline(session_id)}`",
        f"- Decision: `{_inline(frame['decision_id'])}`",
        f"- Phase: `{_inline(phase['projected_phase'])}`",
        f"- Status: `{_inline(state['status'])}`",
        f"- Audit events: `{len(event_rows)}`",
        f"- Audit tip: `{event_rows[-1]['event_hash']}`",
        "",
        "## Decision",
        "",
        frame["question"],
        "",
        f"Denominator: {frame['denominator']}",
        "",
        f"Time horizon: {frame['time_horizon']}",
        "",
        "| Action | RED | BLUE rank | Expected utility | Decision state |",
        "|---|---|---:|---:|---|",
    ]
    red_by_action = (
        {row["action_id"]: row for row in governance["red_action_rows"]}
        if governance
        else {}
    )
    blue_by_action = (
        {row["action_id"]: row for row in governance["blue_action_rows"]}
        if governance
        else {}
    )
    for action in frame["actions"]:
        action_id = action["action_id"]
        red = red_by_action.get(action_id)
        blue = blue_by_action.get(action_id)
        red_label = (
            "admissible"
            if red and red["admissible"]
            else f"blocked ({len(red['blockers'])})"
            if red
            else "not evaluated"
        )
        if state.get("committed_action_id") == action_id:
            decision_state = "committed"
        elif state.get("proposed_action_id") == action_id:
            decision_state = "proposed"
        else:
            decision_state = "not selected"
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(f"{action['label']} (`{action_id}`)"),
                    _cell(red_label),
                    str(blue["rank"]) if blue else "—",
                    str(blue["expected_utility_microunits"]) if blue else "—",
                    _cell(decision_state),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Active Frame",
            "",
            f"- Frame ID: `{_inline(frame['frame_id'])}`",
            f"- Frame artifact: `{state['frame_hash']}`",
            f"- Assumptions: `{len(frame['assumptions'])}`",
            f"- RED constraints: `{len(frame['red_constraints'])}`",
            f"- Discriminators: `{len(frame['discriminators'])}`",
        ]
    )
    if frame["assumptions"]:
        lines.extend(["", "Assumptions:"])
        lines.extend(f"- {assumption}" for assumption in frame["assumptions"])

    lines.extend(
        [
            "",
            "## Frame History",
            "",
            "| State | Frame | Question | Denominator | Artifact |",
            "|---|---|---|---|---|",
        ]
    )
    for node in frame_lineage["nodes"]:
        historical_frame = _artifact(
            artifact_map, node["artifact_hash"], "historical frame"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(node["state"]),
                    f"`{_inline(node['frame_id'])}`",
                    _cell(historical_frame["question"]),
                    _cell(historical_frame["denominator"]),
                    f"`{node['artifact_hash']}`",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Model-Led Calibration",
            "",
            f"- Cycle: `{_inline(calibration['cycle_id'] or 'not available')}`",
            f"- Status: `{_inline(calibration['status'])}`",
            f"- Context authorized: `{'yes' if calibration['context_authorized'] else 'no'}`",
            f"- Research scope: `{_inline(calibration['research_scope'])}`",
            f"- Completed proposal turns: `{calibration['turn_count']} / {calibration['max_turns']}`",
        ]
    )
    for sequence, artifact_hash, research, source_event in research_episodes:
        lines.extend(
            [
                "",
                f"### Research turn {research['turn_index']} — sequence {sequence}",
                "",
                f"- As of: `{_inline(research['as_of_utc'])}`",
                f"- Model: `{_inline(research['model_id'])}`",
                f"- Scope: `{_inline(research['research_scope'])}`",
                f"- Artifact: `{artifact_hash}`",
            ]
        )
        for source in research["sources"]:
            lines.append(
                f"- Evidence `{_inline(source['source_id'])}`: "
                f"[{_link_text(source['title'])}]({_safe_http_url(source['url'])})"
            )
    for sequence, artifact_hash, proposal, source_event in proposal_episodes:
        lines.extend(
            [
                "",
                f"### Proposal turn {proposal['turn_index']} — sequence {sequence}",
                "",
                f"- Readiness: `{_inline(proposal['readiness'])}`",
                f"- Summary: {proposal['summary']}",
                f"- Model rationale: {proposal['satisfaction_rationale']}",
                f"- Artifact: `{artifact_hash}`",
                "",
                "| Prior particle | Minimum ppm | Working ppm | Maximum ppm | Basis |",
                "|---|---:|---:|---:|---|",
            ]
        )
        for row in proposal["prior_rows"]:
            lines.append(
                f"| `{_inline(row['particle_id'])}` | {row['min_ppm']} | "
                f"{row['recommended_ppm']} | {row['max_ppm']} | "
                f"{_cell(row['basis']['basis_kind'])} |"
            )
        lines.extend(
            [
                "",
                "| Likelihood particle | Outcome | Minimum ppm | Working ppm | Maximum ppm | Basis |",
                "|---|---|---:|---:|---:|---|",
            ]
        )
        for row in proposal["likelihood_rows"]:
            lines.append(
                f"| `{_inline(row['particle_id'])}` | `{_inline(row['outcome_id'])}` | "
                f"{row['min_ppm']} | {row['recommended_ppm']} | {row['max_ppm']} | "
                f"{_cell(row['basis']['basis_kind'])} |"
            )
        for question in proposal["questions"]:
            lines.append(
                f"- {'Blocking' if question['blocking'] else 'Nonblocking'} question "
                f"`{_inline(question['question_id'])}`: {question['prompt']}"
            )
        for gap_id in proposal["blocking_gap_ids"]:
            lines.append(f"- Blocking gap: `{_inline(gap_id)}`")
    for sequence, artifact_hash, acceptance, source_event in acceptance_episodes:
        lines.extend(
            [
                "",
                f"### Operator disposition — sequence {sequence}",
                "",
                f"- Disposition: `{_inline(acceptance['disposition'])}`",
                f"- Confirmed: `{'yes' if acceptance['confirmed'] else 'no'}`",
                f"- Rationale: {acceptance['operator_rationale']}",
                f"- Acceptance artifact: `{artifact_hash}`",
                "- Changed values: "
                + (
                    ", ".join(
                        f"`{_inline(path)}`" for path in acceptance["override_paths"]
                    )
                    if acceptance["override_paths"]
                    else "none"
                ),
                "- Acknowledged model gaps/questions: "
                + (
                    ", ".join(
                        f"`{_inline(gap_id)}`"
                        for gap_id in acceptance["acknowledged_gap_ids"]
                    )
                    if acceptance["acknowledged_gap_ids"]
                    else "none"
                ),
            ]
        )
    if not proposal_episodes and not acceptance_episodes:
        lines.extend(
            [
                "",
                "No model calibration proposal or explicit manual override has been committed.",
            ]
        )

    lines.extend(["", "## Frozen Predictions", ""])
    if prediction_episodes:
        for sequence, artifact_hash, predictions, source_event in prediction_episodes:
            episode_state = _episode_state(
                artifact_hash,
                current_hash=str(state.get("predictions_hash", "")),
                stale_hashes=list(state.get("stale_artifact_hashes", [])),
            )
            lines.extend(
                [
                    f"### Sequence {sequence} — `{_inline(predictions['discriminator_id'])}` "
                    f"({episode_state})",
                    "",
                    f"- Population: `{predictions['population_hash']}`",
                    f"- Seed: `{_inline(predictions['seed'])}`",
                    f"- Authority: `{_inline(source_event['actor'])}` "
                    f"(`{_inline(source_event['provenance_class'])}`)",
                    "",
                    "| Particle | Outcome | Frozen likelihood ppm |",
                    "|---|---|---:|",
                ]
            )
            for row in predictions["rows"]:
                for outcome in row["outcome_likelihoods"]:
                    lines.append(
                        f"| `{_inline(row['particle_id'])}` | "
                        f"`{_inline(outcome['outcome_id'])}` | {outcome['likelihood_ppm']} |"
                    )
            lines.append("")
        if lines[-1] == "":
            lines.pop()
    else:
        lines.append("No pretest predictions frozen.")

    lines.extend(["", "## Active Contradictions", ""])
    active_contradictions = state.get("unresolved_contradictions", [])
    if active_contradictions:
        lines.extend(f"- {contradiction}" for contradiction in active_contradictions)
    else:
        lines.append(
            "No unresolved contradiction is carried in the current projection."
        )

    lines.extend(["", "## Observations", ""])
    if observations:
        lines.extend(
            [
                "| Observation | Discriminator | Outcome | Source | Observed at |",
                "|---|---|---|---|---|",
            ]
        )
        for observation in observations:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _cell(observation["observation_id"]),
                        _cell(observation["discriminator_id"]),
                        _cell(observation["outcome_id"]),
                        _cell(
                            f"{observation['source_class']} · {observation['source_ref']}"
                        ),
                        _cell(observation["observed_at"]),
                    ]
                )
                + " |"
            )
        limitations = [
            (observation["observation_id"], limitation)
            for observation in observations
            for limitation in observation["limitations"]
        ]
        if limitations:
            lines.extend(["", "Observation limitations:"])
            lines.extend(
                f"- `{_inline(observation_id)}`: {limitation}"
                for observation_id, limitation in limitations
            )
    else:
        lines.append("No observations recorded.")

    lines.extend(["", "## Particle Trajectory", ""])
    if update_episodes:
        for sequence, artifact_hash, episode_update, source_event in update_episodes:
            episode_state = _episode_state(
                artifact_hash,
                current_hash=str(state.get("update_hash", "")),
                stale_hashes=list(state.get("stale_artifact_hashes", [])),
            )
            lines.extend(
                [
                    f"### Update at sequence {sequence} — "
                    f"`{_inline(episode_update['update_id'])}` ({episode_state})",
                    "",
                    f"- Absolute fit: `{episode_update['absolute_fit_ppm']} ppm`",
                    f"- Minimum absolute fit: `{episode_update['minimum_absolute_fit_ppm']} ppm`",
                    f"- Effective sample-size fraction: `{episode_update['ess_fraction_ppm']} ppm`",
                    f"- Resample threshold: `{episode_update['resample_ess_threshold_ppm']} ppm`",
                    f"- Denominator status: `{episode_update['denominator_status']}`",
                    f"- Resampled: `{'yes' if episode_update['resampled'] else 'no'}`",
                    f"- Rejuvenation: `{episode_update['rejuvenation_status']}`",
                    f"- Seed: `{_inline(episode_update['seed'])}`",
                    f"- Pretest population: `{episode_update['pretest_population_hash']}`",
                    f"- Frozen predictions: `{episode_update['predictions_hash']}`",
                    f"- Observation: `{episode_update['observation_hash']}`",
                    f"- Posterior population: `{episode_update['posterior_population_hash']}`",
                    f"- Result population: `{episode_update['result_population_hash']}`",
                    f"- Authority: `{_inline(source_event['actor'])}` "
                    f"(`{_inline(source_event['provenance_class'])}`)",
                    "",
                    "| Particle | Prior ppm | Likelihood ppm | Posterior ppm |",
                    "|---|---:|---:|---:|",
                ]
            )
            for row in episode_update["rows"]:
                lines.append(
                    f"| `{_inline(row['particle_id'])}` | {row['prior_weight_ppm']} | "
                    f"{row['likelihood_ppm']} | {row['posterior_weight_ppm']} |"
                )
            lines.append("")
        if lines[-1] == "":
            lines.pop()
    else:
        lines.append("No post-test update committed.")

    lines.extend(["", "Current population:", ""])
    if population is None:
        lines.append("No inference-active population exists; calibration remains pending.")
    else:
        lines.extend(
            [
                "| Particle | Weight ppm | Frame | Hypothesis | RED hazards |",
                "|---|---:|---|---|---:|",
            ]
        )
        for member in population["members"]:
            particle = particle_map[member["particle_id"]]
            unresolved_hazards = sum(
                hazard["status"] == "unresolved" for hazard in particle["red_hazards"]
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{_inline(particle['particle_id'])}`",
                        str(member["weight_ppm"]),
                        f"`{_inline(particle['frame_id'])}`",
                        _cell(particle["hypothesis"]),
                        str(unresolved_hazards),
                    ]
                )
                + " |"
            )

    lines.extend(["", "## RED Governance", ""])
    if governance:
        for row in governance["red_action_rows"]:
            if row["admissible"]:
                lines.append(f"- `{_inline(row['action_id'])}`: admissible.")
                continue
            lines.append(f"- `{_inline(row['action_id'])}`: blocked.")
            for blocker in row["blockers"]:
                provenance = blocker["source_kind"]
                if "particle_id" in blocker:
                    provenance += f" `{_inline(blocker['particle_id'])}`"
                lines.append(
                    f"  - `{_inline(blocker['source_id'])}` "
                    f"({blocker['severity']}, {provenance}): {blocker['description']}"
                )
        if governance["protected_particle_ids"]:
            lines.append(
                "- Protected particles outside ordinary collapse: "
                + ", ".join(
                    f"`{_inline(particle_id)}`"
                    for particle_id in governance["protected_particle_ids"]
                )
                + "."
            )
    else:
        lines.append("RED has not been evaluated.")

    lines.extend(["", "## BLUE Governance", ""])
    if governance and governance["blue_action_rows"]:
        for row in sorted(
            governance["blue_action_rows"], key=lambda item: item["rank"]
        ):
            lines.append(
                f"{row['rank']}. `{_inline(row['action_id'])}` — "
                f"`{row['expected_utility_microunits']}` utility microunits."
            )
    elif governance:
        lines.append(
            "No BLUE ranking is selectable because RED or denominator state blocks commitment."
        )
    else:
        lines.append("BLUE has not been evaluated.")

    lines.extend(["", "## Governance Episodes", ""])
    if governance_episodes:
        for sequence, artifact_hash, episode, source_event in governance_episodes:
            event_payload = source_event.get("payload", {})
            episode_state = _episode_state(
                artifact_hash,
                current_hash=str(state.get("governance_decision_hash", "")),
                stale_hashes=list(state.get("stale_artifact_hashes", [])),
            )
            lines.append(
                f"- Sequence `{sequence}` — `{_inline(episode['governance_id'])}`: "
                f"`{_inline(episode['status'])}` ({episode_state})."
            )
            lines.append(f"  - Frame: `{episode['frame_hash']}`.")
            lines.append(f"  - Population: `{episode['population_hash']}`.")
            lines.append(
                f"  - Authority: `{_inline(source_event['actor'])}` "
                f"(`{_inline(source_event['provenance_class'])}`)."
            )
            if episode["unresolved_contradictions"]:
                for contradiction in episode["unresolved_contradictions"]:
                    lines.append(f"  - Unresolved contradiction: {contradiction}")
            else:
                lines.append("  - Unresolved contradictions: none recorded.")
            if episode.get("proposed_action_id"):
                lines.append(
                    "  - Proposed RED-admissible action: "
                    f"`{_inline(episode['proposed_action_id'])}`."
                )
            if episode.get("next_discriminator_id"):
                lines.append(
                    f"  - Next discriminator: `{_inline(episode['next_discriminator_id'])}`."
                )
            for row in episode["red_action_rows"]:
                if row["admissible"]:
                    lines.append(f"  - RED `{_inline(row['action_id'])}`: admissible.")
                    continue
                lines.append(f"  - RED `{_inline(row['action_id'])}`: blocked.")
                for blocker in row["blockers"]:
                    lines.append(
                        f"    - `{_inline(blocker['source_id'])}` "
                        f"({blocker['severity']}, {blocker['source_kind']}): "
                        f"{blocker['description']}"
                    )
            for row in sorted(
                episode["blue_action_rows"], key=lambda item: item["rank"]
            ):
                lines.append(
                    f"  - BLUE rank `{row['rank']}`: `{_inline(row['action_id'])}` "
                    f"at `{row['expected_utility_microunits']}` utility microunits."
                )
            resolved = (
                event_payload.get("resolved_contradictions", [])
                if isinstance(event_payload, dict)
                else []
            )
            if isinstance(resolved, list) and resolved:
                lines.append(
                    "  - Resolved contradictions: "
                    + ", ".join(f"`{_inline(item)}`" for item in resolved)
                    + "."
                )
                lines.append(
                    "  - Resolution rationale: "
                    + str(event_payload.get("contradiction_resolution_rationale", ""))
                )
    else:
        lines.append("No governance decision episode recorded.")

    lines.extend(["", "## Commitment and Repair", ""])
    governance_events: dict[str, list[dict[str, Any]]] = {
        "hold_placed": [],
        "hold_released": [],
        "decision_committed": [],
        "zeroback_performed": [],
    }
    for event in event_rows:
        if event["event_type"] in governance_events:
            governance_events[event["event_type"]].append(event)
    for placed in governance_events["hold_placed"]:
        payload = placed.get("payload", {})
        lines.append(
            f"- STILL `{_inline(payload.get('hold_id', 'unknown'))}` placed at "
            f"sequence `{placed['sequence']}` by `{_inline(placed['actor'])}` "
            f"(`{_inline(placed['provenance_class'])}`): {payload.get('rationale', '')}"
        )
        if payload.get("governance_decision_hash"):
            lines.append(
                f"  - Governance decision: `{payload['governance_decision_hash']}`."
            )
    for released in governance_events["hold_released"]:
        payload = released.get("payload", {})
        lines.append(
            f"- STILL `{_inline(payload.get('hold_id', 'unknown'))}` released at "
            f"sequence `{released['sequence']}` by `{_inline(released['actor'])}` "
            f"(`{_inline(released['provenance_class'])}`): {payload.get('rationale', '')}"
        )
    for committed in governance_events["decision_committed"]:
        lines.append(
            f"- Decision committed: `{_inline(committed['payload']['action_id'])}` "
            f"at sequence `{committed['sequence']}` — "
            f"{committed['payload']['rationale']}"
        )
    for zeroback in governance_events["zeroback_performed"]:
        payload = zeroback.get("payload", {})
        lines.append(
            f"- ZeroBack at sequence `{zeroback['sequence']}`: "
            f"{payload.get('rationale', '')} Observations and provenance were preserved."
        )
        manifest = payload.get("carry_forward_manifest")
        if isinstance(manifest, dict):
            lines.append(
                "  - Carry-forward manifest: "
                f"`{payload.get('carry_forward_manifest_hash', 'missing')}` "
                f"(`{_inline(manifest.get('carry_forward_manifest_version', 'unknown'))}`)."
            )
            constraint_ids = [
                row.get("constraint", {}).get("constraint_id", "")
                for row in manifest.get("protected_frame_constraints", [])
                if isinstance(row, dict)
            ]
            hazard_ids = [
                row.get("hazard", {}).get("hazard_id", "")
                for row in manifest.get("protected_particle_hazards", [])
                if isinstance(row, dict)
            ]
            contradictions = manifest.get("unresolved_contradictions", [])
            lines.append(
                "  - Protected frame constraints carried: "
                + (
                    ", ".join(f"`{_inline(item)}`" for item in constraint_ids if item)
                    or "none"
                )
                + "."
            )
            lines.append(
                "  - Protected particle hazards carried: "
                + (
                    ", ".join(f"`{_inline(item)}`" for item in hazard_ids if item)
                    or "none"
                )
                + "."
            )
            lines.append(
                "  - Unresolved contradictions carried: "
                + (
                    ", ".join(f"`{_inline(item)}`" for item in contradictions)
                    if isinstance(contradictions, list) and contradictions
                    else "none"
                )
                + "."
            )
            preserved_observations = payload.get("preserved_observation_hashes", [])
            stale_artifacts = payload.get("stale_artifact_hashes", [])
            lines.append(
                "  - Preserved observations: "
                + (
                    ", ".join(
                        f"`{_inline(item)}`" for item in preserved_observations
                    )
                    if isinstance(preserved_observations, list)
                    and preserved_observations
                    else "none"
                )
                + "."
            )
            lines.append(
                "  - Staled downstream artifacts: "
                + (
                    ", ".join(f"`{_inline(item)}`" for item in stale_artifacts)
                    if isinstance(stale_artifacts, list) and stale_artifacts
                    else "none"
                )
                + "."
            )
    if not any(governance_events.values()):
        lines.append("No STILL, commitment, or ZeroBack event recorded.")

    lines.extend(
        [
            "",
            "## Lineage",
            "",
            "- Frame lineage root(s): "
            + ", ".join(
                f"`{_inline(root)}`" for root in frame_lineage["roots"]
            ),
            f"- Frame lineage edges: `{len(frame_lineage['edges'])}`",
            "- Particle lineage root(s): "
            + ", ".join(
                f"`{_inline(root)}`" for root in particle_lineage["roots"]
            ),
            f"- Particle lineage edges: `{len(particle_lineage['edges'])}`",
        ]
    )
    for edge in frame_lineage["edges"]:
        lines.append(
            f"- Frame `{_inline(edge['from_frame_id'])}` —{edge['edge_kind']}→ "
            f"`{_inline(edge['to_frame_id'])}`; cause `{edge['cause_event_hash']}`."
        )
    for edge in particle_lineage["edges"]:
        slot = (
            f"; resample slot `{edge['resample_slot']}`"
            if "resample_slot" in edge
            else ""
        )
        lines.append(
            f"- Particle `{_inline(edge['from_particle_id'])}` —{edge['edge_kind']}→ "
            f"`{_inline(edge['to_particle_id'])}`; cause `{edge['cause_event_hash']}`"
            f"{slot}."
        )

    lines.extend(
        [
            "",
            "## Verification",
            "",
            f"- Foundation contract: `{event_rows[0]['payload']['foundation_contract_version']}`",
            f"- Actualization contract: `{state['actualization_contract_version']}`",
            f"- Frame lineage hash: `{state['frame_lineage_hash']}`",
            f"- Particle lineage hash: `{state['particle_lineage_hash']}`",
            f"- Current population hash: `{state['current_population_hash']}`",
            "- Governance decision hash: "
            f"`{state.get('governance_decision_hash') or 'not_created'}`",
            "- Audit chain verification: `passed`",
            "- Canonical rows identify observation sources and event authority; this report does not attest factual or clinical correctness.",
            "",
        ]
    )
    return "\n".join(lines)


def markdown_sha256(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def _artifact_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        artifact_hash = row.get("artifact_hash")
        artifact = row.get("artifact")
        if not isinstance(artifact_hash, str) or not isinstance(artifact, dict):
            raise MarkdownReconstructionError(
                f"artifact row {index} lacks included content"
            )
        if row.get("included") is not True:
            raise MarkdownReconstructionError("Markdown reconstruction requires full artifacts")
        if artifact_hash in artifacts:
            raise MarkdownReconstructionError("duplicate artifact hash")
        if canonical_hash(artifact) != artifact_hash:
            raise MarkdownReconstructionError("artifact hash mismatch")
        artifacts[artifact_hash] = artifact
    return artifacts


def _artifact(
    artifacts: Mapping[str, dict[str, Any]], artifact_hash: Any, label: str
) -> dict[str, Any]:
    if not isinstance(artifact_hash, str) or not artifact_hash:
        raise MarkdownReconstructionError(f"{label} hash is missing")
    try:
        return artifacts[artifact_hash]
    except KeyError as exc:
        raise MarkdownReconstructionError(f"{label} artifact is missing") from exc


def _artifact_episodes(
    artifacts: Mapping[str, dict[str, Any]],
    events: list[dict[str, Any]],
    *,
    event_type: str,
    artifact_field: str,
) -> list[tuple[int, str, dict[str, Any], dict[str, Any]]]:
    episodes: list[tuple[int, str, dict[str, Any], dict[str, Any]]] = []
    seen: set[str] = set()
    for event in events:
        if event.get("event_type") != event_type:
            continue
        payload = event.get("payload")
        artifact_hash = (
            payload.get(artifact_field) if isinstance(payload, dict) else None
        )
        if not isinstance(artifact_hash, str) or not artifact_hash:
            raise MarkdownReconstructionError(
                f"{event_type} event lacks {artifact_field}"
            )
        if artifact_hash in seen:
            continue
        sequence = event.get("sequence")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise MarkdownReconstructionError(
                f"{event_type} event lacks an integer sequence"
            )
        episodes.append(
            (
                sequence,
                artifact_hash,
                _artifact(artifacts, artifact_hash, event_type),
                event,
            )
        )
        seen.add(artifact_hash)
    return episodes


def _episode_state(
    artifact_hash: str, *, current_hash: str, stale_hashes: list[str]
) -> str:
    if artifact_hash in set(stale_hashes):
        return "stale after ZeroBack"
    if artifact_hash == current_hash:
        return "current"
    return "historical"


def _project_calibration_state(events: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "cycle_id": "",
        "context_authorized": False,
        "context_authorization_event_hash": "",
        "context_authorization_sequence": -1,
        "research_scope": "curated",
        "turn_count": 0,
        "max_turns": CALIBRATION_MAX_TURNS,
        "latest_research_hash": "",
        "latest_proposal_hash": "",
        "readiness": "not_started",
        "blocking_gap_ids": [],
        "questions": [],
        "acceptance_hash": "",
        "disposition": "",
        "status": "not_available",
        "committed_population_hash": "",
        "committed_predictions_hash": "",
        "last_sequence": -1,
    }
    for event in events:
        sequence = event.get("sequence")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            state["last_sequence"] = max(state["last_sequence"], sequence)
        event_type = event.get("event_type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type in {"actualization_initialized", "zeroback_performed"}:
            state.update(
                {
                    "cycle_id": _value_text(payload.get("calibration_cycle_id")),
                    "context_authorized": False,
                    "context_authorization_event_hash": "",
                    "context_authorization_sequence": -1,
                    "research_scope": "curated",
                    "turn_count": 0,
                    "latest_research_hash": "",
                    "latest_proposal_hash": "",
                    "readiness": "not_started",
                    "blocking_gap_ids": [],
                    "questions": [],
                    "acceptance_hash": "",
                    "disposition": "",
                    "status": "pending",
                    "committed_population_hash": "",
                    "committed_predictions_hash": "",
                }
            )
        elif event_type == "calibration_context_authorized":
            state["context_authorized"] = payload.get("confirmed") is True
            state["context_authorization_event_hash"] = _value_text(
                event.get("event_hash")
            )
            state["context_authorization_sequence"] = (
                sequence
                if isinstance(sequence, int) and not isinstance(sequence, bool)
                else -1
            )
            state["research_scope"] = (
                _value_text(payload.get("research_scope")) or "curated"
            )
            state["status"] = "authorized"
        elif event_type == "calibration_research_scope_changed":
            state["research_scope"] = (
                _value_text(payload.get("research_scope")) or state["research_scope"]
            )
            state["context_authorized"] = False
            state["status"] = "authorization_required"
        elif event_type == "calibration_research_completed":
            state["latest_research_hash"] = _value_text(payload.get("research_hash"))
            state["status"] = "research_complete"
        elif event_type == "calibration_proposal_created":
            state["turn_count"] += 1
            state["latest_proposal_hash"] = _value_text(payload.get("proposal_hash"))
            state["readiness"] = _value_text(payload.get("readiness"))
            state["blocking_gap_ids"] = _sorted_text(payload.get("blocking_gap_ids"))
            questions = payload.get("questions")
            state["questions"] = questions if isinstance(questions, list) else []
            state["status"] = (
                "turn_limit_reached"
                if state["turn_count"] >= CALIBRATION_MAX_TURNS
                and state["readiness"] != "ready_for_operator_review"
                else state["readiness"]
            )
        elif event_type == "calibration_proposal_dispositioned":
            state["acceptance_hash"] = _value_text(payload.get("acceptance_hash"))
            state["disposition"] = _value_text(payload.get("disposition"))
            state["status"] = "accepted"
        elif event_type == "calibration_committed":
            state["committed_population_hash"] = _value_text(
                payload.get("population_hash")
            )
            state["committed_predictions_hash"] = _value_text(
                payload.get("predictions_hash")
            )
            state["status"] = "committed"
        elif (
            event.get("provenance_class") == "operator"
            and event_type != "calibration_proposal_dispositioned"
            and state["cycle_id"]
            and state["status"] != "committed"
        ):
            state["context_authorized"] = False
            state["status"] = "authorization_required"
    return state


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _inline(value: Any) -> str:
    return str(value).replace("`", "\\`").replace("\n", " ")


def _link_text(value: Any) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("\n", " ")
    )


def _safe_http_url(value: Any) -> str:
    if not isinstance(value, str) or any(character.isspace() for character in value):
        return ""
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    safe_path = quote(parsed.path, safe="/%:@-._~!$&'*+,;=")
    safe_query = quote(parsed.query, safe="=&%:@/?-._~!$'*,;+")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, safe_path, safe_query, ""))


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MarkdownReconstructionError(f"{label} must be an object")
    return value


def _object_array(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise MarkdownReconstructionError(f"{label} must be an object array")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MarkdownReconstructionError(f"{label} must be a non-empty string")
    return value


def _value_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _sorted_text(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item})


__all__ = [
    "MARKDOWN_EXPORT_VERSION",
    "MarkdownReconstructionError",
    "markdown_sha256",
    "reconstruct_markdown",
    "reconstruct_subject_markdown",
    "verify_markdown_reconstruction",
]
