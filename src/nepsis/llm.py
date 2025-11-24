from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseLLMProvider(ABC):
    """
    Abstraction for pluggable LLM backends.
    """

    @abstractmethod
    def generate(self, projection_spec: Any) -> str:
        """
        Produce a candidate artifact given a projection specification.
        projection_spec may be a dict or ProjectionSpec; implementors should handle both.
        """
        raise NotImplementedError


class SimulatedWordGameLLM(BaseLLMProvider):
    """
    Stub LLM that intentionally hallucinates once, then complies.
    Good for exercising the red-channel repair loop.
    """

    def __init__(self):
        self.attempt_counter = 0

    def generate(self, projection_spec: Any) -> str:
        self.attempt_counter += 1

        # Support both dataclass and dict-like inputs.
        if isinstance(projection_spec, dict):
            ctx = projection_spec.get("manifold_context", {})
        else:
            ctx = getattr(projection_spec, "manifold_context", {})

        letters = ctx.get("letters") or ctx.get("letter_multiset", "")

        # First try: intentionally include an illegal 'S'
        if self.attempt_counter == 1:
            return "JINGLES"

        # Subsequent tries: return a valid candidate
        return "JINGALL" if letters else ""
