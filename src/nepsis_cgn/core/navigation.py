from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Generic, Mapping, Optional, TypeVar

from .constraints import CGNState
from .governor import GovernorConfig, GovernorDecision, ManifoldGovernor
from .interpretant import InterpretantManager, ManifoldEvaluation

SignT = TypeVar("SignT")
StateT = TypeVar("StateT", bound=CGNState)


@dataclass
class NavigationTraceEntry(Generic[SignT, StateT]):
    sign: SignT
    manifold_evaluation: ManifoldEvaluation[StateT]
    governor_decision: GovernorDecision
    posterior: Dict[str, float]
    trace_metadata: Dict[str, Any] = field(default_factory=dict)


class NavigationController(Generic[SignT, StateT]):
    """
    Thin supervisor wiring interpretant → manifold → governor.

    This is intentionally minimal; it keeps per-manifold governor state so
    tension history is preserved across steps.
    """

    def __init__(
        self,
        manager: InterpretantManager[SignT, StateT],
        *,
        governor_configs: Optional[Mapping[str, GovernorConfig]] = None,
        default_governor_config: Optional[GovernorConfig] = None,
    ):
        self.manager = manager
        self._governor_configs = dict(governor_configs or {})
        self._default_config = default_governor_config or GovernorConfig()
        self._governors: Dict[str, ManifoldGovernor[StateT]] = {}
        self.trace: list[NavigationTraceEntry[SignT, StateT]] = []

    def _get_governor(self, manifold_id: str) -> ManifoldGovernor[StateT]:
        if manifold_id in self._governors:
            return self._governors[manifold_id]
        cfg = self._governor_configs.get(manifold_id, self._default_config)
        governor = ManifoldGovernor[StateT](config=cfg)
        self._governors[manifold_id] = governor
        return governor

    def step(self, sign: SignT, *, tension: Optional[float] = None) -> NavigationTraceEntry[SignT, StateT]:
        # Interpretant selects manifold (updates posterior internally).
        manifold = self.manager.select_manifold(sign)
        posterior = self.manager.posterior()

        # Evaluate manifold.
        evaluation = manifold.run(sign)

        # Governor decision using per-manifold state.
        governor = self._get_governor(evaluation.manifold_id)
        decision = governor.evaluate(evaluation, tension=tension)

        trace_entry = NavigationTraceEntry(
            sign=sign,
            manifold_evaluation=evaluation,
            governor_decision=decision,
            posterior=posterior,
            trace_metadata={
                "manifold_id": evaluation.manifold_id,
                "family": evaluation.family,
                "decision": decision.decision,
                "cause": decision.cause,
                "tension": decision.metrics.tension,
                "velocity": decision.metrics.velocity,
                "accel": decision.metrics.accel,
            },
        )
        self.trace.append(trace_entry)
        return trace_entry


__all__ = [
    "NavigationController",
    "NavigationTraceEntry",
]
