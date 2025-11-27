from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult
from ..stream.utf8_normalizer import Utf8StreamNormalizer


@dataclass
class Utf8StreamConfig:
    """Configuration for UTF-8 stream validation manifold."""

    name: str = "utf8_stream"
    strict: bool = True  # if True, any error => REJECTED
    allow_repair: bool = False  # if True, manifold may return normalized stream as artifact
    max_errors: int = 0  # tolerance threshold for "soft" rejection


class Utf8StreamManifold(BaseManifold):
    """
    Manifold that wraps the Utf8StreamNormalizer red-channel logic.
    Treats UTF-8 validity and RFC-compliance as HARD red constraints.
    """

    def __init__(self, config: Optional[Utf8StreamConfig] = None) -> None:
        self.config = config or Utf8StreamConfig()
        self.name = self.config.name

    # --- TRIAGE ---
    def triage(self, raw_query: str, context: str = "") -> TriageResult:
        hard_red = [
            "must_be_valid_utf8",
            "no_overlong_sequences",
            "no_surrogate_range",
            "no_invalid_continuation_bytes",
        ]
        return TriageResult(
            detected_manifold=self.name,
            confidence=0.95,
            is_well_posed=True,
            hard_red=hard_red,
            hard_blue=[],
            soft_blue=[],
            manifold_meta={},
        )

    # --- PROJECTION ---
    def project(self, triage: TriageResult) -> ProjectionSpec:
        system_instruction = (
            "You are a UTF-8 validation and normalization engine. "
            "You MUST enforce RFC-compliant UTF-8 encoding. "
            "Any overlong encodings, surrogate-range code points, or invalid continuation "
            "bytes are considered hard violations."
        )

        invariants = [
            "Text must be valid UTF-8.",
            "No overlong sequences.",
            "No surrogate-range codepoints.",
            "No invalid continuation bytes.",
        ]

        if self.config.allow_repair:
            invariants.append("If errors are present and repair is enabled, normalize stream.")

        return ProjectionSpec(
            system_instruction=system_instruction,
            manifold_context={
                "domain": self.name,
                "strict": self.config.strict,
                "allow_repair": self.config.allow_repair,
            },
            invariants=invariants,
            objective_function={
                "primary": "Ensure the stream is valid UTF-8 under the RFC constraints.",
            },
            trace={"manifold": self.name},
        )

    # --- VALIDATION ---
    def validate(self, projection: ProjectionSpec, artifact: Union[str, bytes]) -> ValidationResult:
        if isinstance(artifact, str):
            raw_bytes = artifact.encode("utf-8", errors="surrogatepass")
        else:
            raw_bytes = bytes(artifact)

        normalizer = Utf8StreamNormalizer()
        normalized_str, errors = normalizer.process(raw_bytes)

        red_violations: List[str] = [f"Invalid sequence at bytes [{start}:{end}]" for start, end in errors]
        error_count = len(errors)

        strict = self.config.strict
        max_errors = self.config.max_errors

        if (strict and error_count > 0) or (not strict and error_count > max_errors):
            outcome = "REJECTED"
        else:
            outcome = "SUCCESS"

        blue_score = 1.0 if error_count == 0 else 0.0

        repair = None
        if outcome == "REJECTED":
            repair = {
                "needed": True,
                "hints": red_violations[:5],
                "next_projection_delta": "Fix UTF-8 encoding errors.",
                "tactic": "constraint_injection",
            }

        final_artifact: Any = normalized_str if self.config.allow_repair else artifact

        return ValidationResult(
            outcome=outcome,
            metrics={
                "red_violations": red_violations,
                "blue_score": blue_score,
                "drift_detected": False,
                "error_count": error_count,
            },
            final_artifact=final_artifact,
            repair=repair,
            manifold_adherence={"score": blue_score},
        )
