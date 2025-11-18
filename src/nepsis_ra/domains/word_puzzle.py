from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import pathlib
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


WORDLIST_PATH = pathlib.Path(__file__).parent.parent / "data" / "wordlist.txt"


@lru_cache(maxsize=1)
def load_dictionary() -> List[str]:
  if not WORDLIST_PATH.exists():
    return []

  with WORDLIST_PATH.open() as f:
    return [line.strip().lower() for line in f if line.strip()]


class WordPuzzleDomainHandler(DomainHandler):
  domain_name: str = "word_puzzle"
  default_template_id: str = "exact_anagram"

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
      letters: List[str] = []
      for token in tokens:
        if token.isalpha() and len(token) == 1:
          letters.append(token.upper())
          continue
        if letters:
          break
      if letters:
        spec["letters"] = " ".join(letters)

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
    letters = manifold.letters.replace(" ", "").lower()
    target_len = manifold.target_length
    allow_repeats = manifold.allow_repeats

    dict_words = load_dictionary()
    allowed_counter = Counter(letters)

    steps: List[EvaluationStep] = []
    best: Optional[str] = None
    candidate_index = 0

    for w in dict_words:
      if len(w) != target_len:
        continue

      crs: List[ConstraintResult] = []

      score_len = 0.0 if len(w) == target_len else 1.0
      crs.append(ConstraintResult("LengthConstraint", score_len, f"len={len(w)}, target={target_len}"))

      candidate_counter = Counter(w)
      if allow_repeats:
        ok_multiset = all(candidate_counter[ch] <= allowed_counter[ch] for ch in candidate_counter)
      else:
        ok_multiset = candidate_counter == allowed_counter

      score_multiset = 0.0 if ok_multiset else 1.0
      crs.append(ConstraintResult("LetterMultisetConstraint", score_multiset, f"ok={ok_multiset}"))

      score_dict = 0.0
      crs.append(ConstraintResult("DictionaryConstraint", score_dict, "in wordlist"))

      total_score = sum(cr.score for cr in crs)
      steps.append(
        EvaluationStep(
          step_index=candidate_index,
          candidate=w,
          total_score=total_score,
          constraint_results=crs,
        )
      )
      candidate_index += 1

      if total_score == 0.0:
        best = w
        break

    success = best is not None

    trace = RunTrace(
      run_id="word_puzzle-v0.1",
      domain=manifold.domain,
      template_id=manifold.template_id,
      puzzle_id=spec.get("puzzle_id"),
      steps=steps,
      final_choice=best,
      success=success,
      meta={"letters": letters, "target_length": target_len},
    )

    return best, trace
