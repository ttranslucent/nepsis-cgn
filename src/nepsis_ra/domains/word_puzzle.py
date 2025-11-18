from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from nepsis_ra.core import (
  ConstraintResult,
  DomainGuess,
  DomainHandler,
  EvaluationStep,
  ManifoldSpec,
  RunTrace,
)


@dataclass
class WordPuzzleManifold(ManifoldSpec):
  letters: str
  target_length: int
  allow_repeats: bool
  constraints: List[Dict[str, Any]]


class WordPuzzleDomainHandler(DomainHandler):
  domain_name: str = "word_puzzle"

  def detect(self, query: str) -> Optional[DomainGuess]:
    lower = query.lower()
    score = 0.0

    if "letters:" in lower or "using these letters" in lower:
      score += 0.6
    if "anagram" in lower or "rearrange the letters" in lower:
      score += 0.3
    if "word" in lower:
      score += 0.1

    if score == 0.0:
      return None

    return DomainGuess(domain=self.domain_name, template_id="exact_anagram", confidence=min(1.0, score))

  def parse_spec(self, query: str) -> Dict[str, Any]:
    spec: Dict[str, Any] = {}
    lower = query.lower()
    if "letters:" in lower:
      part = lower.split("letters:", 1)[1].strip()
      tokens = part.replace(",", " ").split()
      letters = [token for token in tokens if token.isalpha()]
      spec["letters"] = " ".join(letters).upper()

    for token in lower.replace(",", " ").split():
      if token.isdigit():
        spec.setdefault("target_length", int(token))

    spec.setdefault("letters", "")
    spec.setdefault("target_length", len(spec["letters"].replace(" ", "")))
    spec.setdefault("allow_repeats", False)
    spec.setdefault("puzzle_id", None)
    return spec

  def build_manifold(self, template_id: str, spec: Dict[str, Any]) -> WordPuzzleManifold:
    letters = spec["letters"]
    target_length = spec["target_length"]
    allow_repeats = spec.get("allow_repeats", False)
    constraints: List[Dict[str, Any]] = [
      {"type": "LengthConstraint", "weight": 1.0},
      {"type": "LetterMultisetConstraint", "weight": 3.0, "mode": "exact" if not allow_repeats else "subset"},
      {"type": "DictionaryConstraint", "weight": 2.0, "dictionary": "en_US_basic"},
    ]

    return WordPuzzleManifold(
      domain=self.domain_name,
      template_id=template_id,
      config={"dictionary": "en_US_basic"},
      letters=letters,
      target_length=target_length,
      allow_repeats=allow_repeats,
      constraints=constraints,
    )

  def solve(self, manifold: WordPuzzleManifold, spec: Dict[str, Any]) -> Tuple[Any, RunTrace]:
    # TODO: plug into real solver; placeholder for now
    dummy_answer = None
    constraint_results = [
      ConstraintResult("LengthConstraint", 0.0, "Not evaluated (stub)."),
      ConstraintResult("LetterMultisetConstraint", 0.0, "Not evaluated (stub)."),
      ConstraintResult("DictionaryConstraint", 0.0, "Not evaluated (stub)."),
    ]
    step = EvaluationStep(step_index=0, candidate="<stub>", total_score=0.0, constraint_results=constraint_results)

    trace = RunTrace(
      run_id="word_puzzle-stub",
      domain=manifold.domain,
      template_id=manifold.template_id,
      puzzle_id=spec.get("puzzle_id"),
      steps=[step],
      final_choice=dummy_answer,
      success=False,
      meta={"note": "WordPuzzleDomainHandler.solve() is still a stub."},
    )

    return dummy_answer, trace
