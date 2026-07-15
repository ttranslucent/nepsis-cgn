from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from .canonical_json import canonical_hash


GOVERNANCE_COMPARATOR_POLICY_VERSION = (
    "nepsis.governance_comparator_policy@0.1.0"
)

Comparison = Literal["equal", "tighter", "weaker", "incomparable"]
OverrideOutcome = Literal["accepted", "refused", "fork_required"]
OverrideMode = Literal["locked", "tighten_only", "replaceable"]

_ORDERED_FIELDS: dict[str, tuple[Any, ...]] = {
    "evidence_floor": ("operator_attestation", "one_source", "corroborated"),
    "evidence_requirement": ("standard", "elevated", "strict"),
    "reversibility_requirement": ("none", "preferred", "required"),
    "loss_posture": ("balanced", "downside_weighted", "ruin_averse"),
}

_REPLACEABLE_FIELDS = {
    "clarification_budget",
    "proposal_mode",
    "uncertainty_display",
    "unresolved_optional_policy",
}

_COMPARATOR_POLICY_DOCUMENT = {
    "governance_comparator_policy_version": GOVERNANCE_COMPARATOR_POLICY_VERSION,
    "lower_is_stricter": ["maximum_tolerated_severity"],
    "ordered_fields": {
        field: list(values) for field, values in sorted(_ORDERED_FIELDS.items())
    },
    "replaceable_unordered_fields": sorted(_REPLACEABLE_FIELDS),
    "set_rule": "proper_superset_is_stricter",
    "data_scope_rule": "proper_subset_is_stricter",
    "response_rule": "criterion_specific_order_required",
    "unknown_rule": "incomparable_and_refused",
}


class GovernanceProfileError(ValueError):
    pass


@dataclass(frozen=True)
class OverrideDecision:
    outcome: OverrideOutcome
    comparison: Comparison
    reason: str


def comparator_policy_hash() -> str:
    return canonical_hash(_COMPARATOR_POLICY_DOCUMENT)


def compare_values(
    *,
    field: str,
    inherited: Any,
    proposed: Any,
    data_scopes: Mapping[str, frozenset[str]] | None = None,
    response_order: Sequence[str] | None = None,
) -> Comparison:
    if inherited == proposed:
        return "equal"

    if field == "maximum_tolerated_severity":
        _validate_maximum_tolerated_severity(inherited)
        _validate_maximum_tolerated_severity(proposed)
        return "tighter" if proposed < inherited else "weaker"

    if field in _ORDERED_FIELDS:
        order = _ORDERED_FIELDS[field]
        try:
            inherited_index = order.index(inherited)
            proposed_index = order.index(proposed)
        except ValueError as exc:
            raise GovernanceProfileError(f"unsupported {field} value") from exc
        return "tighter" if proposed_index > inherited_index else "weaker"

    if field == "data_scope":
        scopes = data_scopes or {}
        try:
            inherited_set = scopes[str(inherited)]
            proposed_set = scopes[str(proposed)]
        except KeyError as exc:
            raise GovernanceProfileError("unknown data_scope") from exc
        if proposed_set < inherited_set:
            return "tighter"
        if inherited_set < proposed_set:
            return "weaker"
        return "incomparable"

    if field == "criterion_set":
        inherited_set = _string_set(inherited, "inherited criterion_set")
        proposed_set = _string_set(proposed, "proposed criterion_set")
        if proposed_set > inherited_set:
            return "tighter"
        if inherited_set > proposed_set:
            return "weaker"
        return "incomparable"

    if field == "response":
        if not response_order:
            return "incomparable"
        order = tuple(response_order)
        if len(order) != len(set(order)):
            raise GovernanceProfileError("response_order values must be unique")
        try:
            inherited_index = order.index(str(inherited))
            proposed_index = order.index(str(proposed))
        except ValueError as exc:
            raise GovernanceProfileError("response is absent from criterion order") from exc
        return "tighter" if proposed_index > inherited_index else "weaker"

    if field in _REPLACEABLE_FIELDS:
        return "incomparable"

    return "incomparable"


def resolve_override(
    *,
    mode: OverrideMode,
    field: str,
    inherited: Any,
    proposed: Any,
    session_started: bool,
    data_scopes: Mapping[str, frozenset[str]] | None = None,
    response_order: Sequence[str] | None = None,
) -> OverrideDecision:
    comparison = compare_values(
        field=field,
        inherited=inherited,
        proposed=proposed,
        data_scopes=data_scopes,
        response_order=response_order,
    )
    if mode == "locked":
        if comparison == "equal":
            return OverrideDecision("accepted", comparison, "value is unchanged")
        return OverrideDecision("refused", comparison, "locked field cannot change")
    if mode == "replaceable":
        if session_started and comparison != "equal":
            return OverrideDecision(
                "fork_required",
                comparison,
                "active-session replacement requires a new run fork",
            )
        return OverrideDecision("accepted", comparison, "pre-genesis replacement")
    if mode == "tighten_only":
        if comparison in {"equal", "tighter"}:
            return OverrideDecision("accepted", comparison, "deterministic tightening")
        return OverrideDecision(
            "refused",
            comparison,
            "tighten-only field cannot be relaxed or compared ambiguously",
        )
    raise GovernanceProfileError(f"unsupported override mode: {mode}")


def validate_rule_override_mode(*, strength: str, override_mode: str) -> None:
    if strength not in {"soft", "hard", "ruin"}:
        raise GovernanceProfileError("unsupported constraint strength")
    if override_mode not in {"locked", "tighten_only", "replaceable"}:
        raise GovernanceProfileError("unsupported override mode")
    if strength in {"hard", "ruin"} and override_mode != "locked":
        raise GovernanceProfileError(f"{strength} constraints must be locked")


def validate_maximum_tolerated_severity(value: Any) -> None:
    _validate_maximum_tolerated_severity(value)


def _validate_maximum_tolerated_severity(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
        raise GovernanceProfileError(
            "maximum_tolerated_severity must be an integer from 0 through 3"
        )


def _string_set(value: Any, field: str) -> frozenset[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise GovernanceProfileError(f"{field} must be a string collection")
    result = frozenset(value)
    if not result or any(not isinstance(item, str) or not item for item in result):
        raise GovernanceProfileError(f"{field} must contain non-empty strings")
    return result
