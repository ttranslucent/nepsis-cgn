from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional
from uuid import uuid4

from .governance import GovernanceCosts

ObjectiveType = Literal["explain", "decide", "predict", "debug", "design", "sensemake"]


@dataclass(frozen=True)
class FrameVersion:
    frame_id: str
    frame_version: int
    text: str
    objective_type: ObjectiveType = "sensemake"
    domain: Optional[str] = None
    time_horizon: Optional[str] = None
    rationale_for_change: Optional[str] = None
    constraints_hard: tuple[str, ...] = ()
    constraints_soft: tuple[str, ...] = ()
    c_fp: Optional[float] = None
    c_fn: Optional[float] = None
    c_delay: Optional[float] = None

    def reframe(
        self,
        *,
        text: Optional[str] = None,
        objective_type: Optional[ObjectiveType] = None,
        domain: Optional[str] = None,
        time_horizon: Optional[str] = None,
        rationale_for_change: Optional[str] = None,
        constraints_hard: Optional[list[str]] = None,
        constraints_soft: Optional[list[str]] = None,
    ) -> "FrameVersion":
        return FrameVersion(
            frame_id=self.frame_id,
            frame_version=self.frame_version + 1,
            text=text if text is not None else self.text,
            objective_type=objective_type if objective_type is not None else self.objective_type,
            domain=domain if domain is not None else self.domain,
            time_horizon=time_horizon if time_horizon is not None else self.time_horizon,
            rationale_for_change=rationale_for_change,
            constraints_hard=tuple(constraints_hard) if constraints_hard is not None else self.constraints_hard,
            constraints_soft=tuple(constraints_soft) if constraints_soft is not None else self.constraints_soft,
            c_fp=self.c_fp,
            c_fn=self.c_fn,
            c_delay=self.c_delay,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "frame_version": self.frame_version,
            "text": self.text,
            "objective_type": self.objective_type,
            "domain": self.domain,
            "time_horizon": self.time_horizon,
            "rationale_for_change": self.rationale_for_change,
            "constraints_hard": list(self.constraints_hard),
            "constraints_soft": list(self.constraints_soft),
            "costs": {
                "c_fp": self.c_fp,
                "c_fn": self.c_fn,
                "c_delay": self.c_delay,
            },
        }


def infer_frame_from_sign(
    sign: Any,
    *,
    family: Optional[str] = None,
    costs: Optional[GovernanceCosts] = None,
) -> FrameVersion:
    text = _infer_text(sign)
    objective = _infer_objective(family)
    return FrameVersion(
        frame_id=str(uuid4()),
        frame_version=1,
        text=text,
        objective_type=objective,
        domain=family,
        c_fp=costs.c_fp if costs else None,
        c_fn=costs.c_fn if costs else None,
    )


def _infer_text(sign: Any) -> str:
    if hasattr(sign, "describe") and callable(getattr(sign, "describe")):
        return str(sign.describe())
    if hasattr(sign, "to_state") and callable(getattr(sign, "to_state")):
        state = sign.to_state()
        if hasattr(state, "describe") and callable(getattr(state, "describe")):
            return str(state.describe())
    if hasattr(sign, "__dict__"):
        attrs = vars(sign)
        if attrs:
            parts = [f"{k}={v}" for k, v in sorted(attrs.items())]
            return " | ".join(parts)
    return str(sign)


def _infer_objective(family: Optional[str]) -> ObjectiveType:
    if family == "clinical":
        return "decide"
    if family == "safety":
        return "decide"
    if family == "puzzle":
        return "debug"
    return "sensemake"


__all__ = [
    "FrameVersion",
    "ObjectiveType",
    "infer_frame_from_sign",
]
