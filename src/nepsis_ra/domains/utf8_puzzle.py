from __future__ import annotations

import unicodedata
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
class Utf8Manifold(ManifoldSpec):
  normalize_form: str
  allow_invisible: bool
  allow_mixed_scripts: bool
  constraints: List[Dict[str, Any]]


class Utf8PuzzleDomainHandler(DomainHandler):
  domain_name: str = "utf8_puzzle"
  default_template_id: str = "invisible_equivalence"

  def detect(self, query: str) -> Optional[DomainGuess]:
    lower = query.lower()
    score = 0.0

    if "utf-8" in lower or "unicode" in lower or "codepoint" in lower:
      score += 0.6
    if "looks the same" in lower or "invisible" in lower or "zero width" in lower:
      score += 0.3
    if "copy-paste" in lower or "string bug" in lower:
      score += 0.1

    if score == 0.0:
      return None

    return DomainGuess(domain=self.domain_name, template_id="invisible_equivalence", confidence=min(1.0, score))

  def parse_spec(self, query: str) -> Dict[str, Any]:
    return {
      "reference": None,
      "candidate": query,
      "normalize_form": "NFC",
      "allow_invisible": False,
      "allow_mixed_scripts": False,
      "puzzle_id": None,
    }

  def build_manifold(self, template_id: str, spec: Dict[str, Any]) -> Utf8Manifold:
    normalize_form = spec.get("normalize_form", "NFC")
    allow_invisible = spec.get("allow_invisible", False)
    allow_mixed_scripts = spec.get("allow_mixed_scripts", False)
    constraints = [
      {"type": "NormalizationConstraint", "weight": 4.0, "form": normalize_form},
      {"type": "InvisibleCodepointConstraint", "weight": 5.0},
      {"type": "MixedScriptConstraint", "weight": 3.0},
    ]

    return Utf8Manifold(
      domain=self.domain_name,
      template_id=template_id,
      config={},
      normalize_form=normalize_form,
      allow_invisible=allow_invisible,
      allow_mixed_scripts=allow_mixed_scripts,
      constraints=constraints,
    )

  def solve(self, manifold: Utf8Manifold, spec: Dict[str, Any]) -> Tuple[Any, RunTrace]:
    candidate = spec["candidate"]
    reference = spec.get("reference")

    constraint_results: List[ConstraintResult] = []

    form = manifold.normalize_form
    norm_candidate = unicodedata.normalize(form, candidate)
    norm_reference = unicodedata.normalize(form, reference) if reference is not None else None

    if reference is not None:
      score_norm = 0.0 if norm_candidate == norm_reference else 1.0
      msg_norm = (
        "Normalized candidate matches reference."
        if score_norm == 0.0
        else "Normalized candidate differs from reference."
      )
    else:
      score_norm = 0.0
      msg_norm = "No reference; normalization performed but not compared."

    constraint_results.append(ConstraintResult("NormalizationConstraint", score_norm, msg_norm))

    invisible: List[str] = []
    for char in candidate:
      category = unicodedata.category(char)
      if category in ("Cf", "Cc"):
        invisible.append(f"U+{ord(char):04X} ({unicodedata.name(char, 'UNKNOWN')})")

    score_invisible = 0.0 if (not invisible or manifold.allow_invisible) else 1.0
    msg_invisible = (
      "No invisible/format/control codepoints detected."
      if not invisible
      else f"Invisible/format/control codepoints detected: {', '.join(invisible)}"
    )
    constraint_results.append(ConstraintResult("InvisibleCodepointConstraint", score_invisible, msg_invisible))

    scripts = set()
    for char in candidate:
      try:
        name = unicodedata.name(char)
      except ValueError:
        continue
      if "LATIN" in name:
        scripts.add("LATIN")
      elif "CYRILLIC" in name:
        scripts.add("CYRILLIC")
      elif "GREEK" in name:
        scripts.add("GREEK")

    mixed = len(scripts) > 1
    score_mixed = 0.0 if (not mixed or manifold.allow_mixed_scripts) else 1.0
    msg_mixed = (
      f"Single script detected: {', '.join(sorted(scripts)) or 'none'}."
      if not mixed
      else f"Mixed scripts detected: {', '.join(sorted(scripts))}."
    )
    constraint_results.append(ConstraintResult("MixedScriptConstraint", score_mixed, msg_mixed))

    total_score = sum(result.score for result in constraint_results)
    step = EvaluationStep(step_index=0, candidate=candidate, total_score=total_score, constraint_results=constraint_results)

    is_clean = total_score == 0.0
    trace = RunTrace(
      run_id="utf8_puzzle-mvp",
      domain=manifold.domain,
      template_id=manifold.template_id,
      puzzle_id=spec.get("puzzle_id"),
      steps=[step],
      final_choice=is_clean,
      success=True,
      meta={"reference_provided": reference is not None, "normalize_form": form},
    )

    return is_clean, trace
