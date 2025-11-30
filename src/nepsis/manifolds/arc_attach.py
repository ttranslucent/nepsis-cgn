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
        target_shape: Optional[tuple[int, int]] = None
        try:
            parsed = json.loads(raw_query)
            if isinstance(parsed, dict) and "train" in parsed and "test" in parsed:
                grid_bundle = parsed
                confidence = 1.0
                if parsed.get("test"):
                    test_in = parsed["test"][0].get("input", [])
                    rows = len(test_in)
                    cols = len(test_in[0]) if rows > 0 else 0
                    target_shape = (rows, cols)
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
            manifold_meta={"grid_bundle": grid_bundle, "target_shape": target_shape} if grid_bundle else {},
        )

    # --- PROJECTION ---
    def project(self, triage: TriageResult) -> ProjectionSpec:
        bundle = triage.manifold_meta.get("grid_bundle") or {}
        if not bundle or "train" not in bundle:
            raise ValueError("CRITICAL: ArcAttachManifold received no training data. Check JSON input.")
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
        prompt_parts.append(
            "Return ONLY a JSON object with one key 'grid' whose value is the 2D integer array. "
            "Example: {\"grid\": [[0,1],[2,3]]}. Do not use Markdown or explanations."
        )

        system_instruction = (
            "You solve ARC puzzles by inferring geometric/color transformations and producing the correct output grid. "
            "If you respond with anything other than a JSON object of the form {\"grid\": [[...],[...]]}, your answer will be discarded."
        )
        user_prompt = "\n".join(prompt_parts)

        return ProjectionSpec(
            system_instruction=system_instruction,
            manifold_context={"domain": self.name, "target_shape": triage.manifold_meta.get("target_shape")},
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

        grid = None
        try:
            candidate = json.loads(clean)
        except Exception:
            candidate = self._extract_first_json_block(clean)

        if candidate is None:
            violations.append("Output was not valid JSON or could not be parsed.")
        elif isinstance(candidate, dict) and "grid" in candidate:
            grid = candidate.get("grid")
        else:
            grid = candidate

        if grid is not None:
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
            target_shape = projection.manifold_context.get("target_shape")
            if target_shape and not violations:
                rows = len(grid)
                cols = len(grid[0]) if rows > 0 else 0
                if (rows, cols) != target_shape:
                    violations.append(f"Dimension mismatch: expected {target_shape}, got {(rows, cols)}.")
        else:
            violations.append("Output did not contain a parsable grid.")

        if violations:
            return ValidationResult(
                outcome="REJECTED",
                metrics={"red_violations": violations, "blue_score": 0.0},
                final_artifact=grid if grid is not None else artifact,
                repair={
                    "needed": True,
                    "hints": violations,
                    "next_projection_delta": "Ensure output is a JSON object with key 'grid' containing a list of lists of integers.",
                    "tactic": "constraint_injection",
                },
            )

        return ValidationResult(
            outcome="SUCCESS",
            metrics={"red_violations": [], "blue_score": 1.0},
            final_artifact=grid,
            repair={"needed": False},
        )

    @staticmethod
    def _extract_first_json_block(text: str) -> Optional[Any]:
        """
        Heuristic: find the first parseable JSON object/array in the text.
        """
        for start_char in ["{", "["]:
            start = text.find(start_char)
            while start != -1:
                for end in range(len(text), start, -1):
                    chunk = text[start:end]
                    try:
                        return json.loads(chunk)
                    except Exception:
                        continue
                start = text.find(start_char, start + 1)
        return None
