from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Mapping, Optional, Sequence, Tuple, TypeVar

from .constraints import CGNState, ConstraintSet
from .solver import CGNSolver, SolverResult
from ..puzzles.word_game import (
    WordGameState,
    build_word_game_constraint_set,
    compute_distance_from_validity,
    compute_quality_score,
    suggest_repair,
)

StateT = TypeVar("StateT", bound=CGNState)
SignT = TypeVar("SignT")


@dataclass(frozen=True)
class Sign:
    """Raw signal presented to the interpretant."""

    text: str
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TransformationRule(Generic[StateT]):
    name: str
    apply: Callable[[StateT], StateT]
    description: Optional[str] = None


@dataclass(frozen=True)
class RuinNode(Generic[StateT]):
    name: str
    predicate: Callable[[StateT], bool]
    description: Optional[str] = None


@dataclass(frozen=True)
class InterpretantHypothesis(Generic[SignT, StateT]):
    """
    Single interpretant hypothesis.

    Each hypothesis knows how to instantiate a manifold for a given sign and can
    provide a likelihood for Bayesian updating.
    """

    id: str
    description: str
    manifold_factory: Callable[[SignT], "Manifold[StateT]"]
    prior: float = 1.0
    likelihood_fn: Optional[Callable[[SignT], float]] = None

    def likelihood(self, sign: SignT) -> float:
        if self.likelihood_fn is None:
            return 1.0
        value = float(self.likelihood_fn(sign))
        return max(value, 1e-9)


@dataclass
class ManifoldEvaluation(Generic[StateT]):
    manifold_id: str
    family: str
    state: StateT
    result: SolverResult
    is_ruin: bool
    active_transforms: List[str]
    ruin_hits: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)


class Manifold(Generic[StateT]):
    """
    Abstract manifold with constraint geometry and ruin nodes.

    A concrete manifold maps a sign to a state, applies transformation rules,
    checks ruin conditions, and delegates constraint evaluation to CGNSolver.
    """

    id: str
    family: str

    def __init__(
        self,
        *,
        constraint_set: ConstraintSet,
        ruin_nodes: Optional[Sequence[RuinNode[StateT]]] = None,
        transformation_rules: Optional[Sequence[TransformationRule[StateT]]] = None,
        seeds: Optional[Mapping[str, Any]] = None,
        success_signatures: Optional[Sequence[str]] = None,
    ):
        self.constraint_set = constraint_set
        self.ruin_nodes: List[RuinNode[StateT]] = list(ruin_nodes or [])
        self.transformation_rules: List[TransformationRule[StateT]] = list(transformation_rules or [])
        self.seeds: Dict[str, Any] = dict(seeds or {})
        self.success_signatures: List[str] = list(success_signatures or [])
        self._solver = CGNSolver(constraint_set=self.constraint_set)

    def project_state(self, sign: SignT) -> StateT:
        raise NotImplementedError

    def apply_transformations(self, state: StateT) -> Tuple[StateT, List[str]]:
        applied: List[str] = []
        for rule in self.transformation_rules:
            state = rule.apply(state)
            applied.append(rule.name)
        return state, applied

    def evaluate_state(self, state: StateT) -> ManifoldEvaluation[StateT]:
        transformed_state, transforms = self.apply_transformations(state)
        ruin_hits = [node.name for node in self.ruin_nodes if node.predicate(transformed_state)]
        result = self._solver.evaluate_state(transformed_state)
        return ManifoldEvaluation(
            manifold_id=self.id,
            family=self.family,
            state=transformed_state,
            result=result,
            is_ruin=bool(ruin_hits),
            active_transforms=transforms,
            ruin_hits=ruin_hits,
            metadata={
                "seeds": self.seeds,
                "success_signatures": self.success_signatures,
                "constraint_set": self.constraint_set.name,
            },
        )

    def run(self, sign: SignT) -> ManifoldEvaluation[StateT]:
        state = self.project_state(sign)
        return self.evaluate_state(state)


class InterpretantManager(Generic[SignT, StateT]):
    """Bayesian interpreter that selects the active manifold."""

    def __init__(self, hypotheses: Sequence[InterpretantHypothesis[SignT, StateT]]):
        if not hypotheses:
            raise ValueError("At least one hypothesis is required.")
        self._hypotheses = {hyp.id: hyp for hyp in hypotheses}
        self._posterior: Dict[str, float] = {hyp.id: float(hyp.prior) for hyp in hypotheses}

    def update(self, sign: SignT) -> Dict[str, float]:
        weights: Dict[str, float] = {}
        for hyp in self._hypotheses.values():
            weights[hyp.id] = max(hyp.prior, 1e-9) * hyp.likelihood(sign)
        normalizer = sum(weights.values())
        if normalizer == 0.0:
            count = float(len(weights))
            self._posterior = {key: 1.0 / count for key in weights}
        else:
            self._posterior = {key: value / normalizer for key, value in weights.items()}
        return dict(self._posterior)

    def select_manifold(self, sign: SignT) -> Manifold[StateT]:
        self.update(sign)
        best_id = max(self._posterior, key=self._posterior.get)
        hypothesis = self._hypotheses[best_id]
        return hypothesis.manifold_factory(sign)

    def posterior(self) -> Dict[str, float]:
        return dict(self._posterior)


