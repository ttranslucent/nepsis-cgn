from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Protocol


@dataclass
class ConstraintViolation:
    """
    A single violation of a constraint.

    For NepsisCGN this is where we will eventually add:
    - consequence weighting
    - Red/Blue classification
    - geometry metadata (which region/surface was hit)
    """

    message: str
    code: str = "generic"
    severity: str = "error"  # "warning" | "info" | "error"
    metadata: Dict[str, Any] | None = None


class CGNState(Protocol):
    """
    Minimal protocol for a state object in NepsisCGN.
    Domain-specific states (e.g., word puzzles, grids) will implement this.
    """

    def describe(self) -> str:
        ...


class Constraint(Protocol):
    """
    Abstract constraint.

    A constraint inspects a state and returns zero or more violations.
    No side-effects, pure evaluation.
    """

    name: str

    def check(self, state: CGNState) -> List[ConstraintViolation]:
        ...


@dataclass
class ConstraintSet:
    """
    A collection of constraints that can be applied to a state.

    This is our basic "geometry surface": a definition of what it means
    to be valid in a particular region.
    """

    name: str
    constraints: List[Constraint]

    def evaluate(self, state: CGNState) -> List[ConstraintViolation]:
        violations: List[ConstraintViolation] = []
        for constraint in self.constraints:
            violations.extend(constraint.check(state))
        return violations
