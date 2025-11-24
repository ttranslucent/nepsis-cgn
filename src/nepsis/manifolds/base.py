from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class TriageResult:
    detected_manifold: str
    confidence: float
    is_well_posed: bool = True
    hard_red: List[str] = field(default_factory=list)
    hard_blue: List[str] = field(default_factory=list)
    soft_blue: List[str] = field(default_factory=list)
    manifold_meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProjectionSpec:
    system_instruction: str
    manifold_context: Dict[str, Any]
    invariants: List[str]
    objective_function: Dict[str, Any]
    trace: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationResult:
    outcome: str  # "SUCCESS" | "REJECTED"
    metrics: Dict[str, Any]  # e.g., {"red_violations": [], "blue_score": 0.0}
    final_artifact: Any
    repair: Optional[Dict[str, Any]] = None  # {"needed": bool, "hints": [], "next_projection_delta": str}
    manifold_adherence: Optional[Dict[str, Any]] = None
    zeroback_event: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class BaseManifold:
    """
    Abstract interface for plugging domain-specific manifolds into the Supervisor.
    """

    name: str = "base"

    def triage(self, raw_query: str, context: str) -> TriageResult:
        raise NotImplementedError

    def project(self, triage: TriageResult) -> ProjectionSpec:
        raise NotImplementedError

    def validate(self, projection: ProjectionSpec, artifact: Any) -> ValidationResult:
        raise NotImplementedError
