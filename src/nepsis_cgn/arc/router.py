from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

import yaml

from .features import ArcFeatures, extract_task_features


@dataclass
class ManifoldConfig:
    id: str
    dsl_module: str
    gate: dict[str, Any]
    search: dict[str, Any]


class LocalManifoldRouter:
    """Stub interpretant/router for ARC manifolds."""

    def __init__(self, manifest_path: Optional[str] = None):
        self.manifest_path = manifest_path
        self.manifolds: List[ManifoldConfig] = []

    def load_manifest(self) -> None:
        """Populate manifolds from manifest.yaml."""
        path = Path(self.manifest_path) if self.manifest_path else Path(__file__).with_name("manifest.yaml")
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.manifolds = [
            ManifoldConfig(
                id=m["id"],
                dsl_module=m["dsl_module"],
                gate=m.get("gate", {}),
                search=m.get("search", {}),
            )
            for m in raw.get("manifolds", [])
        ]

    def route(self, task_json: dict[str, Any]) -> List[ManifoldConfig]:
        """Return candidate manifolds for the given task."""
        if not self.manifolds:
            self.load_manifest()

        feats: ArcFeatures = extract_task_features(task_json)

        def _passes_gate(cfg: ManifoldConfig) -> bool:
            gate = cfg.gate or {}
            if "same_shape" in gate and gate["same_shape"] != feats.same_shape:
                return False
            # Extend with more gates as features expand.
            return True

        candidates = [m for m in self.manifolds if _passes_gate(m)]
        return candidates or self.manifolds
