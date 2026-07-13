from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from nepsis_cgn.contracts.canonical_json import canonical_hash


WEIGHT_TOTAL_PPM = 1_000_000
CALIBRATION_ACCEPTANCE_VERSION = "nepsis.calibration_acceptance@0.1.0"
POPULATION_VERSION = "nepsis.population_snapshot@0.1.0"
PREDICTIONS_VERSION = "nepsis.pretest_predictions@0.1.0"
OBSERVATION_VERSION = "nepsis.observation@0.1.0"
UPDATE_VERSION = "nepsis.population_update@0.1.0"
FRAME_VERSION = "nepsis.frame@0.1.0"
PARTICLE_VERSION = "nepsis.particle@0.1.0"
GOVERNANCE_VERSION = "nepsis.governance_decision@0.1.0"


class SemanticVerificationError(ValueError):
    """The bundle is structurally present but semantically inconsistent."""


class UnsupportedSemanticPath(SemanticVerificationError):
    """The bundle uses a deterministic branch not implemented in this slice."""


def verify_semantics(
    events: list[dict[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    subject: Mapping[str, Any],
) -> dict[str, Any]:
    """Independently recompute the supported full-bundle semantic pathway."""

    if not isinstance(events, list) or not events:
        raise SemanticVerificationError("events must be a non-empty array")
    artifact_map = _verified_artifact_map(artifacts)
    if not isinstance(subject, Mapping):
        raise SemanticVerificationError("subject must be an object")

    calibration = _verify_manual_calibration(events, artifact_map, subject)
    inference = _verify_nonresampled_inference(events, artifact_map, subject)
    governance = _verify_governance(events, artifact_map, subject)
    return {
        "valid": True,
        "verified_semantics": [
            "accepted_manual_calibration_materialization",
            "governance_red_blue_recomputation",
            "nonresampled_integer_inference_recomputation",
        ],
        "deliberately_unsupported": [
            "calibration_model_research_or_proposal_quality",
            "denominator_collapse_repair",
            "inference_rejuvenation",
            "inference_resampling",
            "markdown_projection_reconstruction",
        ],
        "calibration": calibration,
        "inference": inference,
        "governance": governance,
    }


def normalize_integer_weights(products: Mapping[str, int]) -> dict[str, int]:
    if not isinstance(products, Mapping) or not products:
        raise SemanticVerificationError("weight products must be non-empty")
    normalized_products: dict[str, int] = {}
    for particle_id, value in products.items():
        _text(particle_id, "particle_id")
        normalized_products[particle_id] = _integer(value, "weight product", minimum=0)
    total = sum(normalized_products.values())
    if total <= 0:
        raise SemanticVerificationError("weight products must contain positive mass")
    provisional: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    for particle_id in sorted(normalized_products):
        numerator = normalized_products[particle_id] * WEIGHT_TOTAL_PPM
        provisional[particle_id] = numerator // total
        remainders.append((numerator % total, particle_id))
    remaining = WEIGHT_TOTAL_PPM - sum(provisional.values())
    for _, particle_id in sorted(
        remainders, key=lambda row: (-row[0], row[1])
    )[:remaining]:
        provisional[particle_id] += 1
    return {particle_id: provisional[particle_id] for particle_id in sorted(provisional)}


def effective_sample_size_fraction_ppm(weights: Mapping[str, int]) -> int:
    if not isinstance(weights, Mapping) or not weights:
        raise SemanticVerificationError("ESS weights must be non-empty")
    values = {
        _text(particle_id, "particle_id"): _ppm(weight, "weight_ppm")
        for particle_id, weight in weights.items()
    }
    if sum(values.values()) != WEIGHT_TOTAL_PPM:
        raise SemanticVerificationError("ESS weights must sum to 1000000")
    sum_squares = sum(weight * weight for weight in values.values())
    if sum_squares <= 0:
        return 0
    result = WEIGHT_TOTAL_PPM**3 // (len(values) * sum_squares)
    return max(0, min(WEIGHT_TOTAL_PPM, result))


def _verify_manual_calibration(
    events: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    subject: Mapping[str, Any],
) -> dict[str, Any]:
    initialized = _one_event(events, "actualization_initialized")
    disposition = _one_event(events, "calibration_proposal_dispositioned")
    committed = _one_event(events, "calibration_committed")
    frozen = _one_event(events, "pretest_predictions_frozen")
    if disposition.get("provenance_class") != "operator":
        raise SemanticVerificationError("calibration disposition is not operator-authored")
    init_payload = _payload(initialized)
    disposition_payload = _payload(disposition)
    commit_payload = _payload(committed)
    frozen_payload = _payload(frozen)

    acceptance_hash = _hash(disposition_payload.get("acceptance_hash"), "acceptance hash")
    acceptance = _artifact(
        artifacts, acceptance_hash, CALIBRATION_ACCEPTANCE_VERSION
    )
    if acceptance.get("disposition") != "manual_override":
        raise UnsupportedSemanticPath(
            "only accepted manual calibration is supported"
        )
    if acceptance.get("confirmed") is not True:
        raise SemanticVerificationError("manual calibration was not confirmed")
    if acceptance.get("operator_actor") != disposition.get("actor"):
        raise SemanticVerificationError("calibration operator binding mismatch")
    if acceptance.get("acknowledged_gap_ids") != []:
        raise SemanticVerificationError("manual calibration cannot acknowledge model gaps")
    if acceptance.get("source_artifact_hashes") != []:
        raise SemanticVerificationError("manual calibration cannot cite a model proposal")

    acceptance_preimage = {
        key: deepcopy(value)
        for key, value in acceptance.items()
        if key
        not in {
            "acceptance_id",
            "calibration_acceptance_schema_version",
        }
    }
    # The manual constructor hashes an explicit empty proposal_hash and then
    # omits that field from the sealed artifact.
    acceptance_preimage["proposal_hash"] = ""
    expected_acceptance_id = (
        "acceptance_" + canonical_hash(acceptance_preimage)[:20]
    )
    if acceptance.get("acceptance_id") != expected_acceptance_id:
        raise SemanticVerificationError("calibration acceptance identity mismatch")

    outcome_ids = _sorted_unique_text(acceptance.get("outcome_ids"), "outcome_ids")
    if len(outcome_ids) < 2:
        raise SemanticVerificationError("calibration requires at least two outcomes")
    priors = _prior_rows(acceptance.get("selected_prior_rows"))
    likelihoods = _likelihood_rows(
        acceptance.get("selected_likelihood_rows"),
        particle_ids=[row["particle_id"] for row in priors],
        outcome_ids=outcome_ids,
    )
    expected_override_paths = sorted(
        [
            f"prior_rows/{row['particle_id']}/weight_ppm"
            for row in priors
        ]
        + [
            "likelihood_rows/"
            f"{row['particle_id']}/{row['outcome_id']}/likelihood_ppm"
            for row in likelihoods
        ]
    )
    if acceptance.get("override_paths") != expected_override_paths:
        raise SemanticVerificationError("manual calibration override paths mismatch")

    particle_hashes = _sorted_unique_hashes(
        init_payload.get("particle_artifact_hashes"), "particle hashes"
    )
    particles = [
        _artifact(artifacts, artifact_hash, PARTICLE_VERSION)
        for artifact_hash in particle_hashes
    ]
    particle_by_id = {str(item["particle_id"]): item for item in particles}
    if sorted(particle_by_id) != [row["particle_id"] for row in priors]:
        raise SemanticVerificationError("calibration particles do not match prior rows")
    particle_refs = [
        {
            "artifact_hash": canonical_hash(particle_by_id[particle_id]),
            "particle_id": particle_id,
        }
        for particle_id in sorted(particle_by_id)
    ]
    weights = {row["particle_id"]: row["weight_ppm"] for row in priors}
    generation = _integer(
        init_payload.get("calibration_generation"),
        "calibration_generation",
        minimum=0,
    )
    parents = _sorted_unique_hashes(
        init_payload.get("calibration_parent_population_hashes"),
        "calibration parents",
    )
    if generation == 0 and parents:
        raise SemanticVerificationError("initial calibration has parent populations")
    checkpoint_kind = "initial" if generation == 0 else "zeroback"
    seed = _text(init_payload.get("seed"), "calibration seed")
    frame_hash = _hash(init_payload.get("frame_hash"), "frame hash")
    population_identity = {
        "acceptance_hash": acceptance_hash,
        "checkpoint_kind": checkpoint_kind,
        "frame_hash": frame_hash,
        "generation": generation,
        "parent_population_hashes": parents,
        "particle_refs": particle_refs,
        "seed": seed,
        "weights": weights,
    }
    inference_policy = _policy(subject, "inference_kernel")
    expected_population = {
        "checkpoint_kind": checkpoint_kind,
        "decision_id": _text(init_payload.get("decision_id"), "decision_id"),
        "generation": generation,
        "kernel_policy_hash": inference_policy["policy_hash"],
        "kernel_policy_version": inference_policy["version"],
        "members": [
            {"particle_id": particle_id, "weight_ppm": weights[particle_id]}
            for particle_id in sorted(weights)
        ],
        "parent_population_hashes": parents,
        "particle_refs": particle_refs,
        "population_id": "population_" + canonical_hash(population_identity)[:20],
        "population_snapshot_schema_version": POPULATION_VERSION,
        "seed": seed,
        "session_id": _text(subject.get("session_id"), "session_id"),
        "source_event_hashes": [disposition["event_hash"]],
        "status": "active",
    }
    population_hash = _hash(commit_payload.get("population_hash"), "population hash")
    population = _artifact(artifacts, population_hash, POPULATION_VERSION)
    if population != expected_population:
        raise SemanticVerificationError(
            "manual calibration population materialization mismatch"
        )

    likelihood_map = {
        (row["particle_id"], row["outcome_id"]): row["likelihood_ppm"]
        for row in likelihoods
    }
    expected_predictions = {
        "decision_id": expected_population["decision_id"],
        "discriminator_id": _text(
            acceptance.get("discriminator_id"), "discriminator_id"
        ),
        "kernel_policy_hash": inference_policy["policy_hash"],
        "kernel_policy_version": inference_policy["version"],
        "outcome_ids": outcome_ids,
        "population_hash": population_hash,
        "pretest_predictions_schema_version": PREDICTIONS_VERSION,
        "rows": [
            {
                "outcome_likelihoods": [
                    {
                        "likelihood_ppm": likelihood_map[(particle_id, outcome_id)],
                        "outcome_id": outcome_id,
                    }
                    for outcome_id in outcome_ids
                ],
                "particle_id": particle_id,
                "source_event_hashes": [disposition["event_hash"]],
            }
            for particle_id in sorted(weights)
        ],
        "seed": seed,
        "session_id": expected_population["session_id"],
        "source_event_hashes": [disposition["event_hash"]],
    }
    predictions_hash = _hash(
        commit_payload.get("predictions_hash"), "predictions hash"
    )
    predictions = _artifact(artifacts, predictions_hash, PREDICTIONS_VERSION)
    if predictions != expected_predictions:
        raise SemanticVerificationError(
            "manual calibration prediction materialization mismatch"
        )
    for label, payload in (("commit", commit_payload), ("freeze", frozen_payload)):
        if (
            payload.get("acceptance_hash") != acceptance_hash
            or payload.get("population_hash") != population_hash
            or payload.get("predictions_hash") != predictions_hash
            or payload.get("discriminator_id") != acceptance.get("discriminator_id")
        ):
            raise SemanticVerificationError(f"calibration {label} binding mismatch")
    return {
        "acceptance_hash": acceptance_hash,
        "population_hash": population_hash,
        "predictions_hash": predictions_hash,
    }


def _verify_nonresampled_inference(
    events: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    subject: Mapping[str, Any],
) -> dict[str, Any]:
    observation_event = _one_event(events, "observation_recorded")
    update_event = _one_event(events, "population_updated")
    observation_payload = _payload(observation_event)
    update_payload = _payload(update_event)
    update_hash = _hash(update_payload.get("update_hash"), "update hash")
    update = _artifact(artifacts, update_hash, UPDATE_VERSION)
    pretest_hash = _hash(update.get("pretest_population_hash"), "pretest hash")
    predictions_hash = _hash(update.get("predictions_hash"), "predictions hash")
    observation_hash = _hash(update.get("observation_hash"), "observation hash")
    pretest = _artifact(artifacts, pretest_hash, POPULATION_VERSION)
    predictions = _artifact(artifacts, predictions_hash, PREDICTIONS_VERSION)
    observation = _artifact(artifacts, observation_hash, OBSERVATION_VERSION)
    if observation_payload.get("observation_hash") != observation_hash:
        raise SemanticVerificationError("observation event binding mismatch")
    if observation.get("discriminator_id") != predictions.get("discriminator_id"):
        raise SemanticVerificationError("observation discriminator mismatch")
    outcome_id = observation.get("outcome_id")
    if outcome_id not in predictions.get("outcome_ids", []):
        raise SemanticVerificationError("observation outcome is not predicted")
    if predictions.get("population_hash") != pretest_hash:
        raise SemanticVerificationError("predictions do not bind pretest population")
    if pretest.get("seed") != predictions.get("seed") or pretest.get("seed") != update.get(
        "seed"
    ):
        raise SemanticVerificationError("inference seed mismatch")

    prior_weights = _member_weights(pretest)
    likelihoods = _observed_likelihoods(predictions, str(outcome_id))
    if sorted(prior_weights) != sorted(likelihoods):
        raise SemanticVerificationError("prediction particle coverage mismatch")
    products = {
        particle_id: prior_weights[particle_id] * likelihoods[particle_id]
        for particle_id in sorted(prior_weights)
    }
    total_product = sum(products.values())
    absolute_fit = total_product // WEIGHT_TOTAL_PPM
    minimum_fit = _ppm(update.get("minimum_absolute_fit_ppm"), "minimum fit")
    collapsed = total_product == 0 or absolute_fit < minimum_fit
    if collapsed:
        raise UnsupportedSemanticPath("denominator collapse is not supported")
    posterior_weights = normalize_integer_weights(products)
    ess = effective_sample_size_fraction_ppm(posterior_weights)
    threshold = _ppm(update.get("resample_ess_threshold_ppm"), "resample threshold")
    if ess < threshold or update.get("resampled") is True:
        raise UnsupportedSemanticPath("resampling is not supported")
    if update.get("rejuvenation_status") != "not_requested":
        raise UnsupportedSemanticPath("rejuvenation is not supported")

    expected_rows = [
        {
            "likelihood_ppm": likelihoods[particle_id],
            "particle_id": particle_id,
            "posterior_weight_ppm": posterior_weights[particle_id],
            "prior_weight_ppm": prior_weights[particle_id],
            "unnormalized_weight": products[particle_id],
        }
        for particle_id in sorted(prior_weights)
    ]
    source_hashes = sorted(
        set(
            pretest["source_event_hashes"]
            + predictions["source_event_hashes"]
            + observation["source_event_hashes"]
            + [observation_event["event_hash"]]
        )
    )
    posterior_identity = {
        "observation_hash": observation_hash,
        "operation": "posttest_update",
        "predictions_hash": predictions_hash,
        "pretest_population_hash": pretest_hash,
    }
    inference_policy = _policy(subject, "inference_kernel")
    expected_posterior = {
        "checkpoint_kind": "posttest",
        "decision_id": pretest["decision_id"],
        "generation": pretest["generation"] + 1,
        "kernel_policy_hash": inference_policy["policy_hash"],
        "kernel_policy_version": inference_policy["version"],
        "members": [
            {
                "particle_id": particle_id,
                "weight_ppm": posterior_weights[particle_id],
            }
            for particle_id in sorted(posterior_weights)
        ],
        "parent_population_hashes": [pretest_hash],
        "particle_refs": deepcopy(pretest["particle_refs"]),
        "population_id": "population_" + canonical_hash(posterior_identity)[:20],
        "population_snapshot_schema_version": POPULATION_VERSION,
        "seed": pretest["seed"],
        "session_id": pretest["session_id"],
        "source_event_hashes": source_hashes,
        "status": "active",
    }
    posterior_hash = _hash(
        update.get("posterior_population_hash"), "posterior population hash"
    )
    result_hash = _hash(update.get("result_population_hash"), "result population hash")
    if posterior_hash != result_hash:
        raise UnsupportedSemanticPath("distinct resampled result is not supported")
    posterior = _artifact(artifacts, posterior_hash, POPULATION_VERSION)
    if posterior != expected_posterior:
        raise SemanticVerificationError("posterior population recomputation mismatch")
    update_identity = {
        "observation_hash": observation_hash,
        "predictions_hash": predictions_hash,
        "pretest_population_hash": pretest_hash,
        "result_population_hash": result_hash,
    }
    expected_update = {
        "absolute_fit_ppm": absolute_fit,
        "denominator_status": "adequate",
        "ess_fraction_ppm": ess,
        "kernel_policy_hash": inference_policy["policy_hash"],
        "kernel_policy_version": inference_policy["version"],
        "minimum_absolute_fit_ppm": minimum_fit,
        "observation_hash": observation_hash,
        "population_update_schema_version": UPDATE_VERSION,
        "posterior_population_hash": posterior_hash,
        "predictions_hash": predictions_hash,
        "pretest_population_hash": pretest_hash,
        "rejuvenation_status": "not_requested",
        "resample_ess_threshold_ppm": threshold,
        "resampled": False,
        "result_population_hash": result_hash,
        "rows": expected_rows,
        "seed": pretest["seed"],
        "session_id": pretest["session_id"],
        "source_event_hashes": source_hashes,
        "update_id": "update_" + canonical_hash(update_identity)[:20],
    }
    if update != expected_update:
        raise SemanticVerificationError("population update recomputation mismatch")
    event_bindings = {
        "denominator_status": "adequate",
        "observation_hash": observation_hash,
        "posterior_population_hash": posterior_hash,
        "predictions_hash": predictions_hash,
        "resampled": False,
        "result_population_hash": result_hash,
        "update_hash": update_hash,
    }
    for field, expected in event_bindings.items():
        if update_payload.get(field) != expected:
            raise SemanticVerificationError(f"population update event {field} mismatch")
    return {
        "absolute_fit_ppm": absolute_fit,
        "ess_fraction_ppm": ess,
        "posterior_population_hash": posterior_hash,
        "update_hash": update_hash,
    }


def _verify_governance(
    events: list[dict[str, Any]],
    artifacts: dict[str, dict[str, Any]],
    subject: Mapping[str, Any],
) -> dict[str, Any]:
    red_event = _one_event(events, "red_governance_evaluated")
    blue_event = _one_event(events, "blue_governance_evaluated")
    decision_event = _one_event(events, "governance_decision_created")
    red_payload = _payload(red_event)
    blue_payload = _payload(blue_event)
    decision_payload = _payload(decision_event)
    governance_hash = _hash(
        red_payload.get("governance_decision_hash"), "governance hash"
    )
    governance = _artifact(artifacts, governance_hash, GOVERNANCE_VERSION)
    projection = _object(subject.get("decision_projection"), "decision projection")
    frame_hash = _hash(projection.get("frame_hash"), "frame hash")
    population_hash = _hash(
        projection.get("current_population_hash"), "population hash"
    )
    frame = _artifact(artifacts, frame_hash, FRAME_VERSION)
    population = _artifact(artifacts, population_hash, POPULATION_VERSION)
    particle_refs = population.get("particle_refs")
    if not isinstance(particle_refs, list):
        raise SemanticVerificationError("population particle refs are missing")
    particles = [
        _artifact(
            artifacts,
            _hash(row.get("artifact_hash"), "particle ref"),
            PARTICLE_VERSION,
        )
        for row in particle_refs
        if isinstance(row, dict)
    ]
    if len(particles) != len(particle_refs):
        raise SemanticVerificationError("particle ref is malformed")
    particle_map = {str(particle["particle_id"]): particle for particle in particles}
    weights = _member_weights(population)
    if sorted(particle_map) != sorted(weights):
        raise SemanticVerificationError("governance particle coverage mismatch")

    credible_mass = _ppm(governance.get("credible_mass_ppm"), "credible mass", minimum=1)
    credible_ids = _credible_particle_ids(weights, credible_mass)
    protected_ids = sorted(
        particle_id
        for particle_id, particle in particle_map.items()
        if any(
            hazard.get("protected") is True
            and hazard.get("status") == "unresolved"
            for hazard in particle.get("red_hazards", [])
            if isinstance(hazard, dict)
        )
    )
    red_particle_ids = sorted(set(credible_ids) | set(protected_ids))
    action_ids = [str(row["action_id"]) for row in frame.get("actions", [])]
    red_rows = [
        _red_action_row(
            action_id=action_id,
            frame=frame,
            red_particle_ids=red_particle_ids,
            particles=particle_map,
        )
        for action_id in action_ids
    ]
    admissible = [row["action_id"] for row in red_rows if row["admissible"]]
    blue_rows = _blue_rows(admissible, particle_map, weights)
    contradictions = _sorted_unique_text(
        governance.get("unresolved_contradictions"), "unresolved contradictions"
    )
    if population.get("status") == "denominator_collapse":
        status = "denominator_collapse"
    elif contradictions or not admissible:
        status = "blocked"
    else:
        status = "ready"
    if status != "ready":
        raise UnsupportedSemanticPath(
            "blocked governance and discriminator selection are not supported"
        )
    ranked = sorted(
        blue_rows,
        key=lambda row: (-row["expected_utility_microunits"], row["action_id"]),
    )
    proposed_action_id = ranked[0]["action_id"]
    predictions_hash = _hash(projection.get("predictions_hash"), "predictions hash")
    source_artifact_hashes = sorted(
        {
            frame_hash,
            population_hash,
            predictions_hash,
            *(canonical_hash(particle) for particle in particles),
        }
    )
    if red_event["sequence"] <= 0:
        raise SemanticVerificationError("RED evaluation has no cause event")
    source_event_hashes = [events[red_event["sequence"] - 1]["event_hash"]]
    governance_identity = {
        "credible_mass_ppm": credible_mass,
        "frame_hash": frame_hash,
        "population_hash": population_hash,
        "red_action_rows": red_rows,
        "unresolved_contradictions": contradictions,
    }
    policy = _policy(subject, "governance_kernel")
    expected_governance = {
        "blue_action_rows": sorted(blue_rows, key=lambda row: row["action_id"]),
        "credible_mass_ppm": credible_mass,
        "credible_particle_ids": sorted(credible_ids),
        "decision_id": frame["decision_id"],
        "frame_hash": frame_hash,
        "governance_decision_schema_version": GOVERNANCE_VERSION,
        "governance_id": "governance_" + canonical_hash(governance_identity)[:20],
        "governance_policy_hash": policy["policy_hash"],
        "governance_policy_version": policy["version"],
        "population_hash": population_hash,
        "proposed_action_id": proposed_action_id,
        "protected_particle_ids": protected_ids,
        "red_action_rows": red_rows,
        "session_id": frame["session_id"],
        "source_artifact_hashes": source_artifact_hashes,
        "source_event_hashes": source_event_hashes,
        "status": "ready",
        "unresolved_contradictions": contradictions,
    }
    if governance != expected_governance:
        raise SemanticVerificationError("governance decision recomputation mismatch")
    if red_payload.get("admissible_action_ids") != admissible:
        raise SemanticVerificationError("RED event admissibility mismatch")
    if red_payload.get("status") != status or red_payload.get(
        "unresolved_contradictions"
    ) != contradictions:
        raise SemanticVerificationError("RED event status mismatch")
    if (
        blue_payload.get("governance_decision_hash") != governance_hash
        or blue_payload.get("proposed_action_id") != proposed_action_id
        or blue_payload.get("red_cause_event_hash") != red_event["event_hash"]
    ):
        raise SemanticVerificationError("BLUE event binding mismatch")
    if (
        decision_payload.get("governance_decision_hash") != governance_hash
        or decision_payload.get("proposed_action_id") != proposed_action_id
        or decision_payload.get("status") != status
    ):
        raise SemanticVerificationError("governance decision event mismatch")
    return {
        "admissible_action_ids": admissible,
        "governance_decision_hash": governance_hash,
        "proposed_action_id": proposed_action_id,
    }


def _red_action_row(
    *,
    action_id: str,
    frame: dict[str, Any],
    red_particle_ids: list[str],
    particles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    for constraint in frame.get("red_constraints", []):
        if not isinstance(constraint, dict):
            raise SemanticVerificationError("frame RED constraint is malformed")
        if constraint.get("status") == "unresolved" and action_id in constraint.get(
            "blocked_action_ids", []
        ):
            blocker_preimage = {
                "action_id": action_id,
                "frame_id": frame["frame_id"],
                "source_id": constraint["constraint_id"],
                "source_kind": "frame_constraint",
            }
            blockers.append(
                {
                    "blocker_id": "blocker_" + canonical_hash(blocker_preimage)[:20],
                    "description": constraint["description"],
                    "frame_id": frame["frame_id"],
                    "protected": constraint["severity"] == "ruin",
                    "severity": constraint["severity"],
                    "source_id": constraint["constraint_id"],
                    "source_kind": "frame_constraint",
                    "waivable": constraint["waivable"],
                }
            )
    for particle_id in red_particle_ids:
        particle = particles[particle_id]
        for hazard in particle.get("red_hazards", []):
            if not isinstance(hazard, dict):
                raise SemanticVerificationError("particle RED hazard is malformed")
            if hazard.get("status") != "unresolved" or action_id not in hazard.get(
                "blocked_action_ids", []
            ):
                continue
            blocker_preimage = {
                "action_id": action_id,
                "particle_id": particle_id,
                "source_id": hazard["hazard_id"],
                "source_kind": "particle_hazard",
            }
            blockers.append(
                {
                    "blocker_id": "blocker_" + canonical_hash(blocker_preimage)[:20],
                    "description": hazard["description"],
                    "frame_id": particle["frame_id"],
                    "particle_id": particle_id,
                    "protected": hazard["protected"],
                    "severity": hazard["severity"],
                    "source_id": hazard["hazard_id"],
                    "source_kind": "particle_hazard",
                    "waivable": hazard["waivable"],
                }
            )
    blockers.sort(key=lambda row: row["blocker_id"])
    return {"action_id": action_id, "admissible": not blockers, "blockers": blockers}


def _blue_rows(
    admissible: list[str],
    particles: dict[str, dict[str, Any]],
    weights: dict[str, int],
) -> list[dict[str, Any]]:
    scores: dict[str, int] = {}
    for action_id in admissible:
        numerator = 0
        for particle_id, particle in particles.items():
            utilities = {
                str(row["action_id"]): _integer(
                    row["utility_microunits"], "utility"
                )
                for row in particle.get("blue_utilities", [])
                if isinstance(row, dict)
            }
            if action_id not in utilities:
                raise SemanticVerificationError("particle utility coverage mismatch")
            numerator += weights[particle_id] * utilities[action_id]
        scores[action_id] = _truncate_division(numerator, WEIGHT_TOTAL_PPM)
    ranked = sorted(scores, key=lambda action_id: (-scores[action_id], action_id))
    rank_by_action = {
        action_id: rank for rank, action_id in enumerate(ranked, start=1)
    }
    return [
        {
            "action_id": action_id,
            "expected_utility_microunits": scores[action_id],
            "rank": rank_by_action[action_id],
        }
        for action_id in sorted(scores)
    ]


def _credible_particle_ids(weights: dict[str, int], threshold: int) -> list[str]:
    selected: list[str] = []
    mass = 0
    for particle_id, weight in sorted(
        weights.items(), key=lambda row: (-row[1], row[0])
    ):
        selected.append(particle_id)
        mass += weight
        if mass >= threshold:
            break
    return selected


def _truncate_division(numerator: int, denominator: int) -> int:
    if numerator >= 0:
        return numerator // denominator
    return -((-numerator) // denominator)


def _verified_artifact_map(
    artifacts: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not isinstance(artifacts, Mapping):
        raise SemanticVerificationError("artifacts must be a hash map")
    result: dict[str, dict[str, Any]] = {}
    for artifact_hash, artifact in artifacts.items():
        _hash(artifact_hash, "artifact hash")
        if not isinstance(artifact, Mapping):
            raise SemanticVerificationError("artifact must be an object")
        row = dict(artifact)
        if canonical_hash(row) != artifact_hash:
            raise SemanticVerificationError("artifact key/hash mismatch")
        result[artifact_hash] = row
    return result


def _artifact(
    artifacts: dict[str, dict[str, Any]], artifact_hash: str, version: str
) -> dict[str, Any]:
    try:
        artifact = artifacts[artifact_hash]
    except KeyError as exc:
        raise SemanticVerificationError(f"missing {version} artifact") from exc
    version_fields = [
        value for key, value in artifact.items() if key.endswith("_schema_version")
    ]
    if version_fields != [version]:
        raise SemanticVerificationError(f"artifact is not {version}")
    return artifact


def _one_event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any]:
    matches = [event for event in events if event.get("event_type") == event_type]
    if len(matches) != 1:
        raise SemanticVerificationError(
            f"expected exactly one {event_type} event"
        )
    return matches[0]


def _payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise SemanticVerificationError("event payload is required")
    return payload


def _policy(subject: Mapping[str, Any], policy_id: str) -> dict[str, str]:
    policies = subject.get("policies")
    if not isinstance(policies, list):
        raise SemanticVerificationError("policy manifest is required")
    matches = [
        policy
        for policy in policies
        if isinstance(policy, dict) and policy.get("policy_id") == policy_id
    ]
    if len(matches) != 1:
        raise SemanticVerificationError(f"missing {policy_id} policy")
    policy = matches[0]
    return {
        "policy_hash": _hash(policy.get("policy_hash"), "policy hash"),
        "version": _text(policy.get("version"), "policy version"),
    }


def _prior_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not 2 <= len(value) <= 6:
        raise SemanticVerificationError("selected priors require two to six rows")
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"particle_id", "weight_ppm"}:
            raise SemanticVerificationError("selected prior row is malformed")
        rows.append(
            {
                "particle_id": _text(item["particle_id"], "particle_id"),
                "weight_ppm": _ppm(item["weight_ppm"], "weight_ppm"),
            }
        )
    if rows != sorted(rows, key=lambda row: row["particle_id"]):
        raise SemanticVerificationError("selected priors must be sorted")
    if len({row["particle_id"] for row in rows}) != len(rows):
        raise SemanticVerificationError("selected priors contain duplicates")
    if sum(row["weight_ppm"] for row in rows) != WEIGHT_TOTAL_PPM:
        raise SemanticVerificationError("selected priors must sum to 1000000")
    return rows


def _likelihood_rows(
    value: Any, *, particle_ids: list[str], outcome_ids: list[str]
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise SemanticVerificationError("selected likelihoods must be an array")
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "likelihood_ppm",
            "outcome_id",
            "particle_id",
        }:
            raise SemanticVerificationError("selected likelihood row is malformed")
        rows.append(
            {
                "likelihood_ppm": _ppm(item["likelihood_ppm"], "likelihood_ppm"),
                "outcome_id": _text(item["outcome_id"], "outcome_id"),
                "particle_id": _text(item["particle_id"], "particle_id"),
            }
        )
    rows.sort(key=lambda row: (row["particle_id"], row["outcome_id"]))
    expected = [(particle_id, outcome_id) for particle_id in particle_ids for outcome_id in outcome_ids]
    actual = [(row["particle_id"], row["outcome_id"]) for row in rows]
    if actual != expected:
        raise SemanticVerificationError("likelihood matrix coverage mismatch")
    for particle_id in particle_ids:
        if sum(
            row["likelihood_ppm"]
            for row in rows
            if row["particle_id"] == particle_id
        ) != WEIGHT_TOTAL_PPM:
            raise SemanticVerificationError("particle likelihoods must sum to 1000000")
    return rows


def _member_weights(population: Mapping[str, Any]) -> dict[str, int]:
    members = population.get("members")
    if not isinstance(members, list) or not members:
        raise SemanticVerificationError("population members are required")
    weights: dict[str, int] = {}
    for member in members:
        if not isinstance(member, dict) or set(member) != {"particle_id", "weight_ppm"}:
            raise SemanticVerificationError("population member is malformed")
        particle_id = _text(member["particle_id"], "particle_id")
        if particle_id in weights:
            raise SemanticVerificationError("population member is duplicated")
        weights[particle_id] = _ppm(member["weight_ppm"], "weight_ppm")
    if list(weights) != sorted(weights) or sum(weights.values()) != WEIGHT_TOTAL_PPM:
        raise SemanticVerificationError("population weights are not canonical")
    return weights


def _observed_likelihoods(
    predictions: Mapping[str, Any], outcome_id: str
) -> dict[str, int]:
    rows = predictions.get("rows")
    if not isinstance(rows, list):
        raise SemanticVerificationError("prediction rows are required")
    result: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SemanticVerificationError("prediction row is malformed")
        particle_id = _text(row.get("particle_id"), "particle_id")
        outcomes = row.get("outcome_likelihoods")
        if not isinstance(outcomes, list):
            raise SemanticVerificationError("outcome likelihoods are required")
        matches = [
            item
            for item in outcomes
            if isinstance(item, dict) and item.get("outcome_id") == outcome_id
        ]
        if len(matches) != 1:
            raise SemanticVerificationError("observed likelihood is not unique")
        result[particle_id] = _ppm(matches[0].get("likelihood_ppm"), "likelihood_ppm")
    return result


def _sorted_unique_text(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise SemanticVerificationError(f"{field} must be a string array")
    if value != sorted(set(value)):
        raise SemanticVerificationError(f"{field} must be sorted and unique")
    return list(value)


def _sorted_unique_hashes(value: Any, field: str) -> list[str]:
    values = _sorted_unique_text(value, field)
    for item in values:
        _hash(item, field)
    return values


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticVerificationError(f"{field} must be an object")
    return dict(value)


def _integer(value: Any, field: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SemanticVerificationError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise SemanticVerificationError(f"{field} is below its minimum")
    return value


def _ppm(value: Any, field: str, *, minimum: int = 0) -> int:
    result = _integer(value, field, minimum=minimum)
    if result > WEIGHT_TOTAL_PPM:
        raise SemanticVerificationError(f"{field} exceeds 1000000")
    return result


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise SemanticVerificationError(f"{field} must be non-empty text")
    return value


def _hash(value: Any, field: str) -> str:
    text = _text(value, field)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise SemanticVerificationError(f"{field} must be a lowercase SHA-256 hash")
    return text


__all__ = [
    "SemanticVerificationError",
    "UnsupportedSemanticPath",
    "effective_sample_size_fraction_ppm",
    "normalize_integer_weights",
    "verify_semantics",
]
