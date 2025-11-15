from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from .constraints import CGNState, ConstraintSet, ConstraintViolation


@dataclass
class SolverResult:
    """
    Result of running NepsisCGN over a single state.

    Later we can add:
    - alternative candidate states
    - navigation traces
    - ZeroBack reset metadata
    """

    is_valid: bool
    violations: List[ConstraintViolation]
    state_description: str
    metadata: Dict[str, Any]


class CGNSolver:
    """
    Thin orchestrator for constraint evaluation.

    For now, this is single-state, single-pass.
    Later:
    - multi-step navigation
    - LLM-interaction hooks
    - temporal recursion guards (ZeroBack)
    """

    def __init__(self, constraint_set: ConstraintSet):
        self.constraint_set = constraint_set

    def evaluate_state(self, state: CGNState) -> SolverResult:
        violations = self.constraint_set.evaluate(state)
        is_valid = not any(v.severity == "error" for v in violations)
        return SolverResult(
            is_valid=is_valid,
            violations=violations,
            state_description=state.describe(),
            metadata={
                "constraint_set": self.constraint_set.name,
                "violation_count": len(violations),
            },
        )
