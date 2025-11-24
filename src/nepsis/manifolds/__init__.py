"""Manifold registry and base abstractions."""

from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult
from .word_game import WordGameManifold

__all__ = [
    "BaseManifold",
    "TriageResult",
    "ProjectionSpec",
    "ValidationResult",
    "WordGameManifold",
]
