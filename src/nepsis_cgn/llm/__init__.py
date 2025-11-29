"""LLM providers and registry for NepsisCGN."""

from typing import Dict, Type

from .openai_provider import OpenAIProvider

# Optional placeholder for future providers. Add them as they are implemented.
# Example: from .simulated import SimulatedProvider

MODEL_REGISTRY: Dict[str, Type] = {
    "openai": OpenAIProvider,
    # "simulated": SimulatedProvider,  # add when available
}

__all__ = ["OpenAIProvider", "MODEL_REGISTRY"]
