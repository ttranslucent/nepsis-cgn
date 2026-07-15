from __future__ import annotations

import pytest

from nepsis_cgn.contracts.governance_profile import (
    GovernanceProfileError,
    comparator_policy_hash,
    compare_values,
    resolve_override,
    validate_maximum_tolerated_severity,
    validate_rule_override_mode,
)


@pytest.mark.parametrize(
    ("field", "inherited", "proposed"),
    [
        ("maximum_tolerated_severity", 3, 2),
        ("evidence_floor", "one_source", "corroborated"),
        ("evidence_requirement", "standard", "strict"),
        ("reversibility_requirement", "preferred", "required"),
        ("loss_posture", "balanced", "ruin_averse"),
    ],
)
def test_closed_comparators_recognize_tightening(
    field: str,
    inherited: object,
    proposed: object,
) -> None:
    assert (
        compare_values(field=field, inherited=inherited, proposed=proposed)
        == "tighter"
    )
    assert (
        compare_values(field=field, inherited=proposed, proposed=inherited)
        == "weaker"
    )


def test_data_scope_uses_declared_subset_relation() -> None:
    scopes = {
        "cleared_remote": frozenset({"public", "operator_cleared"}),
        "public_only": frozenset({"public"}),
        "local_notes": frozenset({"local_notes"}),
    }
    assert compare_values(
        field="data_scope",
        inherited="cleared_remote",
        proposed="public_only",
        data_scopes=scopes,
    ) == "tighter"
    assert compare_values(
        field="data_scope",
        inherited="public_only",
        proposed="local_notes",
        data_scopes=scopes,
    ) == "incomparable"


def test_criterion_sets_allow_addition_but_not_removal() -> None:
    assert compare_values(
        field="criterion_set",
        inherited=["base"],
        proposed=["base", "added"],
    ) == "tighter"
    assert compare_values(
        field="criterion_set",
        inherited=["base", "removed"],
        proposed=["base"],
    ) == "weaker"


def test_response_requires_criterion_specific_order() -> None:
    assert compare_values(
        field="response",
        inherited="still",
        proposed="block",
    ) == "incomparable"
    assert compare_values(
        field="response",
        inherited="still",
        proposed="block",
        response_order=["still", "block"],
    ) == "tighter"


def test_override_outcomes_are_closed() -> None:
    assert resolve_override(
        mode="tighten_only",
        field="maximum_tolerated_severity",
        inherited=3,
        proposed=2,
        session_started=False,
    ).outcome == "accepted"
    assert resolve_override(
        mode="tighten_only",
        field="maximum_tolerated_severity",
        inherited=2,
        proposed=3,
        session_started=False,
    ).outcome == "refused"
    assert resolve_override(
        mode="replaceable",
        field="uncertainty_display",
        inherited="ranges",
        proposed="bands",
        session_started=True,
    ).outcome == "fork_required"
    assert resolve_override(
        mode="locked",
        field="criterion_set",
        inherited=["ruin"],
        proposed=["replacement"],
        session_started=False,
    ).outcome == "refused"


def test_severity_four_cannot_be_configured_as_tolerated() -> None:
    for value in range(4):
        validate_maximum_tolerated_severity(value)
    with pytest.raises(GovernanceProfileError):
        validate_maximum_tolerated_severity(4)


def test_hard_and_ruin_rules_are_locked() -> None:
    validate_rule_override_mode(strength="soft", override_mode="replaceable")
    validate_rule_override_mode(strength="hard", override_mode="locked")
    validate_rule_override_mode(strength="ruin", override_mode="locked")
    with pytest.raises(GovernanceProfileError):
        validate_rule_override_mode(strength="hard", override_mode="tighten_only")
    with pytest.raises(GovernanceProfileError):
        validate_rule_override_mode(strength="ruin", override_mode="replaceable")


def test_comparator_policy_hash_is_stable() -> None:
    assert (
        comparator_policy_hash()
        == "979c719781111f5a3f2b65974e69ef4594827b297fe1b375c44746fd5752426a"
    )
