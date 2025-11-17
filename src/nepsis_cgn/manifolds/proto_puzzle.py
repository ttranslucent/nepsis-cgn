"""Proto puzzle manifold for NepsisCGN.

This is intentionally lightweight but expressive enough to cover two early
benchmarks:

1. Letter-usage puzzles such as the JAILING/JINGALL example.
2. UTF-8 / formatting hygiene for arbitrary text outputs (e.g., Terminal Bench).

Each constraint pack in this module can compile into the existing
``ConstraintSet`` abstraction, giving us immediate compatibility with
``CGNSolver`` and any existing evaluation tooling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from ..core.constraints import ConstraintSet, ConstraintViolation
from ..core.solver import CGNSolver, SolverResult
from . import (
    ConstraintPackDefinition,
    ConstraintRuleDefinition,
    DictBackedState,
    ManifoldDefinition,
    ManifoldDimension,
    build_constraint_set_from_pack,
)


PROTO_PUZZLE_DIMENSIONS: List[ManifoldDimension] = [
    ManifoldDimension(name="name_correct", type="boolean", description="Correct proper noun used."),
    ManifoldDimension(name="story_consistent", type="boolean", description="Answer matches prompt story."),
    ManifoldDimension(name="explanation_quality", type="float", description="0-1 coherence score."),
    ManifoldDimension(name="format_ok", type="boolean", description="Matches expected formatting."),
    ManifoldDimension(name="valid_utf8", type="boolean", description="Output is valid UTF-8."),
    ManifoldDimension(name="has_invisible_chars", type="boolean", description="Contains hidden control chars."),
    ManifoldDimension(name="tests_passed", type="float", description="Normalized pass rate."),
    ManifoldDimension(name="banned_commands_used", type="boolean", description="Illegal command detected."),
    ManifoldDimension(name="steps_taken", type="integer", description="Trajectory length."),
    ManifoldDimension(name="timeout_or_crash", type="boolean", description="Run timed out or crashed."),
    ManifoldDimension(name="file_corruption", type="boolean", description="Damaged unrelated files."),
    ManifoldDimension(name="idempotent", type="boolean", description="Re-run stability."),
]


def _soft(rule_id: str, rule: str, description: str, *, weight: float) -> ConstraintRuleDefinition:
    return ConstraintRuleDefinition(
        id=rule_id,
        type="soft",
        rule=rule,
        description=description,
        weight=weight,
    )


def _hard(rule_id: str, rule: str, description: str) -> ConstraintRuleDefinition:
    return ConstraintRuleDefinition(
        id=rule_id,
        type="hard",
        rule=rule,
        description=description,
    )


PROTO_PUZZLE_CONSTRAINT_PACKS: List[ConstraintPackDefinition] = [
    ConstraintPackDefinition(
        id="jailing_jingall",
        constraints=[
            _hard("C1", "name_correct == True", "Must use the correct name in the answer."),
            _hard("C2", "story_consistent == True", "Answer must match the described scenario."),
            _soft(
                "C3",
                "(explanation_quality or 0) >= 0.7",
                "Explanation should be clear and coherent.",
                weight=1.0,
            ),
        ],
    ),
    ConstraintPackDefinition(
        id="utf8_clean",
        constraints=[
            _hard("C4", "valid_utf8 == True", "Output must be valid UTF-8."),
            _soft(
                "C5",
                "has_invisible_chars == False",
                "Avoid invisible control characters.",
                weight=0.8,
            ),
            _soft(
                "C6",
                "format_ok == True",
                "Formatting should match the expected spec.",
                weight=0.5,
            ),
        ],
    ),
    ConstraintPackDefinition(
        id="terminal_bench",
        constraints=[
            _hard("C7", "tests_passed == 1.0", "All graded tests must pass."),
            _hard("C8", "banned_commands_used == False", "No disallowed or unsafe commands."),
            _hard("C9", "timeout_or_crash == False", "Run must complete without crash/timeout."),
            _soft(
                "C10",
                "steps_taken <= 20",
                "Prefer shorter, more efficient trajectories.",
                weight=0.4,
            ),
            _soft(
                "C11",
                "file_corruption == False",
                "Non-target files should not be corrupted.",
                weight=0.6,
            ),
            _soft(
                "C12",
                "idempotent == True",
                "Re-running should not thrash or diverge.",
                weight=0.5,
            ),
        ],
    ),
]


NEPSIS_PROTO_PUZZLE_MANIFOLD = ManifoldDefinition(
    id="nepsis_proto_puzzle",
    name="NepsisCGN Proto Puzzle Manifold",
    dimensions=PROTO_PUZZLE_DIMENSIONS,
    constraint_packs=PROTO_PUZZLE_CONSTRAINT_PACKS,
)


MANIFOLD_DIMENSION_NAMES = [dim.name for dim in PROTO_PUZZLE_DIMENSIONS]


class ProtoPuzzleState(DictBackedState):
    """Concrete state wrapper for the proto puzzle manifold."""

    def __init__(self, **values: Any):
        normalized = {name: values.get(name) for name in MANIFOLD_DIMENSION_NAMES}
        super().__init__(values=normalized)

    @classmethod
    def from_mapping(cls, mapping: Dict[str, Any]) -> "ProtoPuzzleState":
        return cls(**mapping)


def constraint_set_for_pack(pack_id: str) -> ConstraintSet:
    pack = NEPSIS_PROTO_PUZZLE_MANIFOLD.get_pack(pack_id)
    label = f"{NEPSIS_PROTO_PUZZLE_MANIFOLD.id}:{pack_id}"
    return build_constraint_set_from_pack(pack, label=label)


def terminalbench_to_state(summary: Dict[str, Any]) -> ProtoPuzzleState:
    """Map a Terminal Bench summary JSON blob into the manifold state space."""

    data = {
        "tests_passed": float(summary.get("tests_passed", 0.0)),
        "banned_commands_used": bool(summary.get("banned_commands_used", False)),
        "steps_taken": int(summary.get("steps_taken", 0)),
        "timeout_or_crash": bool(summary.get("timeout_or_crash", False)),
        "file_corruption": bool(summary.get("file_corruption", False)),
        "idempotent": bool(summary.get("idempotent", False)),
        "valid_utf8": bool(summary.get("final_output_utf8_valid", True)),
        "has_invisible_chars": bool(summary.get("final_output_has_invisibles", False)),
        "format_ok": summary.get("format_ok"),
    }

    # Semantic dimensions default to ``None`` until we wire richer checks.
    data.setdefault("name_correct", None)
    data.setdefault("story_consistent", None)
    data.setdefault("explanation_quality", None)

    return ProtoPuzzleState(**data)


@dataclass
class ProtoPuzzleReport:
    pack_id: str
    pack_name: str
    state: Dict[str, Any]
    is_valid: bool
    distance: float
    violations: List[ConstraintViolation]
    hints: List[str]
    result: SolverResult


def _state_from_mapping(pack_id: str, mapping: Dict[str, Any]) -> ProtoPuzzleState:
    if pack_id == "terminal_bench":
        return terminalbench_to_state(mapping)
    return ProtoPuzzleState.from_mapping(mapping)


def _compute_distance(violations: List[ConstraintViolation]) -> float:
    if not violations:
        return 0.0
    distance = 0.0
    for violation in violations:
        distance += 1.0 if violation.severity == "error" else 0.5
    return distance


def evaluate_proto_puzzle(pack_id: str, mapping: Dict[str, Any]) -> ProtoPuzzleReport:
    """Evaluate a proto puzzle pack against a mapping of state dimensions."""

    constraint_set = constraint_set_for_pack(pack_id)
    pack = NEPSIS_PROTO_PUZZLE_MANIFOLD.get_pack(pack_id)
    solver = CGNSolver(constraint_set=constraint_set)
    state = _state_from_mapping(pack_id, mapping)
    result = solver.evaluate_state(state)
    distance = _compute_distance(result.violations)
    hints = [f"{v.code}: {v.message}" for v in result.violations]
    return ProtoPuzzleReport(
        pack_id=pack_id,
        pack_name=pack.id,
        state=state.to_dict(),
        is_valid=result.is_valid,
        distance=distance,
        violations=result.violations,
        hints=hints,
        result=result,
    )


def evaluate_terminal_bench(summary: Dict[str, Any]) -> ProtoPuzzleReport:
    return evaluate_proto_puzzle("terminal_bench", summary)


__all__ = [
    "NEPSIS_PROTO_PUZZLE_MANIFOLD",
    "ProtoPuzzleState",
    "constraint_set_for_pack",
    "terminalbench_to_state",
    "evaluate_proto_puzzle",
    "evaluate_terminal_bench",
    "ProtoPuzzleReport",
]
