from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class ConvergenceReason:
    code: str
    title: str
    message: str
    next_discriminator: str
    severity: str

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "title": self.title,
            "message": self.message,
            "next_discriminator": self.next_discriminator,
            "severity": self.severity,
        }


_REASON_MAP: dict[str, ConvergenceReason] = {
    "CONSTRAINT_CONFLICT": ConvergenceReason(
        code="CONSTRAINT_CONFLICT",
        title="Constraint Conflict",
        message="Active constraints are mutually inconsistent under current assumptions.",
        next_discriminator="Relax or remove one soft constraint and rerun contradiction scan.",
        severity="high",
    ),
    "HIGH_ENTROPY_NO_DISCRIMINATOR": ConvergenceReason(
        code="HIGH_ENTROPY_NO_DISCRIMINATOR",
        title="Uncertainty Plateau",
        message="Posterior remains flat because no high-value discriminator has been run.",
        next_discriminator="Choose one test expected to maximally separate top hypotheses.",
        severity="medium",
    ),
    "AUX_LOAD_ACCUMULATION": ConvergenceReason(
        code="AUX_LOAD_ACCUMULATION",
        title="Assumption Overload",
        message="Auxiliary assumptions are accumulating faster than evidence support.",
        next_discriminator="Drop weakest auxiliary assumption and re-score top candidates.",
        severity="medium",
    ),
    "MARGIN_COLLAPSE": ConvergenceReason(
        code="MARGIN_COLLAPSE",
        title="Top Margin Collapse",
        message="Top competing hypotheses are near-equivalent in posterior mass.",
        next_discriminator="Run a discriminator that targets only the top two hypotheses.",
        severity="medium",
    ),
    "CONTRADICTION_PERSISTENCE": ConvergenceReason(
        code="CONTRADICTION_PERSISTENCE",
        title="Contradictions Persist",
        message="Constraint/claim contradictions remain unresolved across iterations.",
        next_discriminator="Focus next test on the contradiction cluster with highest severity.",
        severity="high",
    ),
    "HOTSPOT_APPROACH": ConvergenceReason(
        code="HOTSPOT_APPROACH",
        title="Hotspot Approach",
        message="Trajectory is moving toward an unstable manifold region.",
        next_discriminator="Switch to verification mode and require external check/citation.",
        severity="high",
    ),
    "RECURRENCE_PATTERN": ConvergenceReason(
        code="RECURRENCE_PATTERN",
        title="Recurrence Pattern",
        message="Reset/contradiction pattern is repeating without net convergence.",
        next_discriminator="Perform ZeroBack with explicit carry-forward policy.",
        severity="high",
    ),
    "DATA_QUALITY_GAP": ConvergenceReason(
        code="DATA_QUALITY_GAP",
        title="Data Quality Gap",
        message="Current evidence quality is insufficient for stable collapse.",
        next_discriminator="Acquire one higher-quality observation with source attribution.",
        severity="medium",
    ),
    "RUIN_MASS_HIGH": ConvergenceReason(
        code="RUIN_MASS_HIGH",
        title="Ruin Mass Elevated",
        message="Posterior mass on catastrophic hypotheses meets or exceeds policy threshold.",
        next_discriminator="Take protective action and gather data that can safely de-risk.",
        severity="high",
    ),
    "DIRECT_RUIN_CRITERION_ACTIVE": ConvergenceReason(
        code="DIRECT_RUIN_CRITERION_ACTIVE",
        title="Direct Ruin Criterion Active",
        message=(
            "A deterministic protected criterion is active independently of posterior mass."
        ),
        next_discriminator=(
            "Contain the named exposure and verify the criterion without treating severity as hypothesis truth."
        ),
        severity="high",
    ),
    "COST_GATE_CROSSED": ConvergenceReason(
        code="COST_GATE_CROSSED",
        title="Protective-Action Cost Review",
        message=(
            "Estimated bad-state probability exceeds the cost-derived action threshold; "
            "this requests review but does not establish truth or activate a RED veto."
        ),
        next_discriminator=(
            "Check calibration and explicitly weigh the bounded safeguard burden before acting."
        ),
        severity="medium",
    ),
    "ANTI_STALL": ConvergenceReason(
        code="ANTI_STALL",
        title="Anti-Stall Trigger",
        message="Mixture mode dwell time exceeded without decisive separation.",
        next_discriminator="Run mandatory discriminator action or choose safest fallback policy.",
        severity="medium",
    ),
    "RED_CAPTURE_REVIEW": ConvergenceReason(
        code="RED_CAPTURE_REVIEW",
        title="RED Capture Review",
        message=(
            "RED has remained action-governing across the review limit; the veto stays active "
            "while its applicability and frame are challenged."
        ),
        next_discriminator=(
            "Run a safe discriminator or ZeroBack that preserves the hazard record while testing "
            "whether it applies to the current frame."
        ),
        severity="high",
    ),
}


def explain_trigger_codes(codes: Iterable[str]) -> List[ConvergenceReason]:
    reasons: List[ConvergenceReason] = []
    for code in codes:
        if code in _REASON_MAP:
            reasons.append(_REASON_MAP[code])
        else:
            reasons.append(
                ConvergenceReason(
                    code=code,
                    title="Unmapped Trigger",
                    message=f"Trigger code '{code}' has no mapped explanation yet.",
                    next_discriminator="Inspect trace and map this trigger in convergence.py.",
                    severity="low",
                )
            )
    return reasons


__all__ = [
    "ConvergenceReason",
    "explain_trigger_codes",
]
