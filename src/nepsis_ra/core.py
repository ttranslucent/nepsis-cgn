from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple


@dataclass
class ConstraintResult:
  constraint_id: str
  score: float
  message: str


@dataclass
class EvaluationStep:
  step_index: int
  candidate: Any
  total_score: float
  constraint_results: List[ConstraintResult] = field(default_factory=list)


@dataclass
class RunTrace:
  run_id: str
  domain: str
  template_id: str
  puzzle_id: Optional[str]
  steps: List[EvaluationStep]
  final_choice: Any
  success: bool
  meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainGuess:
  domain: str
  template_id: str
  confidence: float


@dataclass
class DetectionResult:
  primary: DomainGuess
  alternatives: List[DomainGuess] = field(default_factory=list)


@dataclass
class ManifoldSpec:
  domain: str
  template_id: str
  config: Dict[str, Any]


class DomainHandler(Protocol):
  domain_name: str

  def detect(self, query: str) -> Optional[DomainGuess]:
    ...

  def parse_spec(self, query: str) -> Dict[str, Any]:
    ...

  def build_manifold(self, template_id: str, spec: Dict[str, Any]) -> ManifoldSpec:
    ...

  def solve(self, manifold: ManifoldSpec, spec: Dict[str, Any]) -> Tuple[Any, RunTrace]:
    ...


class NepsisRA:
  def __init__(self, domain_handlers: List[DomainHandler]):
    self._domains: Dict[str, DomainHandler] = {handler.domain_name: handler for handler in domain_handlers}

  def run(
    self,
    query: str,
    override_domain: Optional[str] = None,
    override_template: Optional[str] = None,
    puzzle_id: Optional[str] = None,
  ) -> Dict[str, Any]:
    detection = self.detect(query)
    domain = override_domain or detection.primary.domain
    handler = self._get_handler(domain)

    template_id = override_template
    if template_id is None:
      template_id = self._template_for_domain(detection, domain)
    if template_id is None:
      template_id = getattr(handler, "default_template_id", detection.primary.template_id)

    spec = handler.parse_spec(query)
    if puzzle_id is not None:
      spec.setdefault("puzzle_id", puzzle_id)

    manifold = handler.build_manifold(template_id, spec)
    answer, trace = handler.solve(manifold, spec)

    trace.domain = domain
    trace.template_id = template_id
    if trace.puzzle_id is None and "puzzle_id" in spec:
      trace.puzzle_id = spec["puzzle_id"]

    return {
      "answer": answer,
      "domain": domain,
      "template_id": template_id,
      "detection": detection,
      "manifold": manifold,
      "trace": trace,
    }

  def _template_for_domain(self, detection: DetectionResult, domain: str) -> Optional[str]:
    for guess in [detection.primary] + detection.alternatives:
      if guess.domain == domain:
        return guess.template_id
    return None

  def detect(self, query: str) -> DetectionResult:
    guesses: List[DomainGuess] = []

    for handler in self._domains.values():
      guess = handler.detect(query)
      if guess is not None:
        guesses.append(guess)

    if not guesses:
      guesses.append(DomainGuess(domain="word_puzzle", template_id="exact_anagram", confidence=0.1))

    guesses.sort(key=lambda g: g.confidence, reverse=True)
    primary = guesses[0]
    alternatives = guesses[1:]
    return DetectionResult(primary=primary, alternatives=alternatives)

  def _get_handler(self, domain: str) -> DomainHandler:
    if domain not in self._domains:
      raise ValueError(f"Unknown domain: {domain!r}")
    return self._domains[domain]
