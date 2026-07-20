from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping, Optional

from .frame import FrameVersion
from .governance import (
    DEFAULT_EVIDENCE_POLICY_VERSION,
    DEFAULT_GOVERNANCE_POLICY_VERSION,
    GovernanceCalibration,
    GovernanceCosts,
)
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
    policy_version: str = DEFAULT_GOVERNANCE_POLICY_VERSION,
    evidence_policy_version: str = DEFAULT_EVIDENCE_POLICY_VERSION,
    expected_manifest_digest: Optional[str] = None,
    red_evidence_checkpoint: Optional[Mapping[str, Any]] = None,
) -> NavigationController[Any, Any]:
    path = Path(manifest_path) if manifest_path else default_manifest_path()
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found at {path}")
    manifest_digest = f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"
    if expected_manifest_digest is not None and manifest_digest != expected_manifest_digest:
        raise ValueError(
            "Manifest digest mismatch; stored actions cannot be replayed under a changed registry."
        )
    spec = load_manifest_spec(str(path))
    hypotheses = build_interpretants_from_spec(spec, families=families)
    gov_configs = build_governor_configs(spec, families=families)
    manager = InterpretantManager(hypotheses)
    controller = NavigationController(
        manager,
        governor_configs=gov_configs,
        governance_costs=governance_costs,
        governance_calibration=governance_calibration,
        emit_iteration_packet=emit_iteration_packet,
        session_id=session_id,
        frame=frame,
        policy_version=policy_version,
        evidence_policy_version=evidence_policy_version,
        registry_version=manifest_digest,
    )
    if red_evidence_checkpoint is not None:
        controller.import_red_evidence_checkpoint(red_evidence_checkpoint)
    return controller


__all__ = [
    "build_navigation_controller",
    "default_manifest_path",
]
