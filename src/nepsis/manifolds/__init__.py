"""Manifold registry and base abstractions."""

from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult
from .gravity_room import GravityRoomManifold
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
    "GravityRoomManifold",
    "UTF8HiddenManifold",
    "Utf8StreamManifold",
    "WordGameManifold",
]
