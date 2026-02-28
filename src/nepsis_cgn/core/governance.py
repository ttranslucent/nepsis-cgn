from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Literal, Tuple

Stage = Literal["draft", "called", "reported", "evaluated", "committed"]
Event = Literal["CALL", "REPORT", "EVALUATE", "COMMIT", "ITERATE", "ABDUCT", "RESET_PRIORS"]
Posture = Literal[
    "continue",
    "mixture_mode",
    "collapse_mode",
    "red_override",
    "anti_stall",
    "zeroback",
]
WarningLevel = Literal["green", "yellow", "red"]

EPS = 1e-9


def _clip_unit(value: float, *, label: str) -> float:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{label} must be between 0 and 1 inclusive.")
    return value


def _clip_prior(pi: float) -> float:
    if not 0.0 <= pi <= 1.0:
        raise ValueError("prior_pi must be between 0 and 1 inclusive.")
    return min(max(pi, EPS), 1.0 - EPS)


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def compute_theta(c_fp: float, c_fn: float) -> float:
    if c_fp < 0 or c_fn < 0 or (c_fp + c_fn) <= 0:
        raise ValueError("c_fp and c_fn must be >= 0 and not both zero.")
    return c_fp / (c_fp + c_fn)


def expected_losses(p_bad: float, c_fp: float, c_fn: float) -> Tuple[float, float]:
    _clip_unit(p_bad, label="p_bad")
    theta = compute_theta(c_fp, c_fn)
    del theta  # keep validation path centralized via compute_theta
    loss_treat = (1.0 - p_bad) * c_fp
    loss_notreat = p_bad * c_fn
    return loss_treat, loss_notreat


def posterior_from_lr(prior_pi: float, lr: float) -> float:
    if lr < 0:
        raise ValueError("lr must be >= 0.")
    pi = _clip_prior(prior_pi)
    odds = pi / (1.0 - pi)
    post_odds = odds * lr
    return post_odds / (1.0 + post_odds)


def posterior_from_score(prior_pi: float, score_s: float, a: float, b: float) -> float:
    pi = _clip_prior(prior_pi)
    logit_prior = math.log(pi) - math.log(1.0 - pi)
    logit_post = logit_prior + (a + b * score_s)
    return sigmoid(logit_post)


@dataclass(frozen=True)
class GovernanceCosts:
    c_fp: float
    c_fn: float

    def theta(self) -> float:
        return compute_theta(self.c_fp, self.c_fn)


@dataclass(frozen=True)
class GovernanceCalibration:
    """
    Logistic calibration for p_bad from interpretable governance features.
    """

    prior_pi: float = 0.1
    intercept: float = 0.0
    slope: float = 1.0
    w_violation_pressure: float = 1.4
    w_ambiguity_pressure: float = 1.0
    w_contradiction_density: float = 0.8
    w_entropy: float = 0.4
    w_margin_collapse: float = 0.6
    version: str = "logit-v1"

    def validate(self) -> None:
        _clip_prior(self.prior_pi)
        if self.slope <= 0.0:
            raise ValueError("calibration slope must be > 0.")

    def score(
        self,
        *,
        violation_pressure: float,
        ambiguity_pressure: float,
        contradiction_density: float,
        posterior_entropy_norm: float,
        top_margin: float,
    ) -> float:
        _clip_unit(violation_pressure, label="violation_pressure")
        _clip_unit(ambiguity_pressure, label="ambiguity_pressure")
        _clip_unit(contradiction_density, label="contradiction_density")
        _clip_unit(posterior_entropy_norm, label="posterior_entropy_norm")
        _clip_unit(top_margin, label="top_margin")
        margin_collapse = 1.0 - top_margin
        return (
            self.w_violation_pressure * violation_pressure
            + self.w_ambiguity_pressure * ambiguity_pressure
            + self.w_contradiction_density * contradiction_density
            + self.w_entropy * posterior_entropy_norm
            + self.w_margin_collapse * margin_collapse
        )

    def probability(
        self,
        *,
        violation_pressure: float,
        ambiguity_pressure: float,
        contradiction_density: float,
        posterior_entropy_norm: float,
        top_margin: float,
    ) -> float:
        self.validate()
        score_s = self.score(
            violation_pressure=violation_pressure,
            ambiguity_pressure=ambiguity_pressure,
            contradiction_density=contradiction_density,
            posterior_entropy_norm=posterior_entropy_norm,
            top_margin=top_margin,
        )
        return posterior_from_score(
            prior_pi=self.prior_pi,
            score_s=score_s,
            a=self.intercept,
            b=self.slope,
        )


