"""Core manifold primitives for NepsisCGN.

This package defines light-weight schema helpers so new manifolds can be
expressed declaratively (dimensions + constraint packs) while still compiling
down to the existing :mod:`nepsis_cgn.core` constraint machinery.
"""

from __future__ import annotations

import ast
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
        values = getattr(state, "to_dict", lambda: {})()
        try:
            passed = bool(_evaluate_constraint_expression(self.definition.rule, values))
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


def _evaluate_constraint_expression(rule: str, values: Dict[str, Any]) -> Any:
    tree = ast.parse(rule, mode="eval")
    return _eval_ast_node(tree.body, values)


def _eval_ast_node(node: ast.AST, values: Dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (bool, int, float, str)) or node.value is None:
            return node.value
        raise ValueError(f"unsupported constant type: {type(node.value).__name__}")

    if isinstance(node, ast.Name):
        if node.id in values:
            return values[node.id]
        if node.id in {"True", "False", "None"}:
            return {"True": True, "False": False, "None": None}[node.id]
        raise ValueError(f"unknown rule name: {node.id}")

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_ast_node(node.operand, values)

    if isinstance(node, ast.BoolOp):
        return _eval_bool_op(node, values)

    if isinstance(node, ast.Compare):
        left = _eval_ast_node(node.left, values)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_ast_node(comparator, values)
            if not _compare_values(left, op, right):
                return False
            left = right
        return True

    raise ValueError(f"unsupported rule expression: {type(node).__name__}")


def _eval_bool_op(node: ast.BoolOp, values: Dict[str, Any]) -> Any:
    if isinstance(node.op, ast.And):
        result: Any = True
        for item in node.values:
            result = _eval_ast_node(item, values)
            if not result:
                return result
        return result

    if isinstance(node.op, ast.Or):
        result: Any = False
        for item in node.values:
            result = _eval_ast_node(item, values)
            if result:
                return result
        return result

    raise ValueError(f"unsupported boolean operator: {type(node.op).__name__}")


def _compare_values(left: Any, op: ast.cmpop, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    if isinstance(op, ast.Lt):
        return left < right
    if isinstance(op, ast.LtE):
        return left <= right
    if isinstance(op, ast.Gt):
        return left > right
    if isinstance(op, ast.GtE):
        return left >= right
    if isinstance(op, ast.Is):
        return left is right
    if isinstance(op, ast.IsNot):
        return left is not right
    raise ValueError(f"unsupported comparison operator: {type(op).__name__}")


__all__ = [
    "ConstraintPackDefinition",
    "ConstraintRuleDefinition",
    "DictBackedState",
    "ExpressionConstraint",
    "ManifoldDefinition",
    "ManifoldDimension",
    "build_constraint_set_from_pack",
]
