"""Core manifold primitives for NepsisCGN.

This package defines light-weight schema helpers so new manifolds can be
expressed declaratively (dimensions + constraint packs) while still compiling
down to the existing :mod:`nepsis_cgn.core` constraint machinery.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from ..core.constraints import CGNState, Constraint, ConstraintSet, ConstraintViolation

DimensionType = Literal["boolean", "float", "integer", "string"]
ConstraintRuleType = Literal["hard", "soft"]


@dataclass(frozen=True)
class ManifoldDimension:
    name: str
    type: DimensionType
    description: Optional[str] = None


@dataclass(frozen=True)
class ConstraintRuleDefinition:
    id: str
    type: ConstraintRuleType
    rule: str
    description: str
    weight: Optional[float] = None


@dataclass(frozen=True)
class ConstraintPackDefinition:
    id: str
    constraints: List[ConstraintRuleDefinition]


@dataclass(frozen=True)
class ManifoldDefinition:
    id: str
    name: str
    dimensions: List[ManifoldDimension]
    constraint_packs: List[ConstraintPackDefinition]

    def pack_ids(self) -> List[str]:
        return [pack.id for pack in self.constraint_packs]

    def get_pack(self, pack_id: str) -> ConstraintPackDefinition:
        for pack in self.constraint_packs:
            if pack.id == pack_id:
                return pack
        raise ValueError(f"Constraint pack '{pack_id}' not found in manifold '{self.id}'.")


class DictBackedState:
    """Generic :class:`CGNState` backed by a Python dictionary."""

    def __init__(self, values: Dict[str, Any]):
        self._values = values

    def describe(self) -> str:
        return json.dumps(self._values, sort_keys=True, default=str)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._values)

    def __getitem__(self, key: str) -> Any:
        return self._values[key]


class ExpressionConstraint(Constraint):
    def __init__(self, rule: ConstraintRuleDefinition):
        self.definition = rule
        self.name = rule.id

    def check(self, state: DictBackedState) -> List[ConstraintViolation]:
        values = getattr(state, "to_dict", lambda: {} )()
        try:
            passed = bool(eval(self.definition.rule, {"__builtins__": {}}, values))
        except Exception as exc:  # pragma: no cover - defensive guard
            return [
                ConstraintViolation(
                    message=f"Failed to evaluate rule '{self.definition.rule}': {exc}",
                    code="rule_eval_error",
                    severity="error",
                    metadata={"rule": self.definition.rule},
                )
            ]

        if passed:
            return []

        severity = "error" if self.definition.type == "hard" else "warning"
        return [
            ConstraintViolation(
                message=self.definition.description,
                code=self.definition.id,
                severity=severity,
                metadata={
                    "rule": self.definition.rule,
                    "weight": self.definition.weight,
                    "constraint_type": self.definition.type,
                },
            )
        ]


def build_constraint_set_from_pack(
    pack: ConstraintPackDefinition,
    *,
    label: Optional[str] = None,
) -> ConstraintSet:
    constraints: List[Constraint] = [ExpressionConstraint(rule) for rule in pack.constraints]
    name = label or pack.id
    return ConstraintSet(name=name, constraints=constraints)


__all__ = [
    "ConstraintPackDefinition",
    "ConstraintRuleDefinition",
    "DictBackedState",
    "ExpressionConstraint",
    "ManifoldDefinition",
    "ManifoldDimension",
    "build_constraint_set_from_pack",
]