@dataclass(frozen=True)
class GovernanceMetrics:
    p_bad: float
    ruin_mass: float
    contradiction_density: float
    posterior_entropy_norm: float
    top_margin: float
    top_p: float | None = None
    aux_assumption_load: float | None = None
    zeroback_count: int = 0
    filter_ess: float | None = None
    hotspot_score: float | None = None

    def validate(self) -> None:
        _clip_unit(self.p_bad, label="p_bad")
        _clip_unit(self.ruin_mass, label="ruin_mass")
        _clip_unit(self.contradiction_density, label="contradiction_density")
        _clip_unit(self.posterior_entropy_norm, label="posterior_entropy_norm")
        if self.top_p is not None:
            _clip_unit(self.top_p, label="top_p")
        if self.zeroback_count < 0:
            raise ValueError("zeroback_count must be >= 0.")


@dataclass(frozen=True)
class GovernanceContext:
    contradiction_streak: int = 0
    mixture_dwell_iters: int = 0
    stable_iters: int = 0

    def validate(self) -> None:
        if self.contradiction_streak < 0:
            raise ValueError("contradiction_streak must be >= 0.")
        if self.mixture_dwell_iters < 0:
            raise ValueError("mixture_dwell_iters must be >= 0.")
        if self.stable_iters < 0:
            raise ValueError("stable_iters must be >= 0.")


@dataclass(frozen=True)
class GovernanceThresholds:
    tau_red: float = 0.25
    eps_margin: float = 0.08
    h_high: float = 0.6
    c_high: float = 0.35
    c_ok: float = 0.15
    tau_collapse: float = 0.8
    eps_collapse: float = 0.2
    max_dwell_iters: int = 3
    zeroback_limit: int = 2
    contradiction_streak_min: int = 2
    stable_iters_required: int = 2
    yellow_factor: float = 0.8

    def validate(self) -> None:
        _clip_unit(self.tau_red, label="tau_red")
        _clip_unit(self.h_high, label="h_high")
        _clip_unit(self.c_high, label="c_high")
        _clip_unit(self.c_ok, label="c_ok")
        _clip_unit(self.tau_collapse, label="tau_collapse")
        _clip_unit(self.yellow_factor, label="yellow_factor")
        if self.max_dwell_iters < 0:
            raise ValueError("max_dwell_iters must be >= 0.")
        if self.zeroback_limit < 0:
            raise ValueError("zeroback_limit must be >= 0.")
        if self.contradiction_streak_min < 0:
            raise ValueError("contradiction_streak_min must be >= 0.")
        if self.stable_iters_required < 0:
            raise ValueError("stable_iters_required must be >= 0.")


@dataclass(frozen=True)
class GovernanceDecision:
    posture: Posture
    warning_level: WarningLevel
    recommended_action: str
    trigger_codes: Tuple[str, ...]
    theta: float
    loss_treat: float
    loss_notreat: float
    details: Dict[str, float]


