from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, List, Literal, Mapping, Optional, Sequence, Tuple, TypeVar

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
ChannelSpace = Literal["exploratory", "utility", "ruin"]
DecisionMode = Literal["search", "graded", "boundary"]


@dataclass(frozen=True)
class ChannelSemantics:
    """
    Red/Blue semantics are topology, not a threshold preset.

    - utility: graded decisions inside a bounded-risk space
    - ruin: boundary protection against catastrophic miss
    - exploratory: protected plurality while the system is still searching
    """

    space: ChannelSpace
    label: str
    description: str
    decision_mode: DecisionMode
    closure_rule: str
    memory_rule: str
    invariants: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "space": self.space,
            "label": self.label,
            "description": self.description,
            "decision_mode": self.decision_mode,
            "closure_rule": self.closure_rule,
            "memory_rule": self.memory_rule,
            "invariants": list(self.invariants),
        }


EXPLORATORY_CHANNEL = ChannelSemantics(
    space="exploratory",
    label="Exploratory channel",
    description="Search space that protects plurality while contradictions remain unresolved.",
    decision_mode="search",
    closure_rule="Seek discriminators before closure; avoid forced collapse under unresolved contradiction.",
    memory_rule="Preserve plurality and carry forward contradiction structure across iterations.",
    invariants=(
        "Protected plurality is allowed when contradictions remain live.",
        "Coherence is not completion; unresolved mismatch should trigger more search, not forced unification.",
    ),
)

UTILITY_CHANNEL = ChannelSemantics(
    space="utility",
    label="Blue channel",
    description="Utility/coherence space for graded decisions once ruin boundaries are controlled.",
    decision_mode="graded",
    closure_rule="Collapse is earned by discrimination, low contradiction, and controlled red-channel exposure.",
    memory_rule="Preserve graded uncertainty; do not hard-latch on weak or partial evidence.",
    invariants=(
        "Optimize coherence and expected utility only inside bounded catastrophic risk.",
        "Competing explanations may remain live until a discriminator resolves them.",
    ),
)

RUIN_CHANNEL = ChannelSemantics(
    space="ruin",
    label="Red channel",
    description="Boundary-protection space where catastrophic miss is treated as a constraint, not a tradeoff.",
    decision_mode="boundary",
    closure_rule="When the boundary is crossed, escalate or hold; release requires explicit re-evaluation or reframe.",
    memory_rule="Use hysteresis or explicit release discipline before returning to utility optimization.",
    invariants=(
        "Catastrophic miss is a boundary condition, not a utility term.",
        "Prefer protective friction over false-negative ruin when the boundary is near or crossed.",
        "Severity grants authority over unsafe commitment, not authority over which hypothesis is true.",
        "RED applicability remains falsifiable and competing explanations remain visible.",
        "Protective action must be the least-burdensome reversible response that preserves the boundary.",
    ),
)


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
    catastrophic: bool = False

    def likelihood(self, sign: SignT) -> float:
        if self.likelihood_fn is None:
            return 1.0
        value = float(self.likelihood_fn(sign))
        return max(value, 1e-9)


