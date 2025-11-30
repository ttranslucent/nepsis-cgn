import json
import re
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult

Grid = List[List[int]]


class ArcAttachManifold(BaseManifold):
    """
    ARC Manifold v2 (Adaptive):
    - Detects 'Physics' (Isometric vs. Fixed vs. Dynamic).
    - Enforces strict JSON formatting.
    - Applies context-aware geometric constraints.
    """

    name = "reasoning.arc_attach"

    # --- TRIAGE: The Physics Engine ---
    def triage(self, raw_query: str, context: str) -> TriageResult:
        data: Optional[Dict[str, Any]] = None
        confidence = 0.0

        # Physics State
        constraint_mode = "UNKNOWN"  # ISOMETRIC, FIXED, or DYNAMIC
        target_shape_hint: Optional[Tuple[int, int]] = None  # (rows, cols) if FIXED

        try:
            data = json.loads(raw_query)
            if isinstance(data, dict) and "train" in data:
                confidence = 1.0

                # Analyze Training Examples to infer Physics
                train_pairs = data["train"]
                input_shapes = []
                output_shapes = []

                for p in train_pairs:
                    # Safely get shapes
                    i_grid = p.get("input", [])
                    o_grid = p.get("output", [])

                    i_r = len(i_grid)
                    i_c = len(i_grid[0]) if i_r > 0 else 0
                    o_r = len(o_grid)
                    o_c = len(o_grid[0]) if o_r > 0 else 0

                    input_shapes.append((i_r, i_c))
                    output_shapes.append((o_r, o_c))

                # 1. ISOMETRIC: Input Shape == Output Shape (Always)
                if all(i == o for i, o in zip(input_shapes, output_shapes)):
                    constraint_mode = "ISOMETRIC"

                # 2. FIXED: Output Shape is constant (but different from input)
                elif len(set(output_shapes)) == 1:
                    constraint_mode = "FIXED"
                    target_shape_hint = output_shapes[0]

                # 3. DYNAMIC: Output Shape varies
                else:
                    constraint_mode = "DYNAMIC"

        except json.JSONDecodeError:
            pass

        return TriageResult(
            detected_manifold=self.name,
            confidence=confidence,
            is_well_posed=(confidence == 1.0),
            manifold_meta={
                "arc_task": data,
                "constraint_mode": constraint_mode,
                "target_shape_hint": target_shape_hint,
            },
            hard_red=["Must be valid JSON.", "Must be 2D Grid."],
        )

    # --- PROJECT: The Instruction ---
    def project(self, triage: TriageResult) -> ProjectionSpec:
        data = triage.manifold_meta.get("arc_task")
        if not data or "train" not in data:
            raise ValueError("CRITICAL: ArcAttachManifold received no training data.")

        train_pairs = data.get("train", [])
        test_cases = data.get("test", [])
        target_input = test_cases[0]["input"] if test_cases else []

        # Force JSON Object wrapper
        system_instruction = (
            "You are an abstract reasoning engine solving an ARC puzzle.\n"
            "You must output a single JSON object containing the solution grid.\n"
            'Format: {"grid": [[row1], [row2], ...]}\n'
            "Do not output Markdown. Do not explain. STRICT JSON ONLY."
        )

        user_prompt_parts = ["TRAINING EXAMPLES:\n"]
        for i, pair in enumerate(train_pairs):
            user_prompt_parts.append(f"--- EXAMPLE {i+1} ---\n")
            user_prompt_parts.append(f"INPUT: {json.dumps(pair['input'])}\n")
            user_prompt_parts.append(f"OUTPUT: {json.dumps(pair['output'])}\n\n")

        user_prompt_parts.append("--- TEST INPUT ---\n")
        user_prompt_parts.append(json.dumps(target_input))

        return ProjectionSpec(
            system_instruction=system_instruction,
            manifold_context=triage.manifold_meta,  # Pass physics context down
            invariants=[
                "Output must be valid JSON.",
                "Output must be a 2D grid (list of lists).",
                "Grid cells must be integers.",
            ],
            objective_function={"primary": "Produce the correct ARC test output grid."},
            trace={"manifold": self.name, "user_prompt": "".join(user_prompt_parts)},
        )

    # --- HELPERS ---
    def _extract_first_json_block(self, text: str) -> Optional[Any]:
        match = re.search(r"[{\\[]", text)
        if not match:
            return None
        start = match.start()
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except Exception:
                continue
        return None

    # --- BLUE CHANNEL: The Quality Judge ---
    def _calculate_blue_score(self, grid: Grid, context: Dict[str, Any]) -> float:
        """
        Heuristic blue score when ground truth is unknown.
        Factors:
          - Palette consistency (penalize hallucinated colors unless training shows new colors)
          - For ISOMETRIC tasks, penalize lazy copies or total noise
        """
        score = 1.0
        task_data = context.get("arc_task", {}) or {}
        mode = context.get("constraint_mode")

        # Palette consistency
        if task_data and "test" in task_data:
            input_grid = task_data["test"][0].get("input", [])
            input_colors = set(c for row in input_grid for c in row) if input_grid else set()
            output_colors = set(c for row in grid for c in row) if grid else set()

            allows_new_colors = False
            for p in task_data.get("train", []):
                t_in = set(c for r in p.get("input", []) for c in r)
                t_out = set(c for r in p.get("output", []) for c in r)
                if not t_out.issubset(t_in):
                    allows_new_colors = True
                    break

            if not allows_new_colors:
                new_colors = output_colors - input_colors
                if new_colors:
                    score -= 0.3  # hallucinated palette

        # ISOMETRIC laziness/noise checks
        if mode == "ISOMETRIC" and task_data.get("test"):
            input_grid = task_data["test"][0].get("input", [])
            if input_grid:
                diffs = 0
                total = len(grid) * len(grid[0]) if grid else 1
                for r in range(len(grid)):
                    for c in range(len(grid[0])):
                        if r < len(input_grid) and c < len(input_grid[0]):
                            if grid[r][c] != input_grid[r][c]:
                                diffs += 1
                if diffs == 0:
                    score -= 0.2  # pure copy
                if diffs == total:
                    score -= 0.1  # total noise

        return max(0.0, min(1.0, score))

    # --- VALIDATE: The Adaptive Guardrails ---
    def validate(self, projection: ProjectionSpec, artifact: Any) -> ValidationResult:
        raw = artifact
        grid: Optional[Grid] = None
        red_violations: List[str] = []
        blue_score = 0.0

        # 1. Parsing (Belt-and-Suspenders)
        try:
            obj = json.loads(str(raw))
        except Exception:
            obj = self._extract_first_json_block(str(raw))

        if obj is None:
            red_violations.append("Output was not valid JSON.")
        else:
            # Unwrap
            if isinstance(obj, dict) and "grid" in obj:
                grid = obj["grid"]
            elif isinstance(obj, list):
                grid = obj
            else:
                red_violations.append("JSON valid but missing 'grid' key.")

        # 2. Topology
        if grid is not None:
            if not isinstance(grid, list) or not all(isinstance(r, list) for r in grid):
                red_violations.append("Output must be a 2D grid.")

        # 3. PHYSICS & GEOMETRY CHECK
        if grid is not None and not red_violations:
            rows = len(grid)
            cols = len(grid[0]) if rows > 0 else 0
            candidate_shape = (rows, cols)

            # Retrieve Physics Context
            mode = projection.manifold_context.get("constraint_mode")
            target_hint = projection.manifold_context.get("target_shape_hint")

            # Get Test Input Shape
            task_data = projection.manifold_context.get("arc_task")
            test_input_shape = None
            if task_data and "test" in task_data:
                t_in = task_data["test"][0]["input"]
                test_input_shape = (len(t_in), len(t_in[0]))

            # Apply Differential Constraints
            if mode == "ISOMETRIC":
                if test_input_shape and candidate_shape != test_input_shape:
                    red_violations.append(
                        f"Constraint Violation (ISOMETRIC): Expected output shape {test_input_shape}, got {candidate_shape}."
                    )

            elif mode == "FIXED":
                if target_hint and candidate_shape != target_hint:
                    red_violations.append(
                        f"Constraint Violation (FIXED): Expected output shape {target_hint}, got {candidate_shape}."
                    )
            elif mode == "DYNAMIC":
                # For extraction tasks, output is usually smaller than input.
                # If LLM returns input size, it's likely lazy/failed.
                if test_input_shape and candidate_shape == test_input_shape:
                    red_violations.append(
                        "Constraint Violation (DYNAMIC): Puzzle implies object extraction. Output should likely be smaller than input."
                    )

        outcome = "SUCCESS" if not red_violations else "REJECTED"
        if outcome == "SUCCESS" and grid is not None:
            # Prefer ground-truth scoring if available
            task_data = projection.manifold_context.get("arc_task", {}) or {}
            ground_truth = None
            if task_data.get("test") and "output" in task_data["test"][0]:
                ground_truth = task_data["test"][0].get("output")
            if ground_truth:
                if len(grid) != len(ground_truth) or (len(grid) > 0 and len(grid[0]) != len(ground_truth[0])):
                    blue_score = 0.0
                else:
                    total = len(grid) * len(grid[0]) if grid else 1
                    errors = 0
                    for r in range(len(grid)):
                        for c in range(len(grid[0])):
                            if grid[r][c] != ground_truth[r][c]:
                                errors += 1
                    blue_score = max(0.0, 1.0 - (errors / total))
            else:
                blue_score = self._calculate_blue_score(grid, projection.manifold_context)

        repair = None
        if outcome == "REJECTED":
            repair = {
                "needed": True,
                "hints": red_violations[:2],
                "next_projection_delta": "Ensure grid dimensions match the task physics.",
                "tactic": "constraint_injection",
            }

        return ValidationResult(
            outcome=outcome,
            metrics={"red_violations": red_violations, "blue_score": blue_score},
            final_artifact=grid if grid else raw,
            repair=repair,
        )
