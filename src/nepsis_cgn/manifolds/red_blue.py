from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..core.constraints import CGNState, Constraint, ConstraintSet, ConstraintViolation
from ..core.interpretant import (
    InterpretantHypothesis,
    InterpretantManager,
    Manifold,
    RuinNode,
)


@dataclass
class SafetySign:
    critical_signal: bool
    policy_violation: bool = False
    notes: Optional[str] = None

    def to_state(self) -> "SafetyState":
        return SafetyState(
            critical_signal=self.critical_signal,
            policy_violation=self.policy_violation,
            notes=self.notes,
        )


@dataclass
class SafetyState(CGNState):
    critical_signal: bool
    policy_violation: bool = False
    notes: Optional[str] = None

    def describe(self) -> str:
        return json.dumps(
            {
                "critical_signal": self.critical_signal,
                "policy_violation": self.policy_violation,
                "notes": self.notes,
            },
            sort_keys=True,
            default=str,
        )


class NoCriticalSignal(Constraint):
    name = "no_critical_signal"

    def check(self, state: SafetyState) -> List[ConstraintViolation]:
        if state.critical_signal:
            return [
                ConstraintViolation(
                    message="Critical signal detected; route to red channel.",
                    code="critical_signal_present",
                    severity="error",
                )
            ]
        return []


class RequiresCriticalSignal(Constraint):
    name = "requires_critical_signal"

    def check(self, state: SafetyState) -> List[ConstraintViolation]:
        if state.critical_signal:
            return []
        return [
            ConstraintViolation(
                message="No critical signal; red channel likely mismatch.",
                code="missing_critical_signal",
                severity="error",
            )
        ]


class NoPolicyViolation(Constraint):
    name = "no_policy_violation"

    def check(self, state: SafetyState) -> List[ConstraintViolation]:
        if state.policy_violation:
            return [
                ConstraintViolation(
                    message="Policy violation detected.",
                    code="policy_violation",
                    severity="error",
                )
            ]
        return []


class EscalationNotice(Constraint):
    name = "escalation_notice"

    def check(self, state: SafetyState) -> List[ConstraintViolation]:
        if state.notes:
            return [
                ConstraintViolation(
                    message="Context notes present; review carefully.",
                    code="context_notes",
                    severity="warning",
                )
            ]
        return []


def build_blue_constraint_set(name: str = "blue_channel") -> ConstraintSet:
    return ConstraintSet(
        name=name,
        constraints=[
            NoCriticalSignal(),
            NoPolicyViolation(),
            EscalationNotice(),
        ],
    )


def build_red_constraint_set(name: str = "red_channel") -> ConstraintSet:
    return ConstraintSet(
        name=name,
        constraints=[
            RequiresCriticalSignal(),
            EscalationNotice(),
        ],
    )


def _ruin_on_policy(state: SafetyState) -> bool:
    return bool(state.policy_violation)


class BlueChannelManifold(Manifold[SafetyState]):
    id = "blue_channel"
    family = "safety"

    def __init__(self) -> None:
        super().__init__(
            constraint_set=build_blue_constraint_set(),
            ruin_nodes=[],
            transformation_rules=[],
            seeds={"channel": "blue"},
            success_signatures=["routine_clearance"],
        )

    def project_state(self, sign: SafetySign) -> SafetyState:
        return sign.to_state()


class RedChannelManifold(Manifold[SafetyState]):
    id = "red_channel"
    family = "safety"

    def __init__(self) -> None:
        super().__init__(
            constraint_set=build_red_constraint_set(),
            ruin_nodes=[
                RuinNode(
                    name="policy_violation_ruin",
                    predicate=_ruin_on_policy,
                    description="Immediate halt on policy violation.",
                )
            ],
            transformation_rules=[],
            seeds={"channel": "red"},
            success_signatures=["escalation_active"],
        )

    def project_state(self, sign: SafetySign) -> SafetyState:
        return sign.to_state()


def build_red_blue_hypotheses() -> List[InterpretantHypothesis[SafetySign, SafetyState]]:
    return [
        InterpretantHypothesis(
            id="blue_channel",
            description="Routine/blue channel; no critical signals.",
            manifold_factory=lambda _: BlueChannelManifold(),
            prior=0.6,
        ),
        InterpretantHypothesis(
            id="red_channel",
            description="Red channel for critical signals; policy violation is ruin.",
            manifold_factory=lambda _: RedChannelManifold(),
            prior=0.4,
            likelihood_fn=lambda sign: 2.0 if getattr(sign, "critical_signal", False) else 1.0,
        ),
    ]


def demo_red_blue(sign: Optional[SafetySign] = None) -> Dict[str, Any]:
    sign = sign or SafetySign(critical_signal=True, policy_violation=False, notes="Urgent cue from upstream.")
    hypotheses = build_red_blue_hypotheses()
    manager: InterpretantManager[SafetySign, SafetyState] = InterpretantManager(hypotheses=hypotheses)
    posterior = manager.update(sign)

    blue_eval = hypotheses[0].manifold_factory(sign).run(sign)
    red_eval = hypotheses[1].manifold_factory(sign).run(sign)

    return {
        "posterior": posterior,
        "blue": blue_eval,
        "red": red_eval,
    }


__all__ = [
    "BlueChannelManifold",
    "RedChannelManifold",
    "SafetySign",
    "SafetyState",
    "build_blue_constraint_set",
    "build_red_blue_hypotheses",
    "build_red_constraint_set",
    "demo_red_blue",
]
