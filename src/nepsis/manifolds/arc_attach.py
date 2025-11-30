import json
from typing import Any, Dict, List, Optional

from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult


class ArcAttachManifold(BaseManifold):
    """
    ARC manifold for presenting train/test grids and enforcing structural validity
    of candidate outputs (hard red channel).
    """

    name = "reasoning.arc_attach"

    # --- TRIAGE ---
    def triage(self, raw_query: str, context: str = "") -> TriageResult:
        grid_bundle: Optional[Dict[str, Any]] = None
        confidence = 0.0
        try:
            parsed = json.loads(raw_query)
            if isinstance(parsed, dict) and "train" in parsed and "test" in parsed:
                grid_bundle = parsed
                confidence = 1.0
        except json.JSONDecodeError:
            confidence = 0.0

        return TriageResult(
            detected_manifold=self.name,
            confidence=confidence,
            is_well_posed=grid_bundle is not None,
            hard_red=[
                "Output must be valid JSON.",
                "Output must be a 2D grid (list of lists).",
                "Grid must contain integers.",
            ],
            hard_blue=["Match ARC output grid for the given test input."],
            soft_blue=[],
            manifold_meta={"grid_bundle": grid_bundle} if grid_bundle else {},
        )

    # --- PROJECTION ---
    def project(self, triage: TriageResult) -> ProjectionSpec:
        bundle = triage.manifold_meta.get("grid_bundle") or {}
        train_pairs = bundle.get("train", [])
        test_inputs = bundle.get("test", [])
        target_input = test_inputs[0]["input"] if test_inputs else []

        prompt_parts: List[str] = [
            "You are an abstract reasoning engine solving an ARC puzzle.",
            "Training examples map INPUT grids to OUTPUT grids.",
            "Analyze the transformation and apply it to the TEST INPUT.",
            "",
        ]

        for idx, pair in enumerate(train_pairs):
            prompt_parts.append(f"--- EXAMPLE {idx + 1} ---")
            prompt_parts.append(f"INPUT: {json.dumps(pair.get('input', []))}")
            prompt_parts.append(f"OUTPUT: {json.dumps(pair.get('output', []))}")
            prompt_parts.append("")

        prompt_parts.append("--- TEST INPUT ---")
        prompt_parts.append(json.dumps(target_input))
        prompt_parts.append("")
        prompt_parts.append("Return ONLY the OUTPUT grid as raw JSON (list of lists). No markdown, no explanations.")

        system_instruction = "You solve ARC puzzles by inferring geometric/color transformations and producing the correct output grid."
        user_prompt = "\n".join(prompt_parts)

        return ProjectionSpec(
            system_instruction=system_instruction,
            manifold_context={"domain": self.name},
            invariants=[
                "Output must be valid JSON.",
                "Output must be a 2D grid (list of lists).",
                "Cells must be integers.",
            ],
            objective_function={"primary": "Produce the correct ARC test output grid."},
            trace={"manifold": self.name, "grid_bundle": bundle, "user_prompt": user_prompt},
        )

    # --- VALIDATION ---
    def validate(self, projection: ProjectionSpec, artifact: Any) -> ValidationResult:
        raw = artifact if isinstance(artifact, str) else str(artifact)
        clean = raw.replace("```json", "").replace("```", "").strip()

        violations: List[str] = []

        try:
            grid = json.loads(clean)
        except json.JSONDecodeError:
            violations.append("Output was not valid JSON.")
            return ValidationResult(
                outcome="REJECTED",
                metrics={"red_violations": violations, "blue_score": 0.0},
                final_artifact=artifact,
                repair={
                    "needed": True,
                    "hints": ["Return only the grid as JSON."],
                    "next_projection_delta": "Emit raw JSON (list of lists).",
                    "tactic": "constraint_injection",
                },
            )

        if not isinstance(grid, list) or not all(isinstance(row, list) for row in grid):
            violations.append("Output must be a 2D grid (list of lists).")
        else:
            for row in grid:
                for cell in row:
                    if not isinstance(cell, int):
                        violations.append("Grid must contain integers only.")
                        break
                if violations:
                    break

        if violations:
            return ValidationResult(
                outcome="REJECTED",
                metrics={"red_violations": violations, "blue_score": 0.0},
                final_artifact=grid,
                repair={
                    "needed": True,
                    "hints": violations,
                    "next_projection_delta": "Ensure output is a JSON list of lists of integers.",
                    "tactic": "constraint_injection",
                },
            )

        return ValidationResult(
            outcome="SUCCESS",
            metrics={"red_violations": [], "blue_score": 1.0},
            final_artifact=grid,
            repair={"needed": False},
        )
