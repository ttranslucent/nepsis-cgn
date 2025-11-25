import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

try:
    import openai  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    openai = None


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


def _projection_as_dict(projection_spec: Any) -> Dict[str, Any]:
    """
    Normalize projection spec (dataclass or dict) to a dict.
    """
    if isinstance(projection_spec, dict):
        return projection_spec
    # Fallback for dataclass-like objects
    return {
        "system_instruction": getattr(projection_spec, "system_instruction", ""),
        "manifold_context": getattr(projection_spec, "manifold_context", {}) or {},
        "invariants": getattr(projection_spec, "invariants", []) or [],
        "objective_function": getattr(projection_spec, "objective_function", {}) or {},
        "trace": getattr(projection_spec, "trace", {}) or {},
    }


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


class OpenAIProvider(BaseLLMProvider):
    """
    Provider that sends projection specs to OpenAI Chat Completions.
    """

    def __init__(self, model: str = "gpt-4o"):
        if openai is None:
            raise ImportError("openai package not installed; cannot initialize OpenAIProvider.")
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Credential Failure: OPENAI_API_KEY not found in environment.")
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model

    def generate(self, projection_spec: Any) -> str:
        spec = _projection_as_dict(projection_spec)
        system_instruction = spec.get("system_instruction", "")
        manifold_context = spec.get("manifold_context", {}) or {}
        invariants: List[str] = spec.get("invariants", []) or []
        objective = spec.get("objective_function", {}) or {}

        user_parts: List[str] = []
        if manifold_context:
            user_parts.append(f"Context: {manifold_context}")
        if invariants:
            user_parts.append("Invariants:\n- " + "\n- ".join(invariants))
        if objective:
            user_parts.append(f"Objective: {objective}")
        user_prompt = "\n".join(user_parts) if user_parts else "Follow the system instruction precisely."

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_instruction or "You are a precise reasoning engine. Output exactly what is requested."},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
            )
            return (response.choices[0].message.content or "").strip()
        except Exception as exc:
            return f"Error: {exc}"


def get_llm_provider(model_name: str) -> BaseLLMProvider:
    """
    Factory for LLM providers.
    """
    normalized = model_name.lower()
    if normalized == "simulated":
        return SimulatedWordGameLLM()
    if normalized.startswith("gpt"):
        return OpenAIProvider(model=model_name)
    raise ValueError(f"Unknown model architecture: {model_name}")
