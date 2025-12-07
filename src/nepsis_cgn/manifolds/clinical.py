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
    TransformationRule,
)


@dataclass
class ClinicalSign:
    """Incoming clinical story/observations."""

    radicular_pain: bool
    spasm_present: bool
    saddle_anesthesia: bool = False
    bladder_dysfunction: bool = False
    bilateral_weakness: bool = False
    progression: bool = False
    fever: bool = False
    notes: Optional[str] = None
    followup: Optional[Dict[str, Any]] = None

    def to_state(self) -> "ClinicalState":
        return ClinicalState(
            radicular_pain=self.radicular_pain,
            spasm_present=self.spasm_present,
            saddle_anesthesia=self.saddle_anesthesia,
            bladder_dysfunction=self.bladder_dysfunction,
            bilateral_weakness=self.bilateral_weakness,
            progression=self.progression,
            fever=self.fever,
            notes=self.notes,
            followup=self.followup,
        )


@dataclass
class ClinicalState(CGNState):
    """State inside a clinical manifold."""

    radicular_pain: bool
    spasm_present: bool
    saddle_anesthesia: bool = False
    bladder_dysfunction: bool = False
    bilateral_weakness: bool = False
    progression: bool = False
    fever: bool = False
    notes: Optional[str] = None
    followup: Optional[Dict[str, Any]] = None

    def describe(self) -> str:
        return json.dumps(
            {
                "radicular_pain": self.radicular_pain,
                "spasm_present": self.spasm_present,
                "saddle_anesthesia": self.saddle_anesthesia,
                "bladder_dysfunction": self.bladder_dysfunction,
                "bilateral_weakness": self.bilateral_weakness,
                "progression": self.progression,
                "fever": self.fever,
                "notes": self.notes,
            },
            sort_keys=True,
            default=str,
        )

    def with_followup_applied(self) -> "ClinicalState":
        if not self.followup:
            return self
        updated = {
            "radicular_pain": self.radicular_pain,
            "spasm_present": self.spasm_present,
            "saddle_anesthesia": self.saddle_anesthesia,
            "bladder_dysfunction": self.bladder_dysfunction,
            "bilateral_weakness": self.bilateral_weakness,
            "progression": self.progression,
            "fever": self.fever,
            "notes": self.notes,
            "followup": None,  # clear after applying
        }
        for key, value in self.followup.items():
            if key in updated:
                updated[key] = bool(value) if isinstance(value, bool) or isinstance(value, int) else value
        return ClinicalState(**updated)


class RequiresRadicularPain(Constraint):
    name = "requires_radicular_pain"

    def check(self, state: ClinicalState) -> List[ConstraintViolation]:
        if state.radicular_pain:
            return []
        return [
            ConstraintViolation(
                message="No radicular pain present; manifold mismatch.",
                code="missing_radicular",
                severity="error",
            )
        ]


class RequiresSpasm(Constraint):
    name = "requires_spasm"

    def check(self, state: ClinicalState) -> List[ConstraintViolation]:
        if state.spasm_present:
            return []
        return [
            ConstraintViolation(
                message="Spasm not present; consider alternative manifold.",
                code="missing_spasm",
                severity="warning",
            )
        ]


class NoRedFlags(Constraint):
    name = "no_red_flags"

    def check(self, state: ClinicalState) -> List[ConstraintViolation]:
        flags = {
            "saddle_anesthesia": state.saddle_anesthesia,
            "bladder_dysfunction": state.bladder_dysfunction,
            "bilateral_weakness": state.bilateral_weakness,
        }
        offenders = [name for name, present in flags.items() if present]
        if not offenders:
            return []
        return [
            ConstraintViolation(
                message=f"Red flags present: {', '.join(offenders)}.",
                code="red_flag_present",
                severity="error",
                metadata={"flags": offenders},
            )
        ]


class RedFlagsRequired(Constraint):
    name = "red_flags_required"

    def check(self, state: ClinicalState) -> List[ConstraintViolation]:
        if state.saddle_anesthesia or state.bladder_dysfunction or state.bilateral_weakness:
            return []
        return [
            ConstraintViolation(
                message="No red flags detected; cauda equina manifold likely mismatch.",
                code="missing_red_flags",
                severity="error",
            )
        ]


class ProgressionWarning(Constraint):
    name = "progression_warning"

    def check(self, state: ClinicalState) -> List[ConstraintViolation]:
        if state.progression:
            return [
                ConstraintViolation(
                    message="Symptoms are progressing; escalate monitoring.",
                    code="progression",
                    severity="warning",
                )
            ]
        return []


