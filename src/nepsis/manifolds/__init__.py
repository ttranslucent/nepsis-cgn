"""Manifold registry and base abstractions."""

from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult
from .seed_manifold import SeedManifold
from .utf8_hidden import UTF8HiddenManifold
from .utf8_stream import Utf8StreamManifold
from .word_game import WordGameManifold

__all__ = [
    "BaseManifold",
    "TriageResult",
    "ProjectionSpec",
    "ValidationResult",
    "SeedManifold",
    "UTF8HiddenManifold",
    "Utf8StreamManifold",
    "WordGameManifold",
]
