from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Optional, TypeVar

from .constraints import CGNState
from .interpretant import ManifoldEvaluation

StateT = TypeVar("StateT", bound=CGNState)


@dataclass
class GovernorConfig:
    tension_warn: float = 1.0
    tension_ruin: float = 2.0
    velocity_shock: float = 5.0
    accel_shock: Optional[float] = None
    max_history: int = 20
    shock_cooldown_steps: int = 0


@dataclass
class TensionMetrics:
    tension: float
    velocity: float
    accel: float


@dataclass
class GovernorState:
    tension_history: List[float] = field(default_factory=list)
    shock_cooldown_remaining: int = 0
    last_manifold_id: Optional[str] = None
    last_family: Optional[str] = None
    last_transforms: List[str] = field(default_factory=list)
    last_ruin_hits: List[str] = field(default_factory=list)

    @property
    def tension(self) -> float:
        return self.tension_history[-1] if self.tension_history else 0.0

    @property
    def tension_velocity(self) -> float:
        if len(self.tension_history) < 2:
            return 0.0
        return self.tension_history[-1] - self.tension_history[-2]

    @property
    def tension_accel(self) -> float:
        if len(self.tension_history) < 3:
            return 0.0
        v1 = self.tension_history[-1] - self.tension_history[-2]
        v0 = self.tension_history[-2] - self.tension_history[-3]
        return v1 - v0

    def add_tension(self, tension: float, *, max_history: int) -> None:
        self.tension_history.append(tension)
        if len(self.tension_history) > max_history:
            overflow = len(self.tension_history) - max_history
            if overflow > 0:
                del self.tension_history[0:overflow]


@dataclass
class GovernorDecision:
    decision: str  # "continue" | "warn" | "collapse" | "ruin"
    cause: Optional[str]
    metrics: TensionMetrics
    metadata: Dict[str, Any]


def default_tension_fn(evaluation: ManifoldEvaluation[Any]) -> float:
    """Map manifold evaluation into a scalar tension."""
    score = 0.0
    severity_weight = {"error": 1.0, "warning": 0.5, "info": 0.1}
    for violation in evaluation.result.violations:
        score += severity_weight.get(violation.severity, 0.5)
    if evaluation.is_ruin:
        score += 2.0
    # Optional richness for puzzle manifolds.
    if "distance" in evaluation.metadata:
        score += float(evaluation.metadata["distance"])
    return score


class ManifoldGovernor(Generic[StateT]):
    """Collapse governor with temporal awareness of tension."""

    def __init__(
        self,
        config: Optional[GovernorConfig] = None,
        tension_fn: Callable[[ManifoldEvaluation[StateT]], float] = default_tension_fn,
    ):
        self.config = config or GovernorConfig()
        self.tension_fn = tension_fn
        self.state = GovernorState()

    def evaluate(
        self,
        evaluation: ManifoldEvaluation[StateT],
        *,
        tension: Optional[float] = None,
    ) -> GovernorDecision:
        cfg = self.config
        computed_tension = tension if tension is not None else self.tension_fn(evaluation)
        self.state.add_tension(computed_tension, max_history=cfg.max_history)
        self.state.last_manifold_id = evaluation.manifold_id
        self.state.last_family = evaluation.family
        self.state.last_transforms = list(evaluation.active_transforms)
        self.state.last_ruin_hits = list(evaluation.ruin_hits)

        metrics = TensionMetrics(
            tension=self.state.tension,
            velocity=self.state.tension_velocity,
            accel=self.state.tension_accel,
        )

        decision = "continue"
        cause: Optional[str] = None

        if evaluation.is_ruin or evaluation.ruin_hits:
            decision, cause = "ruin", "RUIN_NODE"
        elif cfg.accel_shock is not None and metrics.accel >= cfg.accel_shock:
            decision, cause = "collapse", "SHOCK_ACCEL"
        elif metrics.velocity >= cfg.velocity_shock:
            decision, cause = "collapse", "SHOCK_VELOCITY"
            if cfg.shock_cooldown_steps > 0:
                self.state.shock_cooldown_remaining = cfg.shock_cooldown_steps
        elif metrics.tension >= cfg.tension_ruin:
            decision, cause = "collapse", "ABS_TENSION"
        elif metrics.tension >= cfg.tension_warn:
            decision, cause = "warn", "ABS_TENSION"

        if self.state.shock_cooldown_remaining > 0 and decision == "continue":
            self.state.shock_cooldown_remaining -= 1

        metadata = {
            "manifold_id": evaluation.manifold_id,
            "family": evaluation.family,
            "active_transforms": evaluation.active_transforms,
            "ruin_hits": evaluation.ruin_hits,
            "shock_cooldown_remaining": self.state.shock_cooldown_remaining,
        }

        return GovernorDecision(decision=decision, cause=cause, metrics=metrics, metadata=metadata)


__all__ = [
    "GovernorConfig",
    "GovernorDecision",
    "GovernorState",
    "ManifoldGovernor",
    "TensionMetrics",
    "default_tension_fn",
]