def evaluate_governance_policy(
    metrics: GovernanceMetrics,
    costs: GovernanceCosts,
    *,
    context: GovernanceContext | None = None,
    thresholds: GovernanceThresholds | None = None,
) -> GovernanceDecision:
    metrics.validate()
    ctx = context or GovernanceContext()
    ctx.validate()
    th = thresholds or GovernanceThresholds()
    th.validate()

    theta = costs.theta()
    loss_treat, loss_notreat = expected_losses(metrics.p_bad, costs.c_fp, costs.c_fn)

    trigger_codes: List[str] = []
    red_condition = metrics.ruin_mass >= th.tau_red or metrics.p_bad >= theta
    if metrics.ruin_mass >= th.tau_red:
        trigger_codes.append("RUIN_MASS_HIGH")
    if metrics.p_bad >= theta:
        trigger_codes.append("COST_GATE_CROSSED")

    if red_condition:
        return GovernanceDecision(
            posture="red_override",
            warning_level="red",
            recommended_action="escalate_red",
            trigger_codes=tuple(trigger_codes),
            theta=theta,
            loss_treat=loss_treat,
            loss_notreat=loss_notreat,
            details={"p_bad": metrics.p_bad, "ruin_mass": metrics.ruin_mass},
        )

    recurrence_condition = (
        ctx.mixture_dwell_iters > th.max_dwell_iters
        and ctx.contradiction_streak >= th.contradiction_streak_min
        and metrics.contradiction_density > th.c_high
    )
    if metrics.zeroback_count >= th.zeroback_limit or recurrence_condition:
        return GovernanceDecision(
            posture="zeroback",
            warning_level="red",
            recommended_action="reset_priors",
            trigger_codes=("RECURRENCE_PATTERN",),
            theta=theta,
            loss_treat=loss_treat,
            loss_notreat=loss_notreat,
            details={
                "zeroback_count": float(metrics.zeroback_count),
                "recurrence_condition": float(1.0 if recurrence_condition else 0.0),
            },
        )

    mixture_by_margin = metrics.top_margin < th.eps_margin and metrics.posterior_entropy_norm > th.h_high
    mixture_by_contradiction = (
        metrics.contradiction_density > th.c_high
        and ctx.contradiction_streak >= th.contradiction_streak_min
    )
    mixture_mode = mixture_by_margin or mixture_by_contradiction
    if mixture_by_margin:
        trigger_codes.extend(("MARGIN_COLLAPSE", "HIGH_ENTROPY_NO_DISCRIMINATOR"))
    if mixture_by_contradiction:
        trigger_codes.append("CONTRADICTION_PERSISTENCE")

    if mixture_mode and ctx.mixture_dwell_iters > th.max_dwell_iters:
        return GovernanceDecision(
            posture="anti_stall",
            warning_level="yellow",
            recommended_action="run_test",
            trigger_codes=tuple(sorted(set(trigger_codes + ["ANTI_STALL"]))),
            theta=theta,
            loss_treat=loss_treat,
            loss_notreat=loss_notreat,
            details={"mixture_dwell_iters": float(ctx.mixture_dwell_iters)},
        )

    collapse_mode = False
    if metrics.top_p is not None:
        collapse_mode = (
            metrics.top_p >= th.tau_collapse
            and metrics.top_margin >= th.eps_collapse
            and metrics.contradiction_density <= th.c_ok
            and ctx.stable_iters >= th.stable_iters_required
        )

    if collapse_mode:
        return GovernanceDecision(
            posture="collapse_mode",
            warning_level="green",
            recommended_action="collapse",
            trigger_codes=(),
            theta=theta,
            loss_treat=loss_treat,
            loss_notreat=loss_notreat,
            details={
                "top_p": float(metrics.top_p if metrics.top_p is not None else 0.0),
                "top_margin": metrics.top_margin,
            },
        )

    if mixture_mode:
        return GovernanceDecision(
            posture="mixture_mode",
            warning_level="yellow",
            recommended_action="abduct",
            trigger_codes=tuple(sorted(set(trigger_codes))),
            theta=theta,
            loss_treat=loss_treat,
            loss_notreat=loss_notreat,
            details={
                "top_margin": metrics.top_margin,
                "posterior_entropy_norm": metrics.posterior_entropy_norm,
            },
        )

    warning_level: WarningLevel = "green"
    if metrics.p_bad >= th.yellow_factor * theta:
        warning_level = "yellow"

    return GovernanceDecision(
        posture="continue",
        warning_level=warning_level,
        recommended_action="continue",
        trigger_codes=(),
        theta=theta,
        loss_treat=loss_treat,
        loss_notreat=loss_notreat,
        details={"p_bad": metrics.p_bad},
    )


class IterationStateMachine:
    """
    Event-driven state machine for one Nepsis iteration.
    """

    _TRANSITIONS: Dict[Tuple[Stage, Event], Stage] = {
        ("draft", "CALL"): "called",
        ("called", "REPORT"): "reported",
        ("reported", "EVALUATE"): "evaluated",
        ("evaluated", "COMMIT"): "committed",
        ("evaluated", "ITERATE"): "draft",
        ("committed", "ITERATE"): "draft",
        # The following start the next iteration at draft while preserving lineage.
        ("evaluated", "ABDUCT"): "draft",
        ("evaluated", "RESET_PRIORS"): "draft",
        ("committed", "ABDUCT"): "draft",
        ("committed", "RESET_PRIORS"): "draft",
    }

    def __init__(self, stage: Stage = "draft") -> None:
        self._stage: Stage = stage

    @property
    def stage(self) -> Stage:
        return self._stage

    def valid_events(self) -> Tuple[Event, ...]:
        events: List[Event] = []
        for (stage, event), _ in self._TRANSITIONS.items():
            if stage == self._stage:
                events.append(event)
        return tuple(events)

    def can_apply(self, event: Event) -> bool:
        return (self._stage, event) in self._TRANSITIONS

    def apply(self, event: Event) -> Stage:
        key = (self._stage, event)
        if key not in self._TRANSITIONS:
            valid = ", ".join(self.valid_events()) or "none"
            raise ValueError(f"Invalid transition: {self._stage} + {event}. Valid events: {valid}.")
        self._stage = self._TRANSITIONS[key]
        return self._stage


__all__ = [
    "Event",
    "GovernanceCalibration",
    "GovernanceContext",
    "GovernanceCosts",
    "GovernanceDecision",
    "GovernanceMetrics",
    "GovernanceThresholds",
    "IterationStateMachine",
    "Posture",
    "Stage",
    "WarningLevel",
    "compute_theta",
    "evaluate_governance_policy",
    "expected_losses",
    "posterior_from_lr",
    "posterior_from_score",
    "sigmoid",
]
