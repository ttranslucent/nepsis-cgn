import json
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple, Optional

from .base import BaseManifold, ProjectionSpec, TriageResult, ValidationResult

Grid = List[List[int]]
Coord = Tuple[int, int]


@dataclass
class GravityObject:
    object_id: int
    cells: List[Coord]


class GravityRoomManifold(BaseManifold):
    """
    The 'Boss Room' for ARC-style Gravity/Object Fall tasks.
    Implements Option B: stepwise simulation with collision sensors.
    """

    name = "reasoning.gravity_room"

    # --- TRIAGE ---
    def triage(self, raw_query: str, context: str) -> TriageResult:
        grid = self._parse_grid(raw_query)
        is_grid = grid is not None

        has_gravity_keywords = any(
            kw in context.lower() for kw in ("gravity", "fall", "drop", "physics", "arc")
        )

        confidence = 0.0
        if is_grid:
            confidence = 0.9 if has_gravity_keywords else 0.5
            if self._detect_floating_objects(grid):
                confidence = max(confidence, 0.8)

        return TriageResult(
            detected_manifold=self.name,
            confidence=confidence,
            is_well_posed=is_grid,
            hard_red=[
                "Conservation of Mass: Objects cannot lose pixels.",
                "Collision Physics: Objects cannot overlap static terrain.",
                "Gravity Vector: Objects must rest on a surface.",
            ],
            hard_blue=["Minimize potential energy (objects should be as low as possible)."],
            soft_blue=[],
            manifold_meta={"input_grid": grid} if is_grid else {},
        )

    # --- PROJECTION ---
    def project(self, triage: TriageResult) -> ProjectionSpec:
        return ProjectionSpec(
            system_instruction=(
                "You are a physics engine solver. "
                "The input is a 2D grid where 0 is empty space. "
                "Apply gravity (+Y) to all mobile objects. "
                "Static terrain (usually defined by the floor) does not move. "
                "Output ONLY the final 2D grid as a JSON list of lists."
            ),
            manifold_context={
                "domain": self.name,
                "laws": ["Gravity applies downwards (+Y).", "Objects fall until collision."],
                "input_grid": triage.manifold_meta.get("input_grid"),
            },
            invariants=[
                "Preserve object shapes (Conservation of Mass).",
                "No overlapping pixels (Collision Physics).",
            ],
            objective_function={"primary": "Calculate equilibrium state."},
            trace={"manifold": self.name, "input_grid": triage.manifold_meta.get("input_grid")},
        )

    # --- VALIDATION ---
    def validate(self, projection: ProjectionSpec, artifact: Any) -> ValidationResult:
        """
        Runs Option B physics simulation and compares candidate to expected equilibrium.
        """
        input_grid = projection.trace.get("input_grid")
        candidate_grid = self._parse_grid(artifact)

        if input_grid is None:
            return ValidationResult("FAILURE", {"error": "Missing input context"}, artifact)
        if candidate_grid is None:
            return ValidationResult(
                "REJECTED",
                {"red_violations": ["Output must be a valid JSON 2D grid."], "blue_score": 0.0},
                artifact,
                repair={
                    "needed": True,
                    "hints": ["Format output as [[0,1], ...]."],
                    "next_projection_delta": "Fix JSON format.",
                    "tactic": "constraint_injection",
                },
            )

        # Extract objects with terrain/mobile separation
        input_objects = self._extract_objects(input_grid)
        candidate_objects = self._extract_objects(candidate_grid)
        violations: List[str] = []

        # Conservation of mass and count
        if len(input_objects) != len(candidate_objects):
            violations.append(f"Object count mismatch: Input {len(input_objects)}, Output {len(candidate_objects)}")
        else:
            for obj_id, in_obj in input_objects.items():
                cand_obj = candidate_objects.get(obj_id)
                if not cand_obj:
                    violations.append(f"Object {obj_id} missing in output.")
                elif len(in_obj.cells) != len(cand_obj.cells):
                    violations.append(
                        f"Mass mismatch for Object {obj_id}: {len(in_obj.cells)} vs {len(cand_obj.cells)} pixels."
                    )

        blue_score = 0.0
        if not violations:
            expected_grid = self._simulate_gravity(input_grid)
            diffs = self._compare_grids(expected_grid, candidate_grid)

            if diffs:
                violations.append("Physics violation: Objects not in equilibrium.")
                for diff in diffs:
                    if diff["type"] == "clipping":
                        violations.append(f"Object {diff['object_id']} clipped through surface at {diff['loc']}.")
                    elif diff["type"] == "levitation":
                        violations.append(f"Object {diff['object_id']} is floating at {diff['loc']}.")
                total_pixels = len(input_grid) * len(input_grid[0]) if input_grid else 1
                blue_score = max(0.0, 1.0 - (len(diffs) / total_pixels))
            else:
                blue_score = 1.0

        outcome = "SUCCESS" if not violations else "REJECTED"
        repair = None
        if outcome == "REJECTED":
            repair = {
                "needed": True,
                "hints": violations[:3],
                "next_projection_delta": "Simulate falling step-by-step. Do not penetrate static blocks.",
                "tactic": "physics_grounding",
            }

        return ValidationResult(
            outcome=outcome,
            metrics={"red_violations": violations, "blue_score": blue_score},
            final_artifact=candidate_grid,
            repair=repair,
        )

    # --- Physics Engine (Option B) ---
    def _simulate_gravity(self, grid: Grid) -> Grid:
        """Stepwise descent simulation for mobile objects; terrain stays fixed."""
        if not grid:
            return []
        height, width = len(grid), len(grid[0])
        sim_grid = [row[:] for row in grid]

        objects = self._extract_objects(sim_grid)

        # Sort by lowest y first (bottom objects settle first)
        sorted_objs = sorted(
            objects.values(),
            key=lambda o: max(y for (_, y) in o.cells) if o.cells else -1,
            reverse=True,
        )

        for obj in sorted_objs:
            self._erase_object(sim_grid, obj)
            while True:
                if self._would_collide(obj, sim_grid, width, height):
                    self._draw_object(sim_grid, obj)
                    break
                obj.cells = [(x, y + 1) for x, y in obj.cells]

        return sim_grid

    def _would_collide(self, obj: GravityObject, grid: Grid, w: int, h: int) -> bool:
        for x, y in obj.cells:
            next_y = y + 1
            if next_y >= h:
                return True
            if grid[next_y][x] != 0:
                return True
        return False

    # --- Helpers ---
    def _parse_grid(self, raw: Any) -> Optional[Grid]:
        try:
            if isinstance(raw, list):
                if all(isinstance(row, list) for row in raw):
                    return raw
            data = json.loads(str(raw))
            if isinstance(data, list) and all(isinstance(row, list) for row in data):
                return data
        except Exception:
            pass
        return None

    def _extract_objects(self, grid: Grid) -> Dict[int, GravityObject]:
        """
        Extracts ONLY mobile objects.
        Heuristic: IDs found in the bottom row are treated as static terrain.
        """
        objects: Dict[int, List[Coord]] = {}
        height = len(grid)
        width = len(grid[0]) if height else 0

        terrain_ids = set()
        if height > 0:
            for x in range(width):
                val = grid[height - 1][x]
                if val != 0:
                    terrain_ids.add(val)

        for y in range(height):
            for x in range(width):
                val = grid[y][x]
                if val != 0 and val not in terrain_ids:
                    objects.setdefault(val, []).append((x, y))

        return {obj_id: GravityObject(object_id=obj_id, cells=cells) for obj_id, cells in objects.items()}

    def _erase_object(self, grid: Grid, obj: GravityObject):
        for x, y in obj.cells:
            grid[y][x] = 0

    def _draw_object(self, grid: Grid, obj: GravityObject):
        for x, y in obj.cells:
            grid[y][x] = obj.object_id

    def _grids_equal(self, g1: Grid, g2: Grid) -> bool:
        if len(g1) != len(g2):
            return False
        if not g1:
            return True
        if len(g1[0]) != len(g2[0]):
            return False
        for r1, r2 in zip(g1, g2):
            if r1 != r2:
                return False
        return True

    def _compare_grids(self, expected: Grid, candidate: Grid) -> List[Dict]:
        diffs = []
        for y in range(len(expected)):
            for x in range(len(expected[0])):
                e, c = expected[y][x], candidate[y][x]
                if e != c:
                    if e == 0 and c != 0:
                        diffs.append({"type": "clipping", "loc": (x, y), "object_id": c})
                    elif e != 0 and c == 0:
                        diffs.append({"type": "levitation", "loc": (x, y), "object_id": e})
        return diffs

    def _detect_floating_objects(self, grid: Grid) -> bool:
        if not grid:
            return False
        h = len(grid)
        w = len(grid[0]) if h else 0
        for y in range(h - 1):
            for x in range(w):
                if grid[y][x] != 0 and grid[y + 1][x] == 0:
                    return True
        return False