# --- Example: Jailing vs. Jingall word puzzle --------------------------------


@dataclass(frozen=True)
class WordPuzzleSign:
    letters: str
    candidate: str

    def to_raw_sign(self) -> Sign:
        return Sign(text=f"{self.letters}|{self.candidate}", data={"letters": self.letters, "candidate": self.candidate})


class WordPuzzleManifold(Manifold[WordGameState]):
    family = "puzzle"

    def project_state(self, sign: WordPuzzleSign) -> WordGameState:
        return WordGameState(letters=sign.letters, candidate=sign.candidate)

    def enrich_metadata(self, evaluation: ManifoldEvaluation[WordGameState]) -> ManifoldEvaluation[WordGameState]:
        # Basic scoring to illustrate how hints slot into the manifold record.
        metadata = dict(evaluation.metadata)
        metadata["distance"] = compute_distance_from_validity(evaluation.state)
        metadata["quality_score"] = compute_quality_score(evaluation.state)
        metadata["repair_hints"] = suggest_repair(evaluation.state)
        evaluation.metadata = metadata
        return evaluation

    def run(self, sign: WordPuzzleSign) -> ManifoldEvaluation[WordGameState]:
        evaluation = super().run(sign)
        return self.enrich_metadata(evaluation)


def _missing_required(letter: str) -> RuinNode[WordGameState]:
    return RuinNode(
        name=f"missing_{letter.lower()}",
        predicate=lambda state: letter.upper() not in state.candidate.upper(),
        description=f"Required letter '{letter}' not present.",
    )


class StrictSetManifold(WordPuzzleManifold):
    id = "strict_set"

    def __init__(self) -> None:
        super().__init__(
            constraint_set=build_word_game_constraint_set(name="strict_word_puzzle"),
            ruin_nodes=[_missing_required("U")],
            transformation_rules=[],
            seeds={},
            success_signatures=["exact_letter_use"],
        )


class PhoneticVariantManifold(WordPuzzleManifold):
    id = "phonetic_variant"

    def __init__(self) -> None:
        transforms = [
            TransformationRule(
                name="i_j_interchange",
                description="Treat I and J as phonetic variants for this manifold.",
                apply=self._collapse_i_j,
            ),
            TransformationRule(
                name="allow_silent_u",
                description="Silent U is permitted; drop it from the letter set if unused.",
                apply=self._drop_silent_u,
            ),
        ]
        super().__init__(
            constraint_set=build_word_game_constraint_set(name="phonetic_word_puzzle"),
            ruin_nodes=[],
            transformation_rules=transforms,
            seeds={"optional_letters": ["U"]},
            success_signatures=["phonetic_alignment"],
        )

    @staticmethod
    def _collapse_i_j(state: WordGameState) -> WordGameState:
        letters = state.letters.replace("J", "I")
        candidate = state.candidate.replace("J", "I")
        return WordGameState(letters=letters, candidate=candidate)

    @staticmethod
    def _drop_silent_u(state: WordGameState) -> WordGameState:
        if "U" in state.candidate.upper():
            return state
        letters = state.letters.replace("U", "")
        return WordGameState(letters=letters, candidate=state.candidate)


def demo_jailing_vs_jingall(candidate: str = "JAILING") -> Dict[str, Any]:
    """
    Minimal illustration:
    - StrictSetManifold fails JAILING because the provided letters encode a hidden 'U'.
    - PhoneticVariantManifold succeeds by allowing I/J interchange and dropping the silent U.
    """

    sign = WordPuzzleSign(letters="JAIILUNG", candidate=candidate)

    hypotheses: List[InterpretantHypothesis[WordPuzzleSign, WordGameState]] = [
        InterpretantHypothesis(
            id="strict",
            description="Letter-for-letter interpretation; hidden U is mandatory.",
            manifold_factory=lambda _: StrictSetManifold(),
            prior=0.55,
        ),
        InterpretantHypothesis(
            id="phonetic",
            description="Phonetic variant allows I/J swap and silent U.",
            manifold_factory=lambda _: PhoneticVariantManifold(),
            prior=0.45,
            likelihood_fn=lambda s: 1.5 if "PHONETIC" in getattr(s, "letters", "").upper() else 1.0,
        ),
    ]

    manager: InterpretantManager[WordPuzzleSign, WordGameState] = InterpretantManager(hypotheses=hypotheses)
    posterior = manager.update(sign)

    strict_eval = hypotheses[0].manifold_factory(sign).run(sign)
    phonetic_eval = hypotheses[1].manifold_factory(sign).run(sign)

    return {
        "posterior": posterior,
        "strict": strict_eval,
        "phonetic": phonetic_eval,
    }


__all__ = [
    "InterpretantHypothesis",
    "InterpretantManager",
    "Manifold",
    "ManifoldEvaluation",
    "PhoneticVariantManifold",
    "RuinNode",
    "Sign",
    "StrictSetManifold",
    "TransformationRule",
    "WordPuzzleManifold",
    "WordPuzzleSign",
    "demo_jailing_vs_jingall",
]