@dataclass
class ManifoldEvaluation(Generic[StateT]):
    manifold_id: str
    family: str
    channel_semantics: ChannelSemantics
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
        channel_semantics: Optional[ChannelSemantics] = None,
    ):
        self.constraint_set = constraint_set
        self.ruin_nodes: List[RuinNode[StateT]] = list(ruin_nodes or [])
        self.transformation_rules: List[TransformationRule[StateT]] = list(transformation_rules or [])
        self.seeds: Dict[str, Any] = dict(seeds or {})
        self.success_signatures: List[str] = list(success_signatures or [])
        self.channel_semantics = channel_semantics or EXPLORATORY_CHANNEL
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
            channel_semantics=self.channel_semantics,
            state=transformed_state,
            result=result,
            is_ruin=bool(ruin_hits),
            active_transforms=transforms,
            ruin_hits=ruin_hits,
            metadata={
                "seeds": self.seeds,
                "success_signatures": self.success_signatures,
                "constraint_set": self.constraint_set.name,
                "constraint_count": len(self.constraint_set.constraints),
                "channel": self.channel_semantics.to_dict(),
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
        initial_weights = {hyp.id: float(hyp.prior) for hyp in hypotheses}
        if any(
            not math.isfinite(weight) or weight < 0.0
            for weight in initial_weights.values()
        ):
            raise ValueError("Hypothesis priors must be finite and non-negative.")
        normalizer = sum(initial_weights.values())
        if normalizer <= 0.0:
            raise ValueError("Hypothesis priors must have positive total weight.")
        self._posterior: Dict[str, float] = {
            hypothesis_id: weight / normalizer
            for hypothesis_id, weight in initial_weights.items()
        }

    def update(self, sign: SignT) -> Dict[str, float]:
        weights: Dict[str, float] = {}
        for hyp in self._hypotheses.values():
            # Sequential Bayes: previous posterior becomes the next prior.
            prior_weight = self._posterior.get(hyp.id, hyp.prior)
            weights[hyp.id] = max(float(prior_weight), 1e-9) * hyp.likelihood(sign)
        normalizer = sum(weights.values())
        if normalizer == 0.0:
            count = float(len(weights))
            self._posterior = {key: 1.0 / count for key in weights}
        else:
            self._posterior = {key: value / normalizer for key, value in weights.items()}
        return dict(self._posterior)

    def select_manifold(
        self,
        sign: SignT,
        *,
        update_posterior: bool = True,
    ) -> Manifold[StateT]:
        if update_posterior:
            self.update(sign)
        best_id = max(self._posterior, key=self._posterior.get)
        hypothesis = self._hypotheses[best_id]
        return hypothesis.manifold_factory(sign)

    def posterior(self) -> Dict[str, float]:
        return dict(self._posterior)

    def restore_posterior(self, posterior: Mapping[str, float]) -> None:
        if set(posterior) != set(self._hypotheses):
            raise ValueError(
                "Checkpoint posterior hypotheses do not match the active registry."
            )
        restored: Dict[str, float] = {}
        for hypothesis_id, raw_weight in posterior.items():
            weight = float(raw_weight)
            if not math.isfinite(weight) or weight < 0.0:
                raise ValueError(
                    "Checkpoint posterior weights must be finite and non-negative."
                )
            restored[hypothesis_id] = weight
        total = sum(restored.values())
        if total <= 0.0 or not math.isclose(total, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("Checkpoint posterior weights must sum to 1.")
        self._posterior = restored

    def ruin_mass(self, posterior: Optional[Dict[str, float]] = None) -> float:
        if posterior is None:
            posterior = self._posterior
        total = 0.0
        for hid, weight in posterior.items():
            hypothesis = self._hypotheses.get(hid)
            if hypothesis is not None and hypothesis.catastrophic:
                total += float(weight)
        return min(max(total, 0.0), 1.0)


# --- Example: Jailing vs. Jingall word puzzle --------------------------------


@dataclass(frozen=True)
class WordPuzzleSign:
    letters: str
    candidate: str

    def direct_ruin_latch_requires_qualified_release(self) -> bool:
        """Puzzle constraints are fully re-evaluated from each complete sign."""

        return False

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
    "ChannelSpace",
    "ChannelSemantics",
    "DecisionMode",
    "EXPLORATORY_CHANNEL",
    "InterpretantHypothesis",
    "InterpretantManager",
    "Manifold",
    "ManifoldEvaluation",
    "PhoneticVariantManifold",
    "RuinNode",
    "RUIN_CHANNEL",
    "Sign",
    "StrictSetManifold",
    "TransformationRule",
    "UTILITY_CHANNEL",
    "WordPuzzleManifold",
    "WordPuzzleSign",
    "demo_jailing_vs_jingall",
]