def build_radicular_constraint_set(name: str = "radicular_spasm") -> ConstraintSet:
    return ConstraintSet(
        name=name,
        constraints=[
            RequiresRadicularPain(),
            RequiresSpasm(),
            NoRedFlags(),
            ProgressionWarning(),
        ],
    )


def build_cauda_constraint_set(name: str = "cauda_equina") -> ConstraintSet:
    return ConstraintSet(
        name=name,
        constraints=[
            RequiresRadicularPain(),
            RedFlagsRequired(),
            ProgressionWarning(),
        ],
    )


def _followup_transform(state: ClinicalState) -> ClinicalState:
    return state.with_followup_applied()


def _ruin_on_red_flags(state: ClinicalState) -> bool:
    return bool(state.saddle_anesthesia or state.bladder_dysfunction)


class RadicularSpasmManifold(Manifold[ClinicalState]):
    id = "radicular_spasm"
    family = "clinical"

    def __init__(self) -> None:
        super().__init__(
            constraint_set=build_radicular_constraint_set(),
            ruin_nodes=[
                RuinNode(
                    name="red_flag_ruin",
                    predicate=_ruin_on_red_flags,
                    description="Immediate escalation if red flags appear.",
                )
            ],
            transformation_rules=[
                TransformationRule(
                    name="apply_followup",
                    description="Merge bedside follow-up findings into the state.",
                    apply=_followup_transform,
                )
            ],
            seeds={"red_flags": ["saddle_anesthesia", "bladder_dysfunction", "bilateral_weakness"]},
            success_signatures=["spasm_breakthrough"],
        )

    def project_state(self, sign: ClinicalSign) -> ClinicalState:
        return sign.to_state()


class CaudaEquinaManifold(Manifold[ClinicalState]):
    id = "cauda_equina"
    family = "clinical"

    def __init__(self) -> None:
        super().__init__(
            constraint_set=build_cauda_constraint_set(),
            ruin_nodes=[],
            transformation_rules=[
                TransformationRule(
                    name="apply_followup",
                    description="Merge bedside follow-up findings into the state.",
                    apply=_followup_transform,
                )
            ],
            seeds={"red_flags": ["saddle_anesthesia", "bladder_dysfunction", "bilateral_weakness"]},
            success_signatures=["red_channel_engaged"],
        )

    def project_state(self, sign: ClinicalSign) -> ClinicalState:
        return sign.to_state()


def build_clinical_hypotheses() -> List[InterpretantHypothesis[ClinicalSign, ClinicalState]]:
    return [
        InterpretantHypothesis(
            id="radicular_spasm",
            description="Radicular pain with spasm, no red flags.",
            manifold_factory=lambda _: RadicularSpasmManifold(),
            prior=0.6,
        ),
        InterpretantHypothesis(
            id="cauda_equina",
            description="Red-channel manifold for cauda equina red flags.",
            manifold_factory=lambda _: CaudaEquinaManifold(),
            prior=0.4,
            likelihood_fn=lambda sign: 2.0
            if getattr(sign, "saddle_anesthesia", False) or getattr(sign, "bladder_dysfunction", False)
            else 1.0,
        ),
    ]


def demo_radicular_vs_cauda(sign: Optional[ClinicalSign] = None) -> Dict[str, Any]:
    """
    Minimal illustration:
    - RadicularSpasmManifold stays blue unless red flags present.
    - CaudaEquinaManifold activates red-channel geometry when red flags appear.
    """

    sign = sign or ClinicalSign(
        radicular_pain=True,
        spasm_present=True,
        saddle_anesthesia=False,
        bladder_dysfunction=False,
        bilateral_weakness=False,
        progression=False,
        notes="Left L5 paresthesias, muscle spasm on exam.",
        followup={"saddle_anesthesia": True},
    )

    hypotheses = build_clinical_hypotheses()
    manager: InterpretantManager[ClinicalSign, ClinicalState] = InterpretantManager(hypotheses=hypotheses)
    posterior = manager.update(sign)

    rad_eval = hypotheses[0].manifold_factory(sign).run(sign)
    cauda_eval = hypotheses[1].manifold_factory(sign).run(sign)

    return {
        "posterior": posterior,
        "radicular": rad_eval,
        "cauda": cauda_eval,
    }


__all__ = [
    "CaudaEquinaManifold",
    "ClinicalSign",
    "ClinicalState",
    "RadicularSpasmManifold",
    "build_cauda_constraint_set",
    "build_clinical_hypotheses",
    "build_radicular_constraint_set",
    "demo_radicular_vs_cauda",
]
