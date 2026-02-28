from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .frame import FrameVersion
from .governance import GovernanceCalibration, GovernanceCosts
from .manifest_loader import build_governor_configs, build_interpretants_from_spec, load_manifest_spec
from .navigation import NavigationController
from .interpretant import InterpretantManager


def default_manifest_path() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "manifests" / "manifest_definitions.yaml"


def build_navigation_controller(
    *,
    manifest_path: Optional[str] = None,
    families: Optional[list[str]] = None,
    governance_costs: Optional[GovernanceCosts] = None,
    governance_calibration: Optional[GovernanceCalibration] = None,
    emit_iteration_packet: bool = False,
    session_id: Optional[str] = None,
    frame: Optional[FrameVersion] = None,
) -> NavigationController[Any, Any]:
    path = Path(manifest_path) if manifest_path else default_manifest_path()
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found at {path}")
    spec = load_manifest_spec(str(path))
    hypotheses = build_interpretants_from_spec(spec, families=families)
    gov_configs = build_governor_configs(spec, families=families)
    manager = InterpretantManager(hypotheses)
    return NavigationController(
        manager,
        governor_configs=gov_configs,
        governance_costs=governance_costs,
        governance_calibration=governance_calibration,
        emit_iteration_packet=emit_iteration_packet,
        session_id=session_id,
        frame=frame,
    )


__all__ = [
    "build_navigation_controller",
    "default_manifest_path",
]
