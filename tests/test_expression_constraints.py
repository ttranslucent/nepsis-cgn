from __future__ import annotations

from nepsis_cgn.manifolds import ConstraintRuleDefinition, DictBackedState, ExpressionConstraint


def _rule(rule: str, *, rule_type: str = "hard") -> ExpressionConstraint:
    return ExpressionConstraint(
        ConstraintRuleDefinition(
            id="T1",
            type=rule_type,  # type: ignore[arg-type]
            rule=rule,
            description="Test rule",
        )
    )


def test_expression_constraint_evaluates_allowed_boolean_rule() -> None:
    constraint = _rule("(explanation_quality or 0) >= 0.7")

    assert constraint.check(DictBackedState({"explanation_quality": 0.9})) == []
    violations = constraint.check(DictBackedState({"explanation_quality": None}))

    assert len(violations) == 1
    assert violations[0].code == "T1"
    assert violations[0].severity == "error"


def test_expression_constraint_rejects_function_calls() -> None:
    constraint = _rule("__import__('os').system('true') == 0")

    violations = constraint.check(DictBackedState({}))

    assert len(violations) == 1
    assert violations[0].code == "rule_eval_error"
    assert "unsupported rule expression" in violations[0].message


def test_expression_constraint_rejects_attribute_access() -> None:
    constraint = _rule("name.__class__ == str")

    violations = constraint.check(DictBackedState({"name": "JINGALL"}))

    assert len(violations) == 1
    assert violations[0].code == "rule_eval_error"
