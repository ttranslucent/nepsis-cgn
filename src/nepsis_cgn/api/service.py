from __future__ import annotations

import json
import hashlib
import hmac
import logging
import os
import sqlite3
import base64
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Literal, Optional
from uuid import uuid4

from ..core import (
    DEFAULT_CALIBRATION_VERSION,
    DEFAULT_EVIDENCE_POLICY_VERSION,
    DEFAULT_GOVERNANCE_POLICY_VERSION,
    FrameVersion,
    GovernanceCalibration,
    GovernanceCosts,
    NavigationController,
)
from ..core.case_reasoning import (
    compile_case_reasoning,
    mark_case_reasoning_validation,
    prompt_hash as case_reasoning_prompt_hash,
    threshold_fields_from_case_reasoning,
    validate_case_reasoning,
)
from ..core.interpretant import WordPuzzleSign
from ..core.governance import threshold_crossed
from ..core.runtime import build_navigation_controller
from ..manifolds.clinical import ClinicalSign
from ..manifolds.red_blue import SafetySign
from ..provenance import (
    PacketProvenanceStore,
    build_audit_export,
    build_graph,
    default_provenance_path,
    record_packet_observation,
)
from ..runtime_storage import is_serverless_runtime, serverless_runtime_sessions_path

Family = Literal["puzzle", "clinical", "safety"]
_STORE_SCHEMA_ID = "nepsis.engine_api_sessions"
_STORE_SCHEMA_VERSION = "1.7.0"
_SQLITE_SCHEMA_VERSION = 9
_REPLAY_CONTRACT_VERSION = "nepsis.session_replay@0.3.0"
_WORKSPACE_STATE_MAX_BYTES = 64 * 1024
_STAGE_AUDIT_POLICY = {
    "name": "nepsis_cgn.stage_audit",
    "version": "2026-03-10",
}
_OPERATOR_PHASE_INITIAL = "frame_draft"
_OPERATOR_LEGAL_NEXT_TOOLS: dict[str, list[str]] = {
    "frame_draft": ["get_session_state", "lock_frame", "abandon_session"],
    "frame_locked": ["get_session_state", "run_report", "abandon_session"],
    "report_evaluated": ["get_session_state", "run_report", "lock_report", "abandon_session"],
    "report_locked": ["get_session_state", "set_threshold_decision", "abandon_session"],
    "threshold_set": ["get_session_state", "commit_iteration", "abandon_session"],
}
_DEFAULT_OPERATOR_FRAME = {
    "text": "Operator session draft.",
    "objective_type": "sensemake",
    "domain": "safety",
    "time_horizon": "short",
    "rationale_for_change": (
        "Red channel: keep irreversible bad outcomes explicit | "
        "Blue channel: optimize after red boundaries are controlled | "
        "Uncertainty: the operator has not locked the frame yet"
    ),
    "constraints_hard": ["Maintain RED before BLUE sequencing."],
    "constraints_soft": ["Keep the audit trace concise."],
}
_DEFAULT_OPERATOR_GOVERNANCE_COSTS = {"c_fp": 1.0, "c_fn": 9.0}
LOGGER = logging.getLogger("nepsis_cgn.api.service")


class _StoreDecryptionError(ValueError):
    pass


def default_api_store_path() -> str:
    configured = os.getenv("NEPSIS_API_STORE_PATH")
    if configured and configured.strip():
        return configured
    if is_serverless_runtime():
        return str(serverless_runtime_sessions_path("engine_api_sessions.db"))
    return str((Path.cwd() / "ledger" / "sessions" / "engine_api_sessions.db").resolve())


@dataclass
class EngineSession:
    session_id: str
    family: Family
    created_at: str
    navigation: NavigationController[Any, Any]
    packets: list[Dict[str, Any]]
    steps: int = 0
    manifest_path: Optional[str] = None
    emit_packet: bool = True
    governance_costs: Optional[GovernanceCosts] = None
    governance_calibration: Optional[GovernanceCalibration] = None
    seed_frame_payload: Optional[Dict[str, Any]] = None
    seed_navigation_checkpoint: Optional[Dict[str, Any]] = None
    seed_navigation_checkpoint_digest: Optional[str] = None
    actions: list[Dict[str, Any]] = field(default_factory=list)
    branch_id: str = ""
    lineage_version: int = 1
    parent_frame_id: Optional[str] = None
    owner_id: Optional[str] = None
    workspace_state: Dict[str, Any] = field(default_factory=dict)
    operator_phase: str = _OPERATOR_PHASE_INITIAL
    operator_events: list[Dict[str, Any]] = field(default_factory=list)
    operator_audit: Dict[str, Any] = field(default_factory=dict)
    operator_ambient: bool = False
    operator_checkpoint_active: bool = False
    governance_policy_version: str = DEFAULT_GOVERNANCE_POLICY_VERSION
    evidence_policy_version: str = DEFAULT_EVIDENCE_POLICY_VERSION
    manifest_digest: Optional[str] = None
    replay_contract_version: str = _REPLAY_CONTRACT_VERSION


class EngineApiService:
    def __init__(self, *, store_path: Optional[str] = None, record_provenance: bool = True) -> None:
        self._sessions: Dict[str, EngineSession] = {}
        self._lock = RLock()
        self._store_path = _resolve_store_path(store_path)
        self._record_provenance = record_provenance
        self._load_sessions()
        self._operator_session_id = self._find_ambient_operator_session_id()
        self._apply_retention_policy()

    def create_session(
        self,
        *,
        family: Family,
        manifest_path: Optional[str] = None,
        governance_costs: Optional[Dict[str, float]] = None,
        governance_calibration: Optional[Dict[str, Any]] = None,
        emit_packet: bool = True,
        frame: Optional[Dict[str, Any]] = None,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session_id = str(uuid4())
            normalized_owner_id = _normalize_owner_id(owner_id)
            costs = _parse_governance_costs(governance_costs)
            calibration = (
                _parse_governance_calibration(governance_calibration)
                or GovernanceCalibration()
            )
            seed_frame_payload = _json_copy(frame)
            seed_frame = _frame_from_payload(seed_frame_payload, costs)
            nav = build_navigation_controller(
                manifest_path=manifest_path,
                families=[family],
                governance_costs=costs,
                governance_calibration=calibration,
                emit_iteration_packet=emit_packet,
                session_id=session_id,
                frame=seed_frame,
                policy_version=DEFAULT_GOVERNANCE_POLICY_VERSION,
                evidence_policy_version=DEFAULT_EVIDENCE_POLICY_VERSION,
            )
            if nav.frame is not None:
                seed_frame_payload = nav.frame.to_dict()
            created_at = _now_iso8601()
            seed_navigation_checkpoint = nav.export_red_evidence_checkpoint()
            self._sessions[session_id] = EngineSession(
                session_id=session_id,
                family=family,
                created_at=created_at,
                navigation=nav,
                packets=[],
                manifest_path=manifest_path,
                emit_packet=emit_packet,
                governance_costs=costs,
                governance_calibration=calibration,
                seed_frame_payload=seed_frame_payload,
                seed_navigation_checkpoint=seed_navigation_checkpoint,
                seed_navigation_checkpoint_digest=(
                    _navigation_checkpoint_digest(seed_navigation_checkpoint)
                ),
                branch_id=_initial_branch_id(session_id),
                lineage_version=max(1, _frame_lineage_version(nav.frame)),
                parent_frame_id=None,
                owner_id=normalized_owner_id,
                workspace_state={},
                governance_policy_version=nav.policy_version,
                evidence_policy_version=nav.evidence_policy_version,
                manifest_digest=nav.registry_version,
            )
            self._persist_sessions()
            return self.get_session(session_id)

    def list_sessions(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            page_limit, page_offset = _normalize_pagination(limit=limit, offset=offset)
            normalized_owner_id = _normalize_owner_id(owner_id)
            sessions = self._sessions.values()
            if normalized_owner_id is not None:
                sessions = [s for s in sessions if s.owner_id == normalized_owner_id]
            summaries = [self._session_summary(s) for s in sessions]
            paged = summaries[page_offset : page_offset + page_limit]
            return {
                "sessions": paged,
                "pagination": {
                    "limit": page_limit,
                    "offset": page_offset,
                    "total": len(summaries),
                },
            }

    def get_session(self, session_id: str, *, owner_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id, owner_id=owner_id)
            return self._session_summary(session)

    def get_operator_session_state(self) -> Dict[str, Any]:
        with self._lock:
            session = self._ensure_operator_session()
            return self._operator_state(session)

    def operator_lock_frame(
        self,
        *,
        family: Family,
        frame: Dict[str, Any],
        governance_costs: Optional[Dict[str, float]] = None,
        governance_calibration: Optional[Dict[str, Any]] = None,
        manifest_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._ensure_operator_session()
            if session.operator_phase != "frame_draft":
                return self._phase_rejection(
                    session,
                    attempted_tool="lock_frame",
                    failed_precondition="frame_draft_required",
                    missing=["Fresh draft phase"],
                    coach_prompts=["Commit or abandon the current operator loop before locking a new frame."],
                )

            navigation_checkpoint = None
            if session.operator_checkpoint_active:
                if family != session.family:
                    raise ValueError(
                        "Cannot change operator family while a RED/evidence checkpoint is active; abandon the session to start a new family."
                    )
                navigation_checkpoint = (
                    session.navigation.export_red_evidence_checkpoint()
                )
            self._reset_operator_navigation(
                session,
                family=family,
                frame=frame,
                governance_costs=governance_costs,
                governance_calibration=governance_calibration,
                manifest_path=manifest_path,
                navigation_checkpoint=navigation_checkpoint,
                frame_transition_rationale=(
                    frame.get("rationale_for_change")
                    if isinstance(frame, dict)
                    else None
                ),
            )
            audit = self.stage_audit_session(session.session_id)
            if audit["frame"]["status"] != "PASS":
                return self._phase_rejection(
                    session,
                    attempted_tool="lock_frame",
                    failed_precondition="frame_gate_blocked",
                    gate=audit["frame"],
                )

            session.operator_phase = "frame_locked"
            session.operator_audit = {
                "frame": _json_copy(audit["frame"]),
                "latest_audit": _json_copy(audit),
            }
            _append_operator_event(session, "LOCK_FRAME")
            self._persist_sessions()
            return self._operator_transition_payload(session, audit=audit)

    def operator_run_report(
        self,
        *,
        report_text: str,
        sign: Dict[str, Any],
        interpretation: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._ensure_operator_session()
            if session.operator_phase not in {"frame_locked", "report_evaluated"}:
                return self._phase_rejection(
                    session,
                    attempted_tool="run_report",
                    failed_precondition="lock_frame_required",
                    missing=["Locked frame"],
                    coach_prompts=["Call lock_frame before running a report."],
                )

            step = self._step_session_internal(
                session,
                sign=sign,
                commit=False,
                user_decision=None,
                override_reason=None,
                carry_forward=None,
                record_action=True,
                persist=False,
            )
            context = _operator_stage_context(session)
            interpretation_context = _json_copy(interpretation) if interpretation is not None else {}
            if not isinstance(interpretation_context, dict):
                raise ValueError("interpretation must be an object when provided.")
            interpretation_context.setdefault("report_text", report_text)
            interpretation_context.setdefault("report_synced", True)
            interpretation_context.setdefault("contradictions_status", "none_identified")
            _attach_case_reasoning(
                session,
                interpretation_context,
                report_text=report_text,
            )
            context["interpretation"] = interpretation_context
            threshold_context = context.get("threshold") or {}
            if not isinstance(threshold_context, dict):
                threshold_context = {}
            threshold_context.setdefault("decision", "undecided")
            context["threshold"] = threshold_context
            audit = self.stage_audit_session(
                session.session_id,
                context=context,
                persist_context=True,
            )

            session.operator_phase = "report_evaluated"
            session.operator_audit.update(
                {
                    "interpretation": _json_copy(audit["interpretation"]),
                    "threshold": _json_copy(audit["threshold"]),
                    "latest_audit": _json_copy(audit),
                    "latest_step": _json_copy(step),
                }
            )
            _append_operator_event(session, "RUN_REPORT")
            self._persist_sessions()
            return self._operator_transition_payload(session, step=step, audit=audit)

    def operator_lock_report(self) -> Dict[str, Any]:
        with self._lock:
            session = self._ensure_operator_session()
            if session.operator_phase == "frame_locked":
                return self._phase_rejection(
                    session,
                    attempted_tool="lock_report",
                    failed_precondition="run_report_required",
                    missing=["Evaluated report"],
                    coach_prompts=["Call run_report before locking the report."],
                )
            if session.operator_phase != "report_evaluated":
                return self._phase_rejection(
                    session,
                    attempted_tool="lock_report",
                    failed_precondition="report_evaluated_required",
                    missing=["Evaluated report"],
                    coach_prompts=["Return to the report evaluation phase before locking the report."],
                )

            audit = self.stage_audit_session(session.session_id)
            if audit["interpretation"]["status"] != "PASS":
                return self._phase_rejection(
                    session,
                    attempted_tool="lock_report",
                    failed_precondition="interpretation_gate_blocked",
                    gate=audit["interpretation"],
                )

            session.operator_phase = "report_locked"
            session.operator_audit.update(
                {
                    "interpretation": _json_copy(audit["interpretation"]),
                    "threshold": _json_copy(audit["threshold"]),
                    "latest_audit": _json_copy(audit),
                }
            )
            _append_operator_event(session, "LOCK_REPORT")
            self._persist_sessions()
            return self._operator_transition_payload(session, audit=audit)

    def operator_set_threshold_decision(
        self,
        *,
        decision: str,
        hold_reason: str = "",
        cost_review_acknowledged: bool = False,
        cost_review_rationale: str = "",
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._ensure_operator_session()
            if session.operator_phase != "report_locked":
                return self._phase_rejection(
                    session,
                    attempted_tool="set_threshold_decision",
                    failed_precondition="lock_report_required",
                    missing=["Locked report"],
                    coach_prompts=["Lock a passing report before setting the threshold decision."],
                )

            if decision not in {"recommend", "hold"}:
                raise ValueError("decision must be one of: recommend, hold")
            context = _operator_stage_context(session)
            threshold_context = context.get("threshold") or {}
            if not isinstance(threshold_context, dict):
                threshold_context = {}
            threshold_context["decision"] = decision
            threshold_context["hold_reason"] = hold_reason
            threshold_context["cost_review_acknowledged"] = bool(
                cost_review_acknowledged
            )
            threshold_context["cost_review_rationale"] = str(
                cost_review_rationale or ""
            )
            context["threshold"] = threshold_context
            # Thresholding must never run on raw frame text alone; it depends on
            # a validated Case Reasoning Compiler packet tied to this frame.
            audit = self.stage_audit_session(
                session.session_id,
                context=context,
                persist_context=True,
            )
            if audit["threshold"]["status"] != "PASS":
                return self._phase_rejection(
                    session,
                    attempted_tool="set_threshold_decision",
                    failed_precondition="threshold_gate_blocked",
                    gate=audit["threshold"],
                )

            session.operator_phase = "threshold_set"
            session.operator_audit.update(
                {
                    "threshold": _json_copy(audit["threshold"]),
                    "latest_audit": _json_copy(audit),
                }
            )
            _append_operator_event(session, "SET_THRESHOLD_DECISION")
            self._persist_sessions()
            return self._operator_transition_payload(session, audit=audit)

    def operator_commit_iteration(
        self,
        *,
        carry_forward_frame: Optional[Dict[str, Any]] = None,
        request_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._ensure_operator_session()
            if session.operator_phase != "threshold_set":
                return self._phase_rejection(
                    session,
                    attempted_tool="commit_iteration",
                    failed_precondition="threshold_decision_required",
                    missing=["Threshold decision"],
                    coach_prompts=["Set a passing threshold decision before committing the iteration."],
                )

            audit = self.stage_audit_session(session.session_id)
            if audit["threshold"]["status"] != "PASS":
                return self._phase_rejection(
                    session,
                    attempted_tool="commit_iteration",
                    failed_precondition="threshold_gate_blocked",
                    gate=audit["threshold"],
                )

            final_frame = _merged_frame_payload(session, carry_forward_frame)
            event_log = _operator_event_log_with(session, "COMMIT_ITERATION")
            packet = _build_operator_audit_packet(
                session,
                audit=audit,
                phase_event_log=event_log,
                final_frame=final_frame,
            )
            parent_packet_id = _packet_meta_value(_latest_iteration_packet(session), "packet_id")
            session.packets.append(packet)
            self._record_packet(
                session,
                packet,
                source="ambient_operator_audit",
                retention_mode="retained",
                request_context=request_context,
                parent_packet_id=parent_packet_id,
            )
            session.operator_phase = "frame_draft"
            session.operator_events = []
            session.operator_audit = {
                "last_commit_packet": _json_copy(packet),
                "latest_audit": _json_copy(audit),
            }
            navigation_checkpoint = (
                session.navigation.export_red_evidence_checkpoint()
            )
            session.operator_checkpoint_active = True
            self._reset_operator_navigation(
                session,
                family=session.family,
                frame=final_frame,
                governance_costs=_serialize_governance_costs(session.governance_costs),
                governance_calibration=_serialize_governance_calibration(session.governance_calibration),
                manifest_path=session.manifest_path,
                navigation_checkpoint=navigation_checkpoint,
                frame_transition_rationale=(
                    carry_forward_frame.get("rationale_for_change")
                    if isinstance(carry_forward_frame, dict)
                    else None
                ),
            )
            self._persist_sessions()
            return {
                "session_id": session.session_id,
                "phase": session.operator_phase,
                "legal_next_tools": _legal_next_tools(session.operator_phase),
                "packet": packet,
                "audit": audit,
                "session": self._session_summary(session),
            }

    def operator_abandon_session(
        self,
        *,
        reason: str = "",
        request_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._ensure_operator_session()
            old_session_id = session.session_id
            packet = _build_operator_abandoned_packet(session, reason=reason)
            self._record_packet(
                session,
                packet,
                source="ambient_operator_abandoned",
                retention_mode="retained",
                request_context=request_context,
            )
            session.operator_ambient = False
            session.operator_phase = _OPERATOR_PHASE_INITIAL
            session.operator_events = []
            session.operator_audit = {"abandoned": _json_copy(packet)}
            self._operator_session_id = None
            fresh = self._ensure_operator_session(force_new=True)
            self._persist_sessions()
            return {
                "session_id": fresh.session_id,
                "previous_session_id": old_session_id,
                "phase": fresh.operator_phase,
                "legal_next_tools": _legal_next_tools(fresh.operator_phase),
                "packet": packet,
                "session": self._session_summary(fresh),
            }

    def reframe_session(
        self,
        session_id: str,
        *,
        frame: Dict[str, Any],
        branch_id: Optional[str] = None,
        parent_frame_id: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id, owner_id=owner_id)
            response = self._reframe_session_internal(
                session,
                frame=frame,
                branch_id=branch_id,
                parent_frame_id=parent_frame_id,
                record_action=True,
                persist=True,
            )
            return response

    def step_session(
        self,
        session_id: str,
        *,
        sign: Dict[str, Any],
        commit: bool = False,
        user_decision: Optional[str] = None,
        override_reason: Optional[str] = None,
        carry_forward: Optional[Dict[str, Any]] = None,
        owner_id: Optional[str] = None,
        request_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id, owner_id=owner_id)
            return self._step_session_internal(
                session,
                sign=sign,
                commit=commit,
                user_decision=user_decision,
                override_reason=override_reason,
                carry_forward=carry_forward,
                record_action=True,
                persist=True,
                request_context=request_context,
                record_provenance=True,
            )

    def get_packets(
        self,
        session_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id, owner_id=owner_id)
            page_limit, page_offset = _normalize_pagination(limit=limit, offset=offset)
            total = len(session.packets)
            paged = list(session.packets)[page_offset : page_offset + page_limit]
            return {
                "session_id": session_id,
                "count": total,
                "packets": paged,
                "pagination": {
                    "limit": page_limit,
                    "offset": page_offset,
                    "total": total,
                },
            }

    def get_packet_provenance(
        self,
        session_id: str,
        *,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id, owner_id=owner_id)
            records = PacketProvenanceStore(default_provenance_path()).records_for_session(session.session_id)
            return {
                "session_id": session.session_id,
                "count": len(records),
                "records": records,
                "graph": PacketProvenanceStore(default_provenance_path()).graph_for_session(session.session_id),
            }

    def get_request_provenance(
        self,
        request_id: str,
        *,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not request_id or not request_id.strip():
            raise ValueError("request_id must be non-empty")
        records = PacketProvenanceStore(default_provenance_path()).records_for_request(request_id.strip())
        self._assert_provenance_owner_access(records, owner_id=owner_id)
        return {
            "request_id": request_id.strip(),
            "count": len(records),
            "records": records,
            "graph": build_graph(records),
        }

    def get_packet_lineage(
        self,
        packet_id: str,
        *,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not packet_id or not packet_id.strip():
            raise ValueError("packet_id must be non-empty")
        graph = PacketProvenanceStore(default_provenance_path()).lineage_for_packet(packet_id.strip())
        self._assert_provenance_owner_access(graph.get("nodes", []), owner_id=owner_id)
        return {"packet_id": packet_id.strip(), **graph}

    def export_session_audit(
        self,
        session_id: str,
        *,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id, owner_id=owner_id)
            records = PacketProvenanceStore(default_provenance_path()).records_for_session(session.session_id)
            return build_audit_export(
                session=self._session_summary(session),
                packets=session.packets,
                records=records,
            )

    def stage_audit_session(
        self,
        session_id: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        persist_context: bool = False,
        owner_id: Optional[str] = None,
        request_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id, owner_id=owner_id)
            context_source = "request" if context is not None else "session"
            if context is None:
                context = _stored_stage_audit_context(session.workspace_state)
            normalized_context = _normalize_stage_audit_context(context)
            if "interpretation" in normalized_context:
                report_text = _string_or_default(
                    normalized_context["interpretation"],
                    keys=("report_text", "reportText"),
                    default="",
                )
                _attach_case_reasoning(
                    session,
                    normalized_context["interpretation"],
                    report_text=report_text,
                )
            if persist_context and normalized_context:
                session.workspace_state = _merge_workspace_state(
                    session.workspace_state,
                    {"stage_audit_context": normalized_context},
                )
                self._persist_sessions()
            latest_packet = _latest_iteration_packet(session)

            frame_packet = _build_frame_stage_packet(session, normalized_context.get("frame"))
            interpretation_packet = _build_interpretation_stage_packet(
                normalized_context.get("interpretation"),
                latest_packet,
            )
            threshold_packet = _build_threshold_stage_packet(
                normalized_context.get("threshold"),
                latest_packet,
                interpretation_context=normalized_context.get("interpretation"),
                frame_packet=frame_packet,
            )
            latest_packet_id = _packet_meta_value(latest_packet, "packet_id")
            self._record_packet(
                session,
                frame_packet,
                source="stage_audit_frame",
                retention_mode="retained",
                request_context=request_context,
                parent_packet_id=latest_packet_id,
                sequence=0,
            )
            self._record_packet(
                session,
                interpretation_packet,
                source="stage_audit_interpretation",
                retention_mode="retained",
                request_context=request_context,
                parent_packet_id=latest_packet_id,
                sequence=1,
            )
            self._record_packet(
                session,
                threshold_packet,
                source="stage_audit_threshold",
                retention_mode="retained",
                request_context=request_context,
                parent_packet_id=latest_packet_id,
                sequence=2,
            )

            frame_checks = _evaluate_frame_checks(frame_packet)
            interpretation_checks = _evaluate_interpretation_checks(interpretation_packet)
            threshold_checks = _evaluate_threshold_checks(threshold_packet)

            interpretation_gate = _build_stage_gate(
                checks=interpretation_checks,
                packet=interpretation_packet,
                stage_name="Interpretation",
                prompt_map=_INTERPRETATION_COACH_PROMPTS,
            )
            if isinstance(interpretation_packet.get("case_reasoning_validation"), dict):
                interpretation_gate["case_reasoning_validation"] = _json_copy(
                    interpretation_packet["case_reasoning_validation"]
                )

            threshold_gate = _build_stage_gate(
                checks=threshold_checks,
                packet=threshold_packet,
                stage_name="Threshold",
                prompt_map=_THRESHOLD_COACH_PROMPTS,
            )
            if isinstance(threshold_packet.get("case_reasoning_validation"), dict):
                threshold_gate["case_reasoning_validation"] = _json_copy(
                    threshold_packet["case_reasoning_validation"]
                )

            return {
                "session_id": session.session_id,
                "stage": session.navigation.current_stage,
                "policy": dict(_STAGE_AUDIT_POLICY),
                "frame": _build_stage_gate(
                    checks=frame_checks,
                    packet=frame_packet,
                    stage_name="Frame",
                    prompt_map=_FRAME_COACH_PROMPTS,
                ),
                "interpretation": interpretation_gate,
                "threshold": threshold_gate,
                "source": {
                    "packet_count": len(session.packets),
                    "latest_packet_id": _packet_meta_value(latest_packet, "packet_id"),
                    "latest_iteration": _packet_meta_value(latest_packet, "iteration"),
                    "context_applied": bool(normalized_context),
                    "context_source": context_source if normalized_context else None,
                },
            }

    def update_workspace_state(
        self,
        session_id: str,
        *,
        workspace_state: Dict[str, Any],
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id, owner_id=owner_id)
            session.workspace_state = _normalize_workspace_state(workspace_state)
            self._persist_sessions()
            return self._session_summary(session)

    def delete_session(self, session_id: str, *, owner_id: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id, owner_id=owner_id)
            del self._sessions[session_id]
            self._persist_sessions()
            return {
                "deleted": True,
                "session_id": session_id,
                "family": session.family,
                "remaining_sessions": len(self._sessions),
            }

    def purge_sessions(
        self,
        *,
        max_age_seconds: float,
        dry_run: bool = False,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be > 0.")

        with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now.timestamp() - float(max_age_seconds)
            to_delete: list[str] = []
            normalized_owner_id = _normalize_owner_id(owner_id)

            for sid, session in self._sessions.items():
                if normalized_owner_id is not None and session.owner_id != normalized_owner_id:
                    continue
                created = _parse_iso8601(session.created_at)
                if created.timestamp() <= cutoff:
                    to_delete.append(sid)

            deleted: list[dict[str, str]] = []
            if not dry_run:
                for sid in to_delete:
                    session = self._sessions.pop(sid)
                    deleted.append({"session_id": sid, "family": session.family})
                if to_delete:
                    self._persist_sessions()

            return {
                "purged_count": len(to_delete),
                "purged_sessions": deleted if not dry_run else [{"session_id": sid} for sid in to_delete],
                "dry_run": dry_run,
                "max_age_seconds": float(max_age_seconds),
                "cutoff_at": datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat(timespec="seconds"),
                "remaining_sessions": len(self._sessions) if not dry_run else len(self._sessions),
            }

    def _record_packet(
        self,
        session: EngineSession,
        packet: Dict[str, Any],
        *,
        source: str,
        retention_mode: str,
        request_context: Optional[Dict[str, Any]] = None,
        parent_packet_id: Optional[str] = None,
        sequence: Optional[int] = None,
    ) -> None:
        if not self._record_provenance:
            return
        record_packet_observation(
            packet=packet,
            source=source,
            retention_mode=retention_mode,  # type: ignore[arg-type]
            request_context=request_context,
            session_id=session.session_id,
            owner_id=session.owner_id,
            parent_packet_id=parent_packet_id,
            sequence=sequence,
        )

    def _assert_provenance_owner_access(
        self,
        records_or_nodes: list[Dict[str, Any]],
        *,
        owner_id: Optional[str],
    ) -> None:
        normalized_owner = _normalize_owner_id(owner_id)
        if normalized_owner is None:
            return
        with self._lock:
            for item in records_or_nodes:
                session_id = item.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    continue
                session = self._sessions.get(session_id)
                if session is None:
                    raise PermissionError("session is not available for provenance owner verification")
                if session.owner_id != normalized_owner:
                    raise PermissionError("session owner mismatch")

    def _apply_retention_policy(self) -> None:
        retention_seconds = _configured_retention_seconds()
        if retention_seconds is None:
            return
        try:
            result = self.purge_sessions(max_age_seconds=retention_seconds, dry_run=False)
            if result["purged_count"] > 0:
                LOGGER.info(
                    "retention_purge_applied purged=%s max_age_seconds=%s",
                    result["purged_count"],
                    retention_seconds,
                )
        except Exception:
            LOGGER.exception("retention_purge_failed max_age_seconds=%s", retention_seconds)

    def _find_ambient_operator_session_id(self) -> Optional[str]:
        for session in self._sessions.values():
            if session.operator_ambient:
                return session.session_id
        return None

    def _ensure_operator_session(self, *, force_new: bool = False) -> EngineSession:
        if not force_new and self._operator_session_id is not None:
            session = self._sessions.get(self._operator_session_id)
            if session is not None and session.operator_ambient:
                return session

        if not force_new:
            ambient_session_id = self._find_ambient_operator_session_id()
            if ambient_session_id is not None:
                self._operator_session_id = ambient_session_id
                return self._sessions[ambient_session_id]

        session = self._create_operator_session_unlocked()
        self._persist_sessions()
        return session

    def _create_operator_session_unlocked(self) -> EngineSession:
        session_id = str(uuid4())
        costs = _parse_governance_costs(_DEFAULT_OPERATOR_GOVERNANCE_COSTS)
        calibration = GovernanceCalibration()
        seed_frame_payload = _json_copy(_DEFAULT_OPERATOR_FRAME)
        seed_frame = _frame_from_payload(seed_frame_payload, costs)
        nav = build_navigation_controller(
            manifest_path=None,
            families=["safety"],
            governance_costs=costs,
            governance_calibration=calibration,
            emit_iteration_packet=True,
            session_id=session_id,
            frame=seed_frame,
            policy_version=DEFAULT_GOVERNANCE_POLICY_VERSION,
            evidence_policy_version=DEFAULT_EVIDENCE_POLICY_VERSION,
        )
        if nav.frame is not None:
            seed_frame_payload = nav.frame.to_dict()
        seed_navigation_checkpoint = nav.export_red_evidence_checkpoint()
        session = EngineSession(
            session_id=session_id,
            family="safety",
            created_at=_now_iso8601(),
            navigation=nav,
            packets=[],
            manifest_path=None,
            emit_packet=True,
            governance_costs=costs,
            governance_calibration=calibration,
            seed_frame_payload=seed_frame_payload,
            seed_navigation_checkpoint=seed_navigation_checkpoint,
            seed_navigation_checkpoint_digest=(
                _navigation_checkpoint_digest(seed_navigation_checkpoint)
            ),
            branch_id=_initial_branch_id(session_id),
            lineage_version=max(1, _frame_lineage_version(nav.frame)),
            operator_ambient=True,
            governance_policy_version=nav.policy_version,
            evidence_policy_version=nav.evidence_policy_version,
            manifest_digest=nav.registry_version,
        )
        self._sessions[session_id] = session
        self._operator_session_id = session_id
        return session

    def _reset_operator_navigation(
        self,
        session: EngineSession,
        *,
        family: Family,
        frame: Dict[str, Any],
        governance_costs: Optional[Dict[str, float]],
        governance_calibration: Optional[Dict[str, Any]],
        manifest_path: Optional[str],
        navigation_checkpoint: Optional[Dict[str, Any]] = None,
        frame_transition_rationale: Optional[str] = None,
    ) -> None:
        if family not in {"puzzle", "clinical", "safety"}:
            raise ValueError("family must be one of: puzzle, clinical, safety")
        costs = _parse_governance_costs(governance_costs)
        calibration = (
            _parse_governance_calibration(governance_calibration)
            or GovernanceCalibration()
        )
        seed_frame_payload = _json_copy(frame)
        seed_frame = _frame_from_payload(seed_frame_payload, costs)
        prior_frame = session.navigation.frame
        nav = build_navigation_controller(
            manifest_path=manifest_path,
            families=[family],
            governance_costs=costs,
            governance_calibration=calibration,
            emit_iteration_packet=session.emit_packet,
            session_id=session.session_id,
            frame=seed_frame,
            policy_version=session.governance_policy_version,
            evidence_policy_version=session.evidence_policy_version,
            expected_manifest_digest=(
                session.manifest_digest
                if manifest_path == session.manifest_path
                else None
            ),
            red_evidence_checkpoint=navigation_checkpoint,
        )
        if navigation_checkpoint is not None:
            nav.apply_frame_transition(
                prior_frame=prior_frame,
                rationale_for_change=frame_transition_rationale,
            )
        retained_iteration = _latest_iteration_packet(session)
        if retained_iteration is not None:
            retained_meta = _validated_iteration_packet_meta(retained_iteration)
            nav.restore_packet_lineage(
                last_packet_id=retained_meta["packet_id"],
                next_iteration=retained_meta["iteration"] + 1,
            )
        if nav.frame is not None:
            seed_frame_payload = nav.frame.to_dict()
        session.family = family
        session.manifest_path = manifest_path
        session.governance_costs = costs
        session.governance_calibration = calibration
        session.manifest_digest = nav.registry_version
        session.seed_frame_payload = seed_frame_payload
        session.seed_navigation_checkpoint = nav.export_red_evidence_checkpoint()
        session.seed_navigation_checkpoint_digest = _navigation_checkpoint_digest(
            session.seed_navigation_checkpoint
        )
        session.navigation = nav
        session.actions = []
        session.steps = 0
        session.branch_id = _initial_branch_id(session.session_id)
        session.lineage_version = max(1, _frame_lineage_version(nav.frame))
        session.parent_frame_id = None
        session.workspace_state = _normalize_workspace_state(
            {
                **(_json_copy(session.workspace_state) or {}),
                "stage_audit_context": {
                    "frame": _build_frame_stage_packet(session, None),
                },
            }
        )

    def _operator_state(self, session: EngineSession) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "phase": session.operator_phase,
            "legal_next_tools": _legal_next_tools(session.operator_phase),
            "audit": _json_copy(session.operator_audit) or {},
            "session": self._session_summary(session),
        }

    def _operator_transition_payload(
        self,
        session: EngineSession,
        *,
        step: Optional[Dict[str, Any]] = None,
        audit: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "session_id": session.session_id,
            "phase": session.operator_phase,
            "legal_next_tools": _legal_next_tools(session.operator_phase),
            "session": self._session_summary(session),
        }
        if step is not None:
            payload["step"] = step
        if audit is not None:
            payload["audit"] = audit
        return payload

    def _phase_rejection(
        self,
        session: EngineSession,
        *,
        attempted_tool: str,
        failed_precondition: str,
        gate: Optional[Dict[str, Any]] = None,
        missing: Optional[list[str]] = None,
        coach_prompts: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        gate_status = "BLOCK"
        gate_missing = list(missing or [])
        prompts = list(coach_prompts or [])
        if isinstance(gate, dict):
            gate_status = str(gate.get("status") or "BLOCK")
            raw_missing = gate.get("missing")
            if isinstance(raw_missing, list):
                gate_missing = [str(item) for item in raw_missing if str(item)]
            coach = gate.get("coach")
            if isinstance(coach, dict) and isinstance(coach.get("prompts"), list):
                prompts = [str(item) for item in coach["prompts"] if str(item)]

        return {
            "schema_id": "nepsis.phase_rejection",
            "schema_version": "1.0.0",
            "attempted_tool": attempted_tool,
            "failed_precondition": failed_precondition,
            "current_phase": session.operator_phase,
            "legal_next_tools": _legal_next_tools(session.operator_phase),
            "session_id": session.session_id,
            "gate_status": gate_status,
            "missing": gate_missing,
            "coach_prompts": prompts,
        }

    def _step_session_internal(
        self,
        session: EngineSession,
        *,
        sign: Dict[str, Any],
        commit: bool,
        user_decision: Optional[str],
        override_reason: Optional[str],
        carry_forward: Optional[Dict[str, Any]],
        record_action: bool,
        persist: bool,
        request_context: Optional[Dict[str, Any]] = None,
        record_provenance: bool = True,
    ) -> Dict[str, Any]:
        nav = session.navigation
        if session.seed_navigation_checkpoint is None and not session.actions:
            session.seed_navigation_checkpoint = (
                nav.export_red_evidence_checkpoint()
            )
            session.seed_navigation_checkpoint_digest = (
                _navigation_checkpoint_digest(
                    session.seed_navigation_checkpoint
                )
            )
        typed_sign = _build_sign(session.family, sign)
        entry = nav.step(
            typed_sign,
            commit=commit,
            user_decision=user_decision,
            override_reason=override_reason,
            carry_forward_policy=carry_forward,
        )
        if session.seed_frame_payload is None and nav.frame is not None:
            session.seed_frame_payload = nav.frame.to_dict()
        session.steps += 1

        payload = _trace_payload(entry)
        if entry.iteration_packet is not None:
            # API session_id is canonical for all externally exposed packets.
            entry.iteration_packet["meta"]["session_id"] = session.session_id
            session.packets.append(entry.iteration_packet)
            if record_provenance:
                self._record_packet(
                    session,
                    entry.iteration_packet,
                    source="runtime_iteration",
                    retention_mode="retained",
                    request_context=request_context,
                )
            payload["iteration_packet"] = entry.iteration_packet

        if record_action:
            session.actions.append(
                {
                    "kind": "step",
                    "sign": _json_copy(sign),
                    "commit": bool(commit),
                    "user_decision": user_decision,
                    "override_reason": override_reason,
                    "carry_forward": _json_copy(carry_forward),
                }
            )

        payload["session"] = self._session_summary(session)
        if persist:
            self._persist_sessions()
        return payload

    def _reframe_session_internal(
        self,
        session: EngineSession,
        *,
        frame: Dict[str, Any],
        branch_id: Optional[str],
        parent_frame_id: Optional[str],
        record_action: bool,
        persist: bool,
    ) -> Dict[str, Any]:
        nav = session.navigation
        previous_frame_ref = _frame_ref(nav.frame)
        resolved_branch_id = _normalize_branch_id(
            branch_id,
            fallback=session.branch_id or _initial_branch_id(session.session_id),
        )
        if parent_frame_id is None:
            resolved_parent_frame_id = previous_frame_ref
        else:
            resolved_parent_frame_id = _optional_parent_frame_id(parent_frame_id)
        updated = nav.reframe(
            text=frame.get("text"),
            objective_type=frame.get("objective_type"),
            domain=frame.get("domain"),
            time_horizon=frame.get("time_horizon"),
            rationale_for_change=frame.get("rationale_for_change"),
            constraints_hard=frame.get("constraints_hard"),
            constraints_soft=frame.get("constraints_soft"),
        )
        session.branch_id = resolved_branch_id
        session.parent_frame_id = resolved_parent_frame_id
        session.lineage_version = max(session.lineage_version + 1, _frame_lineage_version(updated))
        if record_action:
            session.actions.append(
                {
                    "kind": "reframe",
                    "frame": _json_copy(frame),
                    "branch_id": session.branch_id,
                    "parent_frame_id": session.parent_frame_id,
                }
            )
        if persist:
            self._persist_sessions()
        return {
            "session_id": session.session_id,
            "frame": updated.to_dict(),
            "stage": nav.current_stage,
            "branch_id": session.branch_id,
            "lineage_version": session.lineage_version,
            "parent_frame_id": session.parent_frame_id,
            "frame_ref": _frame_ref(updated),
        }

    def _session_summary(self, session: EngineSession) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "family": session.family,
            "created_at": session.created_at,
            "stage": session.navigation.current_stage,
            "steps": session.steps,
            "packet_count": len(session.packets),
            "frame": session.navigation.frame.to_dict() if session.navigation.frame else None,
            "frame_ref": _frame_ref(session.navigation.frame),
            "branch_id": session.branch_id,
            "lineage_version": session.lineage_version,
            "parent_frame_id": session.parent_frame_id,
            "owner_id": session.owner_id,
            "workspace_state": _json_copy(session.workspace_state) or {},
            "storage": "disk" if self._store_path is not None else "memory",
            "manifest_path": session.manifest_path,
            "governance": _serialize_governance_costs(session.governance_costs),
            "calibration": _serialize_governance_calibration(session.governance_calibration),
            "governance_policy_version": session.governance_policy_version,
            "evidence_policy_version": session.evidence_policy_version,
            "manifest_digest": session.manifest_digest,
            "replay_contract_version": session.replay_contract_version,
            "operator_checkpoint_active": session.operator_checkpoint_active,
            "operator_phase": session.operator_phase,
            "operator_ambient": session.operator_ambient,
        }

    def _require_session(self, session_id: str, *, owner_id: Optional[str] = None) -> EngineSession:
        if session_id not in self._sessions:
            raise KeyError(f"Unknown session_id: {session_id}")
        session = self._sessions[session_id]
        normalized_owner_id = _normalize_owner_id(owner_id)
        if normalized_owner_id is not None and session.owner_id != normalized_owner_id:
            raise PermissionError("Session is not owned by the authenticated identity.")
        return session

    def _load_sessions(self) -> None:
        if self._store_path is None or not self._store_path.exists():
            return
        if _is_sqlite_store_path(self._store_path):
            self._load_sessions_sqlite()
            return
        self._load_sessions_json()

    def _load_sessions_json(self) -> None:
        assert self._store_path is not None
        try:
            raw = _open_text(self._store_path.read_text(encoding="utf-8"))
            if not raw.strip():
                return

            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("Session store must be a JSON object.")
            sessions = data.get("sessions", [])
            if not isinstance(sessions, list):
                raise ValueError("Session store 'sessions' must be a list.")
        except _StoreDecryptionError:
            raise
        except Exception as exc:
            self._recover_corrupt_store(exc)
            return

        for item in sessions:
            restored = self._restore_session(item)
            self._sessions[restored.session_id] = restored

    def _load_sessions_sqlite(self) -> None:
        assert self._store_path is not None
        try:
            with self._open_sqlite() as conn:
                self._ensure_sqlite_schema(conn)
                rows = conn.execute(
                    """
                    SELECT session_id, family, created_at, steps, manifest_path, emit_packet,
                           governance_costs_json, governance_calibration_json,
                           governance_policy_version, evidence_policy_version, manifest_digest,
                           replay_contract_version, seed_frame_json, actions_json, packets_json,
                           packet_artifacts_digest,
                           seed_navigation_checkpoint_json,
                           seed_navigation_checkpoint_digest,
                           branch_id, lineage_version, parent_frame_id, owner_id, workspace_state_json,
                           operator_phase, operator_events_json, operator_audit_json, operator_ambient,
                           operator_checkpoint_active
                    FROM engine_sessions
                    """
                ).fetchall()
        except _StoreDecryptionError:
            raise
        except Exception as exc:
            self._recover_corrupt_store(exc)
            return

        for row in rows:
            payload = {
                "session_id": row[0],
                "family": row[1],
                "created_at": row[2],
                "steps": row[3],
                "manifest_path": row[4],
                "emit_packet": bool(row[5]),
                "governance_costs": _json_loads_or_none(row[6], encrypted=True),
                "governance_calibration": _json_loads_or_none(row[7], encrypted=True),
                "governance_policy_version": row[8],
                "evidence_policy_version": row[9],
                "manifest_digest": row[10],
                "replay_contract_version": row[11],
                "seed_frame": _json_loads_or_none(row[12], encrypted=True),
                "actions": _json_loads_or_none(row[13], encrypted=True) or [],
                "packets": _json_loads_or_none(row[14], encrypted=True) or [],
                "packet_artifacts_digest": row[15],
                "seed_navigation_checkpoint": _json_loads_or_none(
                    row[16], encrypted=True
                ),
                "seed_navigation_checkpoint_digest": row[17],
                "branch_id": row[18],
                "lineage_version": row[19],
                "parent_frame_id": row[20],
                "owner_id": row[21],
                "workspace_state": _json_loads_or_none(row[22], encrypted=True) or {},
                "operator_phase": row[23],
                "operator_events": _json_loads_or_none(row[24], encrypted=True) or [],
                "operator_audit": _json_loads_or_none(row[25], encrypted=True) or {},
                "operator_ambient": bool(row[26]),
                "operator_checkpoint_active": bool(row[27]),
            }
            restored = self._restore_session(payload)
            self._sessions[restored.session_id] = restored

    def _restore_session(self, payload: Dict[str, Any]) -> EngineSession:
        if not isinstance(payload, dict):
            raise ValueError("Invalid session payload in store.")

        family = payload.get("family")
        if family not in {"puzzle", "clinical", "safety"}:
            raise ValueError("Stored session has unsupported family.")

        session_id = str(payload.get("session_id") or uuid4())
        created_at = str(payload.get("created_at") or _now_iso8601())
        manifest_path = payload.get("manifest_path")
        owner_id = _normalize_owner_id(payload.get("owner_id"))
        emit_packet = bool(payload.get("emit_packet", True))
        costs = _parse_governance_costs(payload.get("governance_costs"))
        stored_actions = payload.get("actions")
        if stored_actions is not None and not isinstance(stored_actions, list):
            raise ValueError("Stored session actions must be a list.")
        actions = stored_actions or []
        stored_packets_raw = payload.get("packets")
        if stored_packets_raw is not None and not isinstance(stored_packets_raw, list):
            raise ValueError("Stored session packets must be a list.")
        stored_packets = stored_packets_raw or []
        if not all(isinstance(packet, dict) for packet in stored_packets):
            raise ValueError("Stored session packets must contain only objects.")
        operator_checkpoint_active = payload.get(
            "operator_checkpoint_active", False
        )
        if not isinstance(operator_checkpoint_active, bool):
            raise ValueError("Stored operator_checkpoint_active must be boolean.")
        replay_contract_version = str(payload.get("replay_contract_version") or "")
        if (
            actions or stored_packets or operator_checkpoint_active
        ) and replay_contract_version != _REPLAY_CONTRACT_VERSION:
            raise ValueError(
                "Stored replay state predates the pinned artifact contract and cannot be restored safely."
            )
        stored_packet_artifacts_digest = payload.get("packet_artifacts_digest")
        if replay_contract_version == _REPLAY_CONTRACT_VERSION and (
            not isinstance(stored_packet_artifacts_digest, str)
            or not stored_packet_artifacts_digest.strip()
        ):
            raise ValueError(
                "Stored packet artifacts have no integrity digest."
            )
        if stored_packet_artifacts_digest is not None:
            if not isinstance(stored_packet_artifacts_digest, str):
                raise ValueError("Stored packet artifact digest must be a string.")
            expected_packet_artifacts_digest = _packet_artifacts_digest(
                stored_packets
            )
            if not hmac.compare_digest(
                stored_packet_artifacts_digest,
                expected_packet_artifacts_digest,
            ):
                raise ValueError(
                    "Stored packet artifacts failed integrity validation."
                )
        governance_policy_version = str(
            payload.get("governance_policy_version")
            or DEFAULT_GOVERNANCE_POLICY_VERSION
        )
        evidence_policy_version = str(
            payload.get("evidence_policy_version")
            or DEFAULT_EVIDENCE_POLICY_VERSION
        )
        manifest_digest = payload.get("manifest_digest")
        if manifest_digest is not None:
            manifest_digest = str(manifest_digest)
        if (actions or stored_packets or operator_checkpoint_active) and not manifest_digest:
            raise ValueError(
                "Stored replay state has no pinned manifest digest and cannot be restored safely."
            )
        calibration = (
            _parse_governance_calibration(payload.get("governance_calibration"))
            or GovernanceCalibration()
        )

        seed_frame_payload = _json_copy(payload.get("seed_frame"))
        seed_navigation_checkpoint = _json_copy(
            payload.get("seed_navigation_checkpoint")
        )
        if seed_navigation_checkpoint is not None and not isinstance(
            seed_navigation_checkpoint, dict
        ):
            raise ValueError("Stored navigation checkpoint must be an object.")
        seed_navigation_checkpoint_digest = payload.get(
            "seed_navigation_checkpoint_digest"
        )
        if seed_navigation_checkpoint is None:
            if seed_navigation_checkpoint_digest is not None:
                raise ValueError(
                    "Stored navigation checkpoint digest has no checkpoint."
                )
        else:
            if not isinstance(seed_navigation_checkpoint_digest, str) or not (
                seed_navigation_checkpoint_digest.strip()
            ):
                raise ValueError(
                    "Stored navigation checkpoint has no integrity digest."
                )
            expected_checkpoint_digest = _navigation_checkpoint_digest(
                seed_navigation_checkpoint
            )
            if not hmac.compare_digest(
                seed_navigation_checkpoint_digest,
                expected_checkpoint_digest,
            ):
                raise ValueError(
                    "Stored navigation checkpoint failed integrity validation."
                )
        if actions and seed_frame_payload is None:
            raise ValueError(
                "Stored action stream has no canonical seed frame and cannot be replayed safely."
            )
        if (actions or operator_checkpoint_active) and seed_navigation_checkpoint is None:
            raise ValueError(
                "Stored replay state has no RED/evidence checkpoint and cannot be restored safely."
            )
        seed_frame = _frame_from_payload(seed_frame_payload, costs)
        nav = build_navigation_controller(
            manifest_path=manifest_path,
            families=[family],
            governance_costs=costs,
            governance_calibration=calibration,
            emit_iteration_packet=emit_packet,
            session_id=session_id,
            frame=seed_frame,
            policy_version=governance_policy_version,
            evidence_policy_version=evidence_policy_version,
            expected_manifest_digest=manifest_digest,
            red_evidence_checkpoint=seed_navigation_checkpoint,
        )
        if seed_navigation_checkpoint is None:
            seed_navigation_checkpoint = nav.export_red_evidence_checkpoint()
            seed_navigation_checkpoint_digest = _navigation_checkpoint_digest(
                seed_navigation_checkpoint
            )
        session = EngineSession(
            session_id=session_id,
            family=family,
            created_at=created_at,
            navigation=nav,
            packets=[],
            steps=0,
            manifest_path=manifest_path,
            emit_packet=emit_packet,
            governance_costs=costs,
            governance_calibration=calibration,
            seed_frame_payload=seed_frame_payload,
            seed_navigation_checkpoint=seed_navigation_checkpoint,
            seed_navigation_checkpoint_digest=seed_navigation_checkpoint_digest,
            branch_id=_initial_branch_id(session_id),
            lineage_version=max(1, _frame_lineage_version(nav.frame)),
            parent_frame_id=None,
            owner_id=owner_id,
            workspace_state=_normalize_workspace_state(payload.get("workspace_state") or {}),
            operator_phase=_normalize_operator_phase(payload.get("operator_phase")),
            operator_events=_normalize_operator_events(payload.get("operator_events")),
            operator_audit=_normalize_operator_audit(payload.get("operator_audit")),
            operator_ambient=bool(payload.get("operator_ambient", False)),
            operator_checkpoint_active=operator_checkpoint_active,
            governance_policy_version=governance_policy_version,
            evidence_policy_version=evidence_policy_version,
            manifest_digest=nav.registry_version,
            replay_contract_version=(
                replay_contract_version or _REPLAY_CONTRACT_VERSION
            ),
        )

        step_action_count = 0
        for action in actions:
            if not isinstance(action, dict):
                raise ValueError("Stored replay actions must contain only objects.")
            kind = action.get("kind")
            if kind == "step":
                step_action_count += 1
            elif kind != "reframe":
                raise ValueError(f"Unsupported stored replay action kind: {kind!r}.")

        stored_iteration_packets = _iteration_packets_from_artifacts(
            stored_packets
        )
        expected_iteration_count = step_action_count if emit_packet else 0
        if len(stored_iteration_packets) < expected_iteration_count:
            raise ValueError(
                "Stored packet artifacts are incomplete for the replay action stream."
            )
        prior_iteration_count = len(stored_iteration_packets) - expected_iteration_count
        if prior_iteration_count and not operator_checkpoint_active:
            raise ValueError(
                "Stored packet artifacts contain history outside the replay action stream."
            )
        if not emit_packet and stored_iteration_packets:
            raise ValueError(
                "Stored iteration packets are incompatible with emit_packet=false."
            )
        if prior_iteration_count:
            prior_meta = _validated_iteration_packet_meta(
                stored_iteration_packets[prior_iteration_count - 1]
            )
            nav.restore_packet_lineage(
                last_packet_id=prior_meta["packet_id"],
                next_iteration=prior_meta["iteration"] + 1,
            )

        for action in actions:
            if not isinstance(action, dict):
                raise ValueError("Stored replay actions must contain only objects.")
            kind = action.get("kind")
            if kind == "step":
                sign = _json_copy(action.get("sign"))
                if not isinstance(sign, dict):
                    raise ValueError("Stored step action requires an object sign.")
                self._step_session_internal(
                    session,
                    sign=sign,
                    commit=bool(action.get("commit", False)),
                    user_decision=action.get("user_decision"),
                    override_reason=action.get("override_reason"),
                    carry_forward=_json_copy(action.get("carry_forward")),
                    record_action=False,
                    persist=False,
                    record_provenance=False,
                )
            elif kind == "reframe":
                frame = _json_copy(action.get("frame"))
                if not isinstance(frame, dict):
                    raise ValueError("Stored reframe action requires an object frame.")
                self._reframe_session_internal(
                    session,
                    frame=frame,
                    branch_id=action.get("branch_id"),
                    parent_frame_id=action.get("parent_frame_id"),
                    record_action=False,
                    persist=False,
                )
            else:
                raise ValueError(f"Unsupported stored replay action kind: {kind!r}.")

        generated_packets = _json_copy(session.packets) or []
        _validate_replayed_packet_artifacts(
            stored_packets=stored_packets,
            generated_packets=generated_packets,
            emit_packet=emit_packet,
            allow_prior_history=operator_checkpoint_active,
        )
        session.actions = _json_copy(actions) or []
        session.packets = _json_copy(stored_packets) or []
        if stored_iteration_packets:
            last_meta = _validated_iteration_packet_meta(
                stored_iteration_packets[-1]
            )
            nav.restore_packet_lineage(
                last_packet_id=last_meta["packet_id"],
                next_iteration=last_meta["iteration"] + 1,
            )
        stored_steps = int(payload.get("steps") or 0)
        if stored_steps != session.steps:
            raise ValueError(
                "Stored step count diverges from the replayed action stream."
            )
        session.branch_id = _normalize_branch_id(payload.get("branch_id"), fallback=session.branch_id)
        stored_lineage_version = _coerce_lineage_version(payload.get("lineage_version"))
        if stored_lineage_version is not None:
            session.lineage_version = max(session.lineage_version, stored_lineage_version)
        if "parent_frame_id" in payload:
            session.parent_frame_id = _optional_parent_frame_id(payload.get("parent_frame_id"))
        return session

    def _persist_sessions(self) -> None:
        if self._store_path is None:
            return

        if _is_sqlite_store_path(self._store_path):
            self._persist_sessions_sqlite()
            return
        self._persist_sessions_json()

    def _persist_sessions_json(self) -> None:
        assert self._store_path is not None
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_id": _STORE_SCHEMA_ID,
            "schema_version": _STORE_SCHEMA_VERSION,
            "saved_at": _now_iso8601(),
            "sessions": [self._serialize_session(session) for session in self._sessions.values()],
        }

        tmp_path = self._store_path.with_suffix(f"{self._store_path.suffix}.tmp")
        raw_text = json.dumps(payload, indent=2, sort_keys=True)
        tmp_path.write_text(_seal_text(raw_text), encoding="utf-8")
        tmp_path.replace(self._store_path)

    def _persist_sessions_sqlite(self) -> None:
        assert self._store_path is not None
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        with self._open_sqlite() as conn:
            self._ensure_sqlite_schema(conn)
            with conn:
                conn.execute("DELETE FROM engine_sessions")
                for session in self._sessions.values():
                    row = self._serialize_session(session)
                    conn.execute(
                        """
                        INSERT INTO engine_sessions(
                            session_id, family, created_at, steps, manifest_path, emit_packet,
                            governance_costs_json, governance_calibration_json,
                            governance_policy_version, evidence_policy_version, manifest_digest,
                            replay_contract_version, seed_frame_json, actions_json, packets_json,
                            packet_artifacts_digest,
                            seed_navigation_checkpoint_json,
                            seed_navigation_checkpoint_digest,
                            branch_id, lineage_version, parent_frame_id, owner_id, workspace_state_json,
                            operator_phase, operator_events_json, operator_audit_json, operator_ambient,
                            operator_checkpoint_active
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            row["session_id"],
                            row["family"],
                            row["created_at"],
                            int(row["steps"]),
                            row["manifest_path"],
                            1 if row["emit_packet"] else 0,
                            _json_dumps_or_none(row.get("governance_costs"), encrypted=True),
                            _json_dumps_or_none(row.get("governance_calibration"), encrypted=True),
                            row["governance_policy_version"],
                            row["evidence_policy_version"],
                            row["manifest_digest"],
                            row["replay_contract_version"],
                            _json_dumps_or_none(row.get("seed_frame"), encrypted=True),
                            _json_dumps_or_none(row.get("actions"), encrypted=True),
                            _json_dumps_or_none(row.get("packets"), encrypted=True),
                            row["packet_artifacts_digest"],
                            _json_dumps_or_none(
                                row.get("seed_navigation_checkpoint"), encrypted=True
                            ),
                            row["seed_navigation_checkpoint_digest"],
                            row["branch_id"],
                            int(row["lineage_version"]),
                            row["parent_frame_id"],
                            row["owner_id"],
                            _json_dumps_or_none(row.get("workspace_state"), encrypted=True),
                            row["operator_phase"],
                            _json_dumps_or_none(row.get("operator_events"), encrypted=True),
                            _json_dumps_or_none(row.get("operator_audit"), encrypted=True),
                            1 if row["operator_ambient"] else 0,
                            1 if row["operator_checkpoint_active"] else 0,
                        ),
                    )

    def _open_sqlite(self) -> sqlite3.Connection:
        assert self._store_path is not None
        conn = sqlite3.connect(str(self._store_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=FULL;")
        return conn

    def _ensure_sqlite_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS engine_store_meta(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS engine_sessions(
                session_id TEXT PRIMARY KEY,
                family TEXT NOT NULL,
                created_at TEXT NOT NULL,
                steps INTEGER NOT NULL,
                manifest_path TEXT,
                emit_packet INTEGER NOT NULL,
                governance_costs_json TEXT,
                governance_calibration_json TEXT,
                governance_policy_version TEXT NOT NULL DEFAULT 'gov-v1.0.0',
                evidence_policy_version TEXT NOT NULL DEFAULT 'evidence-v1',
                manifest_digest TEXT,
                replay_contract_version TEXT,
                seed_frame_json TEXT,
                actions_json TEXT NOT NULL,
                packets_json TEXT NOT NULL DEFAULT '[]',
                packet_artifacts_digest TEXT,
                seed_navigation_checkpoint_json TEXT,
                seed_navigation_checkpoint_digest TEXT,
                branch_id TEXT,
                lineage_version INTEGER NOT NULL DEFAULT 1,
                parent_frame_id TEXT,
                owner_id TEXT,
                workspace_state_json TEXT,
                operator_phase TEXT NOT NULL DEFAULT 'frame_draft',
                operator_events_json TEXT,
                operator_audit_json TEXT,
                operator_ambient INTEGER NOT NULL DEFAULT 0,
                operator_checkpoint_active INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(engine_sessions)").fetchall()}
        if "branch_id" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN branch_id TEXT")
        if "lineage_version" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN lineage_version INTEGER NOT NULL DEFAULT 1")
        if "parent_frame_id" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN parent_frame_id TEXT")
        if "owner_id" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN owner_id TEXT")
        if "workspace_state_json" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN workspace_state_json TEXT")
        if "operator_phase" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN operator_phase TEXT NOT NULL DEFAULT 'frame_draft'")
        if "operator_events_json" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN operator_events_json TEXT")
        if "operator_audit_json" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN operator_audit_json TEXT")
        if "operator_ambient" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN operator_ambient INTEGER NOT NULL DEFAULT 0")
        if "governance_policy_version" not in columns:
            conn.execute(
                "ALTER TABLE engine_sessions ADD COLUMN governance_policy_version "
                "TEXT NOT NULL DEFAULT 'gov-v1.0.0'"
            )
        if "evidence_policy_version" not in columns:
            conn.execute(
                "ALTER TABLE engine_sessions ADD COLUMN evidence_policy_version "
                "TEXT NOT NULL DEFAULT 'evidence-v1'"
            )
        if "manifest_digest" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN manifest_digest TEXT")
        if "replay_contract_version" not in columns:
            conn.execute("ALTER TABLE engine_sessions ADD COLUMN replay_contract_version TEXT")
        if "packets_json" not in columns:
            conn.execute(
                "ALTER TABLE engine_sessions ADD COLUMN packets_json "
                "TEXT NOT NULL DEFAULT '[]'"
            )
        if "packet_artifacts_digest" not in columns:
            conn.execute(
                "ALTER TABLE engine_sessions ADD COLUMN packet_artifacts_digest TEXT"
            )
        if "seed_navigation_checkpoint_json" not in columns:
            conn.execute(
                "ALTER TABLE engine_sessions ADD COLUMN seed_navigation_checkpoint_json TEXT"
            )
        if "seed_navigation_checkpoint_digest" not in columns:
            conn.execute(
                "ALTER TABLE engine_sessions ADD COLUMN seed_navigation_checkpoint_digest TEXT"
            )
        if "operator_checkpoint_active" not in columns:
            conn.execute(
                "ALTER TABLE engine_sessions ADD COLUMN operator_checkpoint_active "
                "INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            """
            INSERT INTO engine_store_meta(key, value)
            VALUES('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (str(_SQLITE_SCHEMA_VERSION),),
        )

    def _recover_corrupt_store(self, exc: Exception) -> None:
        assert self._store_path is not None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        corrupt_path = self._store_path.with_suffix(f"{self._store_path.suffix}.corrupt.{stamp}")
        LOGGER.warning("recovering_corrupt_store path=%s error=%s", self._store_path, exc)
        try:
            self._store_path.rename(corrupt_path)
        except OSError:
            LOGGER.exception("failed_to_move_corrupt_store path=%s", self._store_path)

    def _serialize_session(self, session: EngineSession) -> Dict[str, Any]:
        return {
            "session_id": session.session_id,
            "family": session.family,
            "created_at": session.created_at,
            "steps": session.steps,
            "manifest_path": session.manifest_path,
            "emit_packet": session.emit_packet,
            "governance_costs": _serialize_governance_costs(session.governance_costs),
            "governance_calibration": _serialize_governance_calibration(session.governance_calibration),
            "governance_policy_version": session.governance_policy_version,
            "evidence_policy_version": session.evidence_policy_version,
            "manifest_digest": session.manifest_digest,
            "replay_contract_version": session.replay_contract_version,
            "seed_frame": _json_copy(session.seed_frame_payload),
            "actions": _json_copy(session.actions) or [],
            "packets": _json_copy(session.packets) or [],
            "packet_artifacts_digest": _packet_artifacts_digest(
                session.packets
            ),
            "seed_navigation_checkpoint": _json_copy(
                session.seed_navigation_checkpoint
            ),
            "seed_navigation_checkpoint_digest": (
                _navigation_checkpoint_digest(session.seed_navigation_checkpoint)
                if session.seed_navigation_checkpoint is not None
                else None
            ),
            "branch_id": session.branch_id,
            "lineage_version": int(session.lineage_version),
            "parent_frame_id": session.parent_frame_id,
            "owner_id": session.owner_id,
            "workspace_state": _json_copy(session.workspace_state) or {},
            "operator_phase": session.operator_phase,
            "operator_events": _json_copy(session.operator_events) or [],
            "operator_audit": _json_copy(session.operator_audit) or {},
            "operator_ambient": bool(session.operator_ambient),
            "operator_checkpoint_active": bool(
                session.operator_checkpoint_active
            ),
        }


def _trace_payload(entry: Any) -> Dict[str, Any]:
    decision = entry.governor_decision
    evaln = entry.manifold_evaluation
    payload = {
        "manifold": evaln.manifold_id,
        "family": evaln.family,
        "channel": evaln.channel_semantics.to_dict(),
        "decision": decision.decision,
        "cause": decision.cause,
        "tension": decision.metrics.tension,
        "velocity": decision.metrics.velocity,
        "accel": decision.metrics.accel,
        "posterior": entry.posterior,
        "ruin_hits": evaln.ruin_hits,
        "active_transforms": evaln.active_transforms,
        "is_ruin": evaln.is_ruin,
        "violation_count": len(evaln.result.violations),
        "red_veto_active": bool(entry.trace_metadata.get("red_veto_active", False)),
        "direct_ruin_criterion_active": bool(
            entry.trace_metadata.get("direct_ruin_criterion_active", False)
        ),
        "stage": entry.trace_metadata.get("stage"),
        "stage_events": entry.trace_metadata.get("stage_events", []),
        "frame_id": entry.trace_metadata.get("frame_id"),
        "frame_version": entry.trace_metadata.get("frame_version"),
    }

    if entry.governance_decision is not None and entry.governance_metrics is not None:
        g = entry.governance_decision
        gm = entry.governance_metrics
        payload["governance"] = {
            "posture": g.posture,
            "warning_level": g.warning_level,
            "recommended_action": g.recommended_action,
            "red_veto_active": g.red_veto_active,
            "ruin_boundary_met": "RUIN_MASS_HIGH" in g.trigger_codes,
            "direct_ruin_criterion_active": "DIRECT_RUIN_CRITERION_ACTIVE"
            in g.trigger_codes,
            "cost_gate_crossed": "COST_GATE_CROSSED" in g.trigger_codes,
            "trigger_codes": list(g.trigger_codes),
            "theta": g.theta,
            "loss_treat": g.loss_treat,
            "loss_notreat": g.loss_notreat,
            "p_bad": gm.p_bad,
            "ruin_mass": gm.ruin_mass,
            "contradiction_density": gm.contradiction_density,
            "posterior_entropy_norm": gm.posterior_entropy_norm,
            "top_margin": gm.top_margin,
            "top_p": gm.top_p,
            "user_decision": entry.trace_metadata.get("user_decision"),
            "override_reason": entry.trace_metadata.get("override_reason"),
        }
        why = entry.trace_metadata.get("why_not_converging") or []
        if why:
            payload["governance"]["why_not_converging"] = why

    return payload


def _build_sign(family: Family, payload: Dict[str, Any]) -> Any:
    if family == "puzzle":
        if "letters" not in payload or "candidate" not in payload:
            raise ValueError("Puzzle sign requires 'letters' and 'candidate'.")
        return WordPuzzleSign(letters=str(payload["letters"]), candidate=str(payload["candidate"]))

    if family == "clinical":
        if "radicular_pain" not in payload or "spasm_present" not in payload:
            raise ValueError("Clinical sign requires 'radicular_pain' and 'spasm_present'.")
        return ClinicalSign(
            radicular_pain=_coerce_bool(payload["radicular_pain"], field="radicular_pain"),
            spasm_present=_coerce_bool(payload["spasm_present"], field="spasm_present"),
            saddle_anesthesia=_coerce_optional_bool(
                payload.get("saddle_anesthesia"),
                field="saddle_anesthesia",
            ),
            bladder_dysfunction=_coerce_optional_bool(
                payload.get("bladder_dysfunction"),
                field="bladder_dysfunction",
            ),
            bilateral_weakness=_coerce_optional_bool(
                payload.get("bilateral_weakness"),
                field="bilateral_weakness",
            ),
            progression=_coerce_bool(payload.get("progression", False), field="progression"),
            fever=_coerce_bool(payload.get("fever", False), field="fever"),
            notes=payload.get("notes"),
            followup=payload.get("followup"),
            evidence_id=_normalize_evidence_id(payload.get("evidence_id")),
            independent_observation=_coerce_bool(
                payload.get("independent_observation", False),
                field="independent_observation",
            ),
        )

    if family == "safety":
        if "critical_signal" not in payload:
            raise ValueError("Safety sign requires 'critical_signal'.")
        return SafetySign(
            critical_signal=_coerce_bool(payload["critical_signal"], field="critical_signal"),
            policy_violation=_coerce_bool(payload.get("policy_violation", False), field="policy_violation"),
            notes=payload.get("notes"),
            evidence_id=_normalize_evidence_id(payload.get("evidence_id")),
            independent_observation=_coerce_bool(
                payload.get("independent_observation", False),
                field="independent_observation",
            ),
        )

    raise ValueError(f"Unsupported family: {family}")


def _parse_governance_costs(payload: Optional[Dict[str, float]]) -> Optional[GovernanceCosts]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Governance costs must be an object with c_fp and c_fn.")
    if "c_fp" not in payload or "c_fn" not in payload:
        raise ValueError("Governance costs must include c_fp and c_fn.")
    return GovernanceCosts(c_fp=float(payload["c_fp"]), c_fn=float(payload["c_fn"]))


def _normalize_owner_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("owner_id must be a string when provided.")
    normalized = value.strip().lower()
    if not normalized:
        return None
    if len(normalized) > 256:
        raise ValueError("owner_id must be 256 characters or fewer.")
    return normalized


def _parse_governance_calibration(payload: Optional[Dict[str, Any]]) -> Optional[GovernanceCalibration]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Governance calibration must be an object.")
    version = str(payload.get("version", DEFAULT_CALIBRATION_VERSION))
    _validate_calibration_version(version)
    if version == "logit-v1":
        ambiguity_default = 1.0
        contradiction_default = 0.8
        entropy_default = 0.4
        margin_collapse_default = 0.6
    else:
        ambiguity_default = 0.0
        contradiction_default = 0.0
        entropy_default = 0.0
        margin_collapse_default = 0.0
    calibration = GovernanceCalibration(
        prior_pi=float(payload.get("prior_pi", 0.1)),
        intercept=float(payload.get("intercept", 0.0)),
        slope=float(payload.get("slope", 1.0)),
        w_violation_pressure=float(payload.get("w_violation_pressure", 1.4)),
        w_ambiguity_pressure=float(payload.get("w_ambiguity_pressure", ambiguity_default)),
        w_contradiction_density=float(
            payload.get("w_contradiction_density", contradiction_default)
        ),
        w_entropy=float(payload.get("w_entropy", entropy_default)),
        w_margin_collapse=float(payload.get("w_margin_collapse", margin_collapse_default)),
        version=version,
    )
    return calibration


def _serialize_governance_costs(costs: Optional[GovernanceCosts]) -> Optional[Dict[str, float]]:
    if costs is None:
        return None
    return {
        "c_fp": float(costs.c_fp),
        "c_fn": float(costs.c_fn),
    }


def _serialize_governance_calibration(
    calibration: Optional[GovernanceCalibration],
) -> Optional[Dict[str, Any]]:
    if calibration is None:
        return None
    return {
        "prior_pi": float(calibration.prior_pi),
        "intercept": float(calibration.intercept),
        "slope": float(calibration.slope),
        "w_violation_pressure": float(calibration.w_violation_pressure),
        "w_ambiguity_pressure": float(calibration.w_ambiguity_pressure),
        "w_contradiction_density": float(calibration.w_contradiction_density),
        "w_entropy": float(calibration.w_entropy),
        "w_margin_collapse": float(calibration.w_margin_collapse),
        "version": calibration.version,
    }


def _coerce_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value in {0, 1}:
            return bool(value)
        raise ValueError(f"{field} must be a boolean (true/false).")
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
        raise ValueError(f"{field} must be a boolean (true/false).")
    raise ValueError(f"{field} must be a boolean (true/false).")


def _coerce_optional_bool(value: Any, *, field: str) -> Optional[bool]:
    if value is None:
        return None
    return _coerce_bool(value, field=field)


def _normalize_evidence_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("evidence_id must be a string when provided.")
    normalized = value.strip()
    if not normalized:
        raise ValueError("evidence_id must be non-empty when provided.")
    if len(normalized) > 256:
        raise ValueError("evidence_id must be 256 characters or fewer.")
    return normalized


def _frame_from_payload(payload: Optional[Dict[str, Any]], costs: Optional[GovernanceCosts]) -> Optional[FrameVersion]:
    if payload is None:
        return None
    text = payload.get("text")
    if not text:
        raise ValueError("Frame payload requires non-empty 'text'.")
    payload_costs = payload.get("costs")
    if not isinstance(payload_costs, dict):
        payload_costs = {}

    def frame_cost(name: str, fallback: Optional[float] = None) -> Optional[float]:
        raw = payload.get(name, payload_costs.get(name))
        return float(raw) if raw is not None else fallback

    return FrameVersion(
        frame_id=str(payload.get("frame_id") or uuid4()),
        frame_version=int(payload.get("frame_version") or 1),
        text=str(text),
        objective_type=payload.get("objective_type", "sensemake"),
        domain=payload.get("domain"),
        time_horizon=payload.get("time_horizon"),
        rationale_for_change=payload.get("rationale_for_change"),
        constraints_hard=tuple(payload.get("constraints_hard", []) or []),
        constraints_soft=tuple(payload.get("constraints_soft", []) or []),
        c_fp=frame_cost("c_fp", costs.c_fp if costs else None),
        c_fn=frame_cost("c_fn", costs.c_fn if costs else None),
        c_delay=frame_cost("c_delay"),
    )


def _validated_iteration_packet_meta(packet: Dict[str, Any]) -> Dict[str, Any]:
    if packet.get("schema_id") != "nepsis.iteration_packet":
        raise ValueError("Expected an iteration packet artifact.")
    meta = packet.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("Stored iteration packet requires meta.")
    packet_id = meta.get("packet_id")
    if not isinstance(packet_id, str) or not packet_id.strip():
        raise ValueError("Stored iteration packet requires a non-empty packet_id.")
    iteration = meta.get("iteration")
    if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
        raise ValueError("Stored iteration packet requires a non-negative iteration.")
    parent_packet_id = meta.get("parent_packet_id")
    if parent_packet_id is not None and (
        not isinstance(parent_packet_id, str) or not parent_packet_id.strip()
    ):
        raise ValueError(
            "Stored iteration packet parent_packet_id must be null or non-empty."
        )
    return {
        "packet_id": packet_id,
        "parent_packet_id": parent_packet_id,
        "iteration": iteration,
    }


def _iteration_packets_from_artifacts(
    packets: list[Dict[str, Any]],
    *,
    require_rooted_chain: bool = True,
) -> list[Dict[str, Any]]:
    iteration_packets = [
        packet
        for packet in packets
        if packet.get("schema_id") == "nepsis.iteration_packet"
    ]
    seen_ids: set[str] = set()
    previous_meta: Optional[Dict[str, Any]] = None
    for packet in iteration_packets:
        meta = _validated_iteration_packet_meta(packet)
        if meta["packet_id"] in seen_ids:
            raise ValueError("Stored iteration packet IDs must be unique.")
        seen_ids.add(meta["packet_id"])
        if previous_meta is None:
            if require_rooted_chain and (
                meta["parent_packet_id"] is not None or meta["iteration"] != 0
            ):
                raise ValueError("Stored iteration packet lineage is not rooted.")
        elif (
            meta["parent_packet_id"] != previous_meta["packet_id"]
            or meta["iteration"] != previous_meta["iteration"] + 1
        ):
            raise ValueError("Stored iteration packet lineage is discontinuous.")
        previous_meta = meta
    return iteration_packets


def _normalized_replay_packet(packet: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _json_copy(packet)
    if not isinstance(normalized, dict):
        raise ValueError("Replay packet must be an object.")
    meta = normalized.get("meta")
    if not isinstance(meta, dict):
        raise ValueError("Replay iteration packet requires meta.")
    for dynamic_key in ("packet_id", "created_at", "parent_packet_id"):
        meta.pop(dynamic_key, None)
    return normalized


def _validate_replayed_packet_artifacts(
    *,
    stored_packets: list[Dict[str, Any]],
    generated_packets: list[Dict[str, Any]],
    emit_packet: bool,
    allow_prior_history: bool,
) -> list[Dict[str, Any]]:
    stored_iterations = _iteration_packets_from_artifacts(stored_packets)
    if any(
        packet.get("schema_id") != "nepsis.iteration_packet"
        for packet in generated_packets
    ):
        raise ValueError("Semantic replay emitted an unsupported packet artifact.")
    generated_iterations = _iteration_packets_from_artifacts(
        generated_packets,
        require_rooted_chain=False,
    )
    if not emit_packet:
        if generated_iterations or stored_iterations:
            raise ValueError(
                "Iteration packet artifacts are incompatible with emit_packet=false."
            )
        return []
    if len(stored_iterations) < len(generated_iterations):
        raise ValueError(
            "Stored packet artifacts are incomplete for semantic replay."
        )
    if not allow_prior_history and len(stored_iterations) != len(
        generated_iterations
    ):
        raise ValueError(
            "Stored packet artifacts contain history outside semantic replay."
        )
    current_segment = (
        stored_iterations[-len(generated_iterations) :]
        if generated_iterations
        else []
    )
    for stored, generated in zip(current_segment, generated_iterations):
        if _normalized_replay_packet(stored) != _normalized_replay_packet(
            generated
        ):
            raise ValueError(
                "Stored packet artifact diverges from semantic replay."
            )
    return current_segment


def _frame_ref(frame: Optional[FrameVersion]) -> Optional[str]:
    if frame is None:
        return None
    return f"{frame.frame_id}:v{frame.frame_version}"


def _frame_lineage_version(frame: Optional[FrameVersion]) -> int:
    if frame is None:
        return 0
    return max(1, int(frame.frame_version))


def _initial_branch_id(session_id: str) -> str:
    prefix = session_id[:6] or "session"
    return f"{prefix}-b1"


def _normalize_branch_id(value: Any, *, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _optional_parent_frame_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return str(value)


def _coerce_lineage_version(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(1, parsed)


_FRAME_COACH_PROMPTS: dict[str, str] = {
    "problem_statement": "What exact decision or question are we trying to resolve?",
    "catastrophic_outcome": "What catastrophic outcome defines the red-channel boundary space?",
    "optimization_goal": "What should the blue-channel utility space optimize once red boundaries are controlled?",
    "decision_horizon": "What decision horizon are we operating on right now?",
    "key_uncertainty": "What uncertainty could most change the decision?",
    "constraint_structure": "List at least one hard constraint and one soft constraint.",
}

_INTERPRETATION_COACH_PROMPTS: dict[str, str] = {
    "report_text": "What observations, signals, or evidence do we have so far?",
    "hypothesis_count": "What competing interpretations are still live?",
    "evidence_count": "What evidence supports or contradicts each interpretation?",
    "case_reasoning_compiler": "Run the Case Reasoning Compiler before locking the report.",
    "evaluation_freshness": "Evidence changed after the last run. Re-run CALL + REPORT now.",
    "contradictions_declared": "Declare contradiction status explicitly, or mark none identified.",
    "contradiction_density": "Contradictions are high. Add disambiguating evidence before locking.",
}

_THRESHOLD_COACH_PROMPTS: dict[str, str] = {
    "case_reasoning_compiler": "Thresholding requires a valid Case Reasoning Compiler packet tied to this frame.",
    "posterior_available": "Posterior is missing. Run interpretation to generate hypotheses first.",
    "loss_asymmetry": "Define loss asymmetry (false positive vs false negative cost).",
    "red_override_metadata": "Missing protective-action metadata. Re-run interpretation to refresh governance values.",
    "decision_declared": "Declare threshold decision: recommend action or hold.",
    "hold_reason": "If holding, explain what clarification or evidence is required.",
    "red_override_enforced": "A RED veto is active. Recommendation stays blocked until governed release or narrowing evidence is recorded.",
    "cost_review_disposition": "Acknowledge the cost-derived review and record a rationale before recommending.",
}


def _legal_next_tools(phase: str) -> list[str]:
    return list(_OPERATOR_LEGAL_NEXT_TOOLS.get(phase, _OPERATOR_LEGAL_NEXT_TOOLS[_OPERATOR_PHASE_INITIAL]))


def _normalize_operator_phase(value: Any) -> str:
    if isinstance(value, str) and value in _OPERATOR_LEGAL_NEXT_TOOLS:
        return value
    return _OPERATOR_PHASE_INITIAL


def _normalize_operator_events(value: Any) -> list[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    events: list[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("event"), str):
            events.append(_json_copy(item))
        elif isinstance(item, str) and item.strip():
            events.append({"event": item.strip(), "at": None})
    return events


def _normalize_operator_audit(value: Any) -> Dict[str, Any]:
    return _json_copy(value) if isinstance(value, dict) else {}


def _append_operator_event(
    session: EngineSession,
    event: str,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    entry = {"event": event, "at": _now_iso8601()}
    if extra:
        entry.update(_json_copy(extra) or {})
    session.operator_events.append(entry)


def _operator_event_log_with(session: EngineSession, event: str) -> list[Dict[str, Any]]:
    event_log = _json_copy(session.operator_events) or []
    event_log.append({"event": event, "at": _now_iso8601()})
    return event_log


def _operator_stage_context(session: EngineSession) -> Dict[str, Dict[str, Any]]:
    context = _stored_stage_audit_context(session.workspace_state)
    normalized = _normalize_stage_audit_context(context) if context is not None else {}
    if "frame" not in normalized:
        normalized["frame"] = _build_frame_stage_packet(session, None)
    return normalized


def _attach_case_reasoning(
    session: EngineSession,
    interpretation_context: Dict[str, Any],
    *,
    report_text: str,
) -> None:
    frame = session.navigation.frame
    frame_id = frame.frame_id if frame else ""
    source_text = _string_or_default(
        interpretation_context,
        keys=("case_reasoning_source_text", "caseReasoningSourceText", "source_text", "sourceText"),
        default=frame.text if frame and frame.text else report_text,
    )
    input_hash = _string_or_default(
        interpretation_context,
        keys=("input_prompt_hash", "inputPromptHash", "prompt_hash", "promptHash"),
        default=case_reasoning_prompt_hash(source_text),
    )
    raw_case_id = _context_value(interpretation_context, "case_id", "caseId")
    case_id = _as_string(raw_case_id) or "custom"
    raw = _context_value(interpretation_context, "case_reasoning", "caseReasoning", "case_reasoning_compiler")

    if isinstance(raw, dict):
        compiler = _json_copy(raw) or {}
        validation = validate_case_reasoning(
            compiler,
            source_text=source_text,
            frame_id=frame_id,
            input_prompt_hash=input_hash,
        )
        mark_case_reasoning_validation(compiler, validation)
    else:
        compiler = compile_case_reasoning(
            source_text,
            case_id=case_id,
            frame_id=frame_id,
            input_prompt_hash=input_hash,
        )
        validation = {
            "status": "PASS" if compiler.get("compiler_valid") is True else "BLOCK",
            "errors": _json_copy(compiler.get("validation_errors")) or [],
            "warnings": _json_copy(compiler.get("validation_warnings")) or [],
        }

    interpretation_context["case_reasoning_source_text"] = source_text
    interpretation_context["input_frame_id"] = frame_id
    interpretation_context["input_prompt_hash"] = input_hash
    interpretation_context["case_reasoning"] = compiler
    interpretation_context["case_reasoning_validation"] = validation


def _operator_phase_event_names(event_log: list[Dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for item in event_log:
        event = item.get("event") if isinstance(item, dict) else None
        if isinstance(event, str) and event:
            names.append(event)
    return names


def _merged_frame_payload(
    session: EngineSession,
    carry_forward_frame: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    frame = session.navigation.frame.to_dict() if session.navigation.frame else _json_copy(_DEFAULT_OPERATOR_FRAME)
    merged = _json_copy(frame) or {}
    if carry_forward_frame is not None:
        if not isinstance(carry_forward_frame, dict):
            raise ValueError("carry_forward_frame must be an object when provided.")
        for key, value in carry_forward_frame.items():
            if value is not None:
                merged[key] = _json_copy(value)
    return merged


def _build_operator_audit_packet(
    session: EngineSession,
    *,
    audit: Dict[str, Any],
    phase_event_log: list[Dict[str, Any]],
    final_frame: Dict[str, Any],
) -> Dict[str, Any]:
    threshold_packet = _json_copy(audit["threshold"]["packet"])
    latest_packet = _latest_iteration_packet(session)
    return {
        "schema_id": "nepsis.operator_audit_packet",
        "schema_version": "1.0.0",
        "session_id": session.session_id,
        "created_at": _now_iso8601(),
        "phase_events": _operator_phase_event_names(phase_event_log),
        "phase_event_log": phase_event_log,
        "frame": {
            "status": audit["frame"]["status"],
            "packet": _json_copy(audit["frame"]["packet"]),
            "missing": _json_copy(audit["frame"]["missing"]),
            "warnings": _json_copy(audit["frame"]["warnings"]),
        },
        "report": {
            "status": audit["interpretation"]["status"],
            "packet": _json_copy(audit["interpretation"]["packet"]),
            "missing": _json_copy(audit["interpretation"]["missing"]),
            "warnings": _json_copy(audit["interpretation"]["warnings"]),
        },
        "threshold": threshold_packet,
        "red_override": {
            "active": threshold_packet.get("red_veto_active") is True,
            "warning_level": threshold_packet.get("warning_level"),
            "recommendation": threshold_packet.get("recommendation"),
        },
        "protective_action_review": {
            "active": threshold_packet.get("gate_crossed") is True,
            "cost_review_required": threshold_packet.get("cost_review_required")
            is True,
            "cost_review_acknowledged": threshold_packet.get(
                "cost_review_acknowledged"
            )
            is True,
            "cost_review_rationale": threshold_packet.get(
                "cost_review_rationale"
            ),
        },
        "latest_iteration_packet_id": _packet_meta_value(latest_packet, "packet_id"),
        "latest_iteration": _packet_meta_value(latest_packet, "iteration"),
        "final_frame": _json_copy(final_frame),
        "policy": dict(_STAGE_AUDIT_POLICY),
    }


def _build_operator_abandoned_packet(session: EngineSession, *, reason: str) -> Dict[str, Any]:
    return {
        "schema_id": "nepsis.operator_abandoned_loop",
        "schema_version": "1.0.0",
        "session_id": session.session_id,
        "created_at": _now_iso8601(),
        "phase": session.operator_phase,
        "reason": str(reason or ""),
        "phase_events": _operator_phase_event_names(session.operator_events),
        "phase_event_log": _json_copy(session.operator_events) or [],
        "committed": False,
    }


def _normalize_stage_audit_context(context: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if context is None:
        return {}
    if not isinstance(context, dict):
        raise ValueError("stage-audit context must be an object when provided.")

    normalized: Dict[str, Dict[str, Any]] = {}
    for stage in ("frame", "interpretation", "threshold"):
        section = context.get(stage)
        if section is None:
            continue
        if not isinstance(section, dict):
            raise ValueError(f"stage-audit context '{stage}' must be an object.")
        normalized[stage] = section
    return normalized


def _normalize_workspace_state(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("workspace_state must be an object.")
    normalized = _json_copy(value)
    raw = json.dumps(normalized, sort_keys=True)
    if len(raw.encode("utf-8")) > _WORKSPACE_STATE_MAX_BYTES:
        raise ValueError("workspace_state is too large.")
    return normalized


def _merge_workspace_state(existing: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
    merged = _json_copy(existing) or {}
    merged.update(_json_copy(update) or {})
    return _normalize_workspace_state(merged)


def _stored_stage_audit_context(workspace_state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    context = workspace_state.get("stage_audit_context") if isinstance(workspace_state, dict) else None
    return context if isinstance(context, dict) else None


def _latest_iteration_packet(session: EngineSession) -> Optional[Dict[str, Any]]:
    for candidate in reversed(session.packets):
        if not isinstance(candidate, dict):
            continue
        if candidate.get("schema_id") == "nepsis.iteration_packet":
            return candidate
        meta = candidate.get("meta")
        if isinstance(meta, dict) and meta.get("packet_id"):
            return candidate
    return None


def _packet_meta_value(packet: Optional[Dict[str, Any]], key: str) -> Any:
    if not isinstance(packet, dict):
        return None
    meta = packet.get("meta")
    if not isinstance(meta, dict):
        return None
    return meta.get(key)


def _context_value(section: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in section:
            return section[key]
    return None


def _as_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _string_or_default(section: Dict[str, Any], *, keys: tuple[str, ...], default: str) -> str:
    raw = _context_value(section, *keys)
    if raw is None:
        return default.strip()
    return _as_string(raw)


def _string_list_or_default(section: Dict[str, Any], *, keys: tuple[str, ...], default: list[str]) -> list[str]:
    raw = _context_value(section, *keys)
    if raw is None:
        return list(default)
    if not isinstance(raw, list):
        return list(default)
    values: list[str] = []
    for item in raw:
        text = _as_string(item)
        if text:
            values.append(text)
    return values


def _line_count(value: str) -> int:
    return len([line for line in value.splitlines() if line.strip()])


def _to_optional_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "on"}:
            return True
        if lowered in {"false", "0", "no", "n", "off"}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    return None


def _to_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _text_present(value: str) -> bool:
    return bool(value and value.strip())


def _rationale_segment(rationale: Optional[str], label: str) -> str:
    if not rationale:
        return ""
    match = re.search(rf"{re.escape(label)}:\s*([^|]+)", rationale, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).strip()


def _build_frame_stage_packet(session: EngineSession, context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    frame = session.navigation.frame
    section = context or {}
    rationale = frame.rationale_for_change if frame else None
    hard_default = list(frame.constraints_hard) if frame else []
    soft_default = list(frame.constraints_soft) if frame else []

    return {
        "frame_id": frame.frame_id if frame else "",
        "frame_version": frame.frame_version if frame else None,
        "problem_statement": _string_or_default(section, keys=("problem_statement", "problemStatement"), default=frame.text if frame else ""),
        "catastrophic_outcome": _string_or_default(
            section,
            keys=("catastrophic_outcome", "catastrophicOutcome"),
            default=_rationale_segment(rationale, "Red channel"),
        ),
        "optimization_goal": _string_or_default(
            section,
            keys=("optimization_goal", "optimizationGoal"),
            default=_rationale_segment(rationale, "Blue channel"),
        ),
        "decision_horizon": _string_or_default(
            section,
            keys=("decision_horizon", "decisionHorizon"),
            default=frame.time_horizon if frame and frame.time_horizon else "",
        ),
        "key_uncertainty": _string_or_default(
            section,
            keys=("key_uncertainty", "keyUncertainty"),
            default=_rationale_segment(rationale, "Uncertainty"),
        ),
        "hard_constraints": _string_list_or_default(
            section,
            keys=("hard_constraints", "hardConstraints"),
            default=hard_default,
        ),
        "soft_constraints": _string_list_or_default(
            section,
            keys=("soft_constraints", "softConstraints"),
            default=soft_default,
        ),
    }


def _build_interpretation_stage_packet(
    context: Optional[Dict[str, Any]],
    latest_packet: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    section = context or {}
    report_text = _string_or_default(section, keys=("report_text", "reportText"), default="")

    posterior = latest_packet.get("posterior") if isinstance(latest_packet, dict) else None
    hypothesis_count = len(posterior) if isinstance(posterior, dict) else 0

    governance = latest_packet.get("governance") if isinstance(latest_packet, dict) else None
    metrics = governance.get("metrics") if isinstance(governance, dict) else None
    contradiction_density = _to_optional_float(_context_value(section, "contradiction_density", "contradictionDensity"))
    if contradiction_density is None and isinstance(metrics, dict):
        contradiction_density = _to_optional_float(metrics.get("contradiction_density"))

    evidence_count = _to_optional_int(_context_value(section, "evidence_count", "evidenceCount"))
    if evidence_count is None:
        evidence_count = _line_count(report_text)
    if evidence_count < 0:
        evidence_count = 0

    report_synced = _to_optional_bool(_context_value(section, "report_synced", "reportSynced"))
    if report_synced is None:
        report_synced = False

    contradictions_status = _string_or_default(
        section,
        keys=("contradictions_status", "contradictionsStatus"),
        default="unreviewed",
    )
    if contradictions_status not in {"unreviewed", "none_identified", "declared"}:
        contradictions_status = "unreviewed"

    return {
        "report_text": report_text,
        "hypothesis_count": hypothesis_count,
        "evidence_count": evidence_count,
        "report_synced": report_synced,
        "contradictions_status": contradictions_status,
        "contradictions_note": _string_or_default(
            section,
            keys=("contradictions_note", "contradictionsNote"),
            default="",
        ),
        "contradiction_density": contradiction_density,
        "input_frame_id": _string_or_default(section, keys=("input_frame_id", "inputFrameId"), default=""),
        "input_prompt_hash": _string_or_default(section, keys=("input_prompt_hash", "inputPromptHash", "prompt_hash", "promptHash"), default=""),
        "case_reasoning": _json_copy(_context_value(section, "case_reasoning", "caseReasoning", "case_reasoning_compiler")),
        "case_reasoning_validation": _json_copy(_context_value(section, "case_reasoning_validation", "caseReasoningValidation")) or {},
    }


def _build_threshold_stage_packet(
    context: Optional[Dict[str, Any]],
    latest_packet: Optional[Dict[str, Any]],
    *,
    interpretation_context: Optional[Dict[str, Any]] = None,
    frame_packet: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    section = context or {}
    interpretation_section = interpretation_context or {}
    case_reasoning = _json_copy(
        _context_value(interpretation_section, "case_reasoning", "caseReasoning", "case_reasoning_compiler")
    )
    case_reasoning_validation = _json_copy(
        _context_value(interpretation_section, "case_reasoning_validation", "caseReasoningValidation")
    ) or {}
    compiler_threshold = threshold_fields_from_case_reasoning(
        case_reasoning if isinstance(case_reasoning, dict) else None
    )

    posterior = latest_packet.get("posterior") if isinstance(latest_packet, dict) else None
    hypothesis_count = len(posterior) if isinstance(posterior, dict) else 0

    governance = latest_packet.get("governance") if isinstance(latest_packet, dict) else None
    metrics = governance.get("metrics") if isinstance(governance, dict) else None
    still = latest_packet.get("still") if isinstance(latest_packet, dict) else None
    finalization_blockers = (
        still.get("finalization_blockers") if isinstance(still, dict) else None
    )

    loss_treat = _to_optional_float(_context_value(section, "loss_treat", "lossTreat"))
    if loss_treat is None and isinstance(governance, dict):
        loss_treat = _to_optional_float(governance.get("loss_treat"))
    loss_not_treat = _to_optional_float(_context_value(section, "loss_not_treat", "lossNotTreat"))
    if loss_not_treat is None and isinstance(governance, dict):
        loss_not_treat = _to_optional_float(governance.get("loss_notreat"))

    warning_level = _string_or_default(
        section,
        keys=("warning_level", "warningLevel"),
        default=str(compiler_threshold.get("warning_level") or ""),
    )
    if not warning_level and isinstance(governance, dict):
        warning_level = _as_string(governance.get("warning_level"))

    gate_signals: list[bool] = []
    red_veto_signals: list[bool] = []
    cost_review_signals: list[bool] = []
    requested_gate = _to_optional_bool(_context_value(section, "gate_crossed", "gateCrossed"))
    if requested_gate is not None:
        gate_signals.append(requested_gate)
    if "gate_crossed" in compiler_threshold:
        compiler_gate = _to_optional_bool(compiler_threshold.get("gate_crossed"))
        if compiler_gate is not None:
            gate_signals.append(compiler_gate)
    if isinstance(governance, dict):
        runtime_veto = _to_optional_bool(governance.get("red_veto_active"))
        if runtime_veto is not None:
            gate_signals.append(runtime_veto)
            red_veto_signals.append(runtime_veto)
        trigger_codes = governance.get("trigger_codes")
        if isinstance(trigger_codes, list):
            direct_or_ruin = any(
                code
                in {
                    "DIRECT_RUIN_CRITERION_ACTIVE",
                    "RUIN_MASS_HIGH",
                }
                for code in trigger_codes
            )
            cost_review = "COST_GATE_CROSSED" in trigger_codes
            red_veto_signals.append(direct_or_ruin)
            cost_review_signals.append(cost_review)
            gate_signals.extend((direct_or_ruin, cost_review))
    if not cost_review_signals and isinstance(governance, dict) and isinstance(metrics, dict):
        p_bad = _to_optional_float(metrics.get("p_bad"))
        theta = _to_optional_float(governance.get("theta"))
        if p_bad is not None and theta is not None:
            cost_review = threshold_crossed(p_bad, theta)
            cost_review_signals.append(cost_review)
            gate_signals.append(cost_review)
    if isinstance(finalization_blockers, list):
        authoritative_red_blockers = {
            "direct_ruin_criterion_active",
            "red_veto_active",
            "red_capture_review_required",
        }
        runtime_still_veto = any(
            isinstance(blocker, str)
            and blocker in authoritative_red_blockers
            for blocker in finalization_blockers
        )
        gate_signals.append(runtime_still_veto)
        red_veto_signals.append(runtime_still_veto)
    gate_crossed = any(gate_signals) if gate_signals else None
    red_veto_active = any(red_veto_signals) if red_veto_signals else False
    cost_review_required = (
        any(cost_review_signals) if cost_review_signals else False
    )

    recommendation = _string_or_default(
        section,
        keys=("recommendation",),
        default=str(compiler_threshold.get("recommendation") or ""),
    )
    if not recommendation and isinstance(governance, dict):
        recommendation = _as_string(governance.get("recommended_action"))

    decision = _string_or_default(section, keys=("decision",), default="undecided")
    if decision not in {"undecided", "recommend", "hold"}:
        decision = "undecided"

    return {
        "hypothesis_count": hypothesis_count,
        "loss_treat": loss_treat,
        "loss_not_treat": loss_not_treat,
        "warning_level": warning_level or None,
        "gate_crossed": gate_crossed,
        "red_veto_active": red_veto_active,
        "cost_review_required": cost_review_required,
        "cost_review_acknowledged": bool(
            _to_optional_bool(
                _context_value(
                    section,
                    "cost_review_acknowledged",
                    "costReviewAcknowledged",
                )
            )
        ),
        "cost_review_rationale": _string_or_default(
            section,
            keys=("cost_review_rationale", "costReviewRationale"),
            default="",
        ),
        "recommendation": recommendation or None,
        "recommended_threshold_action": _string_or_default(
            section,
            keys=("recommended_threshold_action", "recommendedThresholdAction"),
            default=str(compiler_threshold.get("recommended_threshold_action") or ""),
        )
        or None,
        "decision": decision,
        "hold_reason": _string_or_default(section, keys=("hold_reason", "holdReason"), default=""),
        "closure_basis": _string_or_default(
            section,
            keys=("closure_basis", "closureBasis"),
            default=str(compiler_threshold.get("closure_basis") or ""),
        ),
        "case_reasoning": case_reasoning if isinstance(case_reasoning, dict) else None,
        "case_reasoning_validation": case_reasoning_validation,
        "expected_frame_id": _string_or_default(frame_packet or {}, keys=("frame_id", "frameId"), default=""),
        "expected_prompt_hash": _string_or_default(
            interpretation_section,
            keys=("input_prompt_hash", "inputPromptHash", "prompt_hash", "promptHash"),
            default="",
        ),
    }


def _evaluate_frame_checks(packet: Dict[str, Any]) -> list[Dict[str, Any]]:
    total_constraints = len(packet["hard_constraints"]) + len(packet["soft_constraints"])
    return [
        {
            "key": "problem_statement",
            "label": "Problem statement",
            "status": "pass" if _text_present(packet["problem_statement"]) else "block",
            "detail": "Defined."
            if _text_present(packet["problem_statement"])
            else "Fill Question with one sentence: 'Should we ... given ...?'",
        },
        {
            "key": "catastrophic_outcome",
            "label": "Catastrophic outcome",
            "status": "pass" if _text_present(packet["catastrophic_outcome"]) else "block",
            "detail": "Red-channel risk defined."
            if _text_present(packet["catastrophic_outcome"])
            else "Fill Red boundary with the bad outcome the system must prevent.",
        },
        {
            "key": "optimization_goal",
            "label": "Optimization goal",
            "status": "pass" if _text_present(packet["optimization_goal"]) else "block",
            "detail": "Blue-channel objective defined."
            if _text_present(packet["optimization_goal"])
            else "Fill Blue goal with what success should optimize after red risk is controlled.",
        },
        {
            "key": "decision_horizon",
            "label": "Decision horizon",
            "status": "pass" if _text_present(packet["decision_horizon"]) else "block",
            "detail": "Time horizon declared."
            if _text_present(packet["decision_horizon"])
            else "Select the decision horizon for this pass.",
        },
        {
            "key": "key_uncertainty",
            "label": "Key uncertainty",
            "status": "pass" if _text_present(packet["key_uncertainty"]) else "block",
            "detail": "Uncertainty source declared."
            if _text_present(packet["key_uncertainty"])
            else "Fill Key uncertainty with the fact that could most change the decision.",
        },
        {
            "key": "constraint_structure",
            "label": "Constraint structure",
            "status": "pass" if total_constraints > 0 else "block",
            "detail": f"{total_constraints} constraints captured."
            if total_constraints > 0
            else "Add at least one line under Hard constraints or Soft constraints.",
        },
    ]


def _evaluate_interpretation_checks(packet: Dict[str, Any]) -> list[Dict[str, Any]]:
    contradiction_declared = packet["contradictions_status"] == "none_identified" or (
        packet["contradictions_status"] == "declared" and _text_present(packet["contradictions_note"])
    )
    contradiction_density = _to_optional_float(packet["contradiction_density"])
    high_contradiction_density = contradiction_density is not None and contradiction_density >= 0.35
    case_reasoning_validation = packet.get("case_reasoning_validation")
    case_reasoning_status = (
        str(case_reasoning_validation.get("status"))
        if isinstance(case_reasoning_validation, dict) and case_reasoning_validation.get("status")
        else "BLOCK"
    )

    return [
        {
            "key": "report_text",
            "label": "Evidence narrative",
            "status": "pass" if _text_present(packet["report_text"]) else "block",
            "detail": "Evidence text captured."
            if _text_present(packet["report_text"])
            else "Add at least one evidence sentence in Report notes.",
        },
        {
            "key": "hypothesis_count",
            "label": "Candidate hypotheses",
            "status": "pass" if packet["hypothesis_count"] > 0 else "block",
            "detail": f"{packet['hypothesis_count']} candidate interpretations generated."
            if packet["hypothesis_count"] > 0
            else "Click Run CALL + REPORT to generate candidate interpretations.",
        },
        {
            "key": "evidence_count",
            "label": "Evidence linkage",
            "status": "pass" if packet["evidence_count"] > 0 else "block",
            "detail": f"{packet['evidence_count']} evidence lines captured."
            if packet["evidence_count"] > 0
            else "Add each observation as its own evidence line before running the report.",
        },
        {
            "key": "case_reasoning_compiler",
            "label": "Case Reasoning Compiler",
            "status": "pass" if case_reasoning_status == "PASS" else "warn" if case_reasoning_status == "WARN" else "block",
            "detail": "Case reasoning compiler valid."
            if case_reasoning_status == "PASS"
            else "Case reasoning compiler has warnings."
            if case_reasoning_status == "WARN"
            else "Case reasoning compiler is missing or invalid.",
        },
        {
            "key": "evaluation_freshness",
            "label": "Evaluation freshness",
            "status": "pass" if packet["report_synced"] else "block",
            "detail": "Current evidence has been evaluated."
            if packet["report_synced"]
            else "Click Run CALL + REPORT again because the evidence text changed.",
        },
        {
            "key": "contradictions_declared",
            "label": "Contradiction declaration",
            "status": "pass" if contradiction_declared else "block",
            "detail": "Contradiction status declared."
            if contradiction_declared
            else "Set contradiction status to none identified, or choose declared and add a contradiction note.",
        },
        {
            "key": "contradiction_density",
            "label": "Contradiction density",
            "status": "warn" if high_contradiction_density else "pass",
            "detail": "High contradiction density. Add disambiguating evidence or state what conflicts."
            if high_contradiction_density
            else "Contradiction density within expected range.",
        },
    ]


def _evaluate_threshold_checks(packet: Dict[str, Any]) -> list[Dict[str, Any]]:
    case_reasoning = packet.get("case_reasoning")
    case_reasoning_validation = packet.get("case_reasoning_validation")
    compiler_valid = (
        isinstance(case_reasoning, dict)
        and case_reasoning.get("compiler_valid") is True
        and isinstance(case_reasoning_validation, dict)
        and case_reasoning_validation.get("status") in {"PASS", "WARN"}
        and case_reasoning.get("input_frame_id") == packet.get("expected_frame_id")
        and case_reasoning.get("input_prompt_hash") == packet.get("expected_prompt_hash")
    )
    loss_asymmetry_defined = packet["loss_treat"] is not None and packet["loss_not_treat"] is not None
    red_gate_metadata_ready = packet["warning_level"] is not None and packet["gate_crossed"] is not None
    decision_declared = packet["decision"] != "undecided"
    hold_reason_ready = packet["decision"] != "hold" or _text_present(packet["hold_reason"])
    red_override_violation = (
        packet.get("red_veto_active") is True
        and packet["decision"] == "recommend"
    )
    cost_review_ready = (
        packet.get("cost_review_required") is not True
        or packet["decision"] != "recommend"
        or (
            packet.get("cost_review_acknowledged") is True
            and _text_present(packet.get("cost_review_rationale"))
        )
    )
    unclassified_gate_violation = (
        packet["gate_crossed"] is True
        and packet.get("red_veto_active") is not True
        and packet.get("cost_review_required") is not True
        and packet["decision"] == "recommend"
    )

    return [
        {
            "key": "case_reasoning_compiler",
            "label": "Case Reasoning Compiler",
            "status": "pass" if compiler_valid else "block",
            "detail": "Validated compiler packet is tied to this frame and prompt."
            if compiler_valid
            else "Thresholding requires a valid compiler packet tied to this frame and prompt.",
        },
        {
            "key": "posterior_available",
            "label": "Posterior available",
            "status": "pass" if packet["hypothesis_count"] > 0 else "block",
            "detail": f"{packet['hypothesis_count']} posterior hypotheses available."
            if packet["hypothesis_count"] > 0
            else "Posterior missing. Run CALL + REPORT first.",
        },
        {
            "key": "loss_asymmetry",
            "label": "Loss asymmetry defined",
            "status": "pass" if loss_asymmetry_defined else "block",
            "detail": "Threshold costs are defined."
            if loss_asymmetry_defined
            else "Lock a frame with a risk posture so false-positive and false-negative costs exist.",
        },
        {
            "key": "red_override_metadata",
            "label": "Protective-action gate",
            "status": "pass" if red_gate_metadata_ready else "block",
            "detail": "Gate metadata available."
            if red_gate_metadata_ready
            else "Run CALL + REPORT so warning level and p_bad vs theta are available.",
        },
        {
            "key": "decision_declared",
            "label": "Decision declaration",
            "status": "pass" if decision_declared else "block",
            "detail": f"Decision marked as {packet['decision']}."
            if decision_declared
            else "Choose recommend action or hold for clarification.",
        },
        {
            "key": "hold_reason",
            "label": "Hold rationale",
            "status": "pass" if hold_reason_ready else "block",
            "detail": "Hold rationale complete."
            if hold_reason_ready
            else "Add a Hold rationale sentence naming the missing discriminator.",
        },
        {
            "key": "red_override_enforced",
            "label": "RED veto enforcement",
            "status": "block"
            if red_override_violation or unclassified_gate_violation
            else "pass",
            "detail": "RED veto active. Choose hold or reframe; recommendation cannot proceed while the protected criterion remains active."
            if red_override_violation
            else "Unclassified protective-action gate requires hold or re-evaluation."
            if unclassified_gate_violation
            else "RED veto discipline satisfied.",
        },
        {
            "key": "cost_review_disposition",
            "label": "Cost-review disposition",
            "status": "pass" if cost_review_ready else "block",
            "detail": "Cost-derived review was explicitly dispositioned."
            if packet.get("cost_review_required") is True and cost_review_ready
            else "Acknowledge the cost-derived review and provide a rationale before recommending."
            if not cost_review_ready
            else "No cost-derived review requires disposition.",
        },
    ]


def _gate_status(checks: list[Dict[str, Any]]) -> str:
    if any(check.get("status") == "block" for check in checks):
        return "BLOCK"
    if any(check.get("status") == "warn" for check in checks):
        return "WARN"
    return "PASS"


def _coach_summary(status: str, stage_name: str) -> str:
    if status == "PASS":
        return f"{stage_name} contract satisfied. You can lock and continue."
    if status == "WARN":
        return f"{stage_name} contract is passable with warnings. Resolve warnings if you need higher confidence."
    return f"{stage_name} contract blocked. Fill required constraints before progression."


def _top_pending_checks(checks: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    ranked = [check for check in checks if check.get("status") != "pass"]
    ranked.sort(
        key=lambda check: (
            0 if check.get("status") == "block" else 1,
            str(check.get("label", "")),
        )
    )
    return ranked[:3]


def _build_stage_gate(
    *,
    checks: list[Dict[str, Any]],
    packet: Dict[str, Any],
    stage_name: str,
    prompt_map: Dict[str, str],
) -> Dict[str, Any]:
    status = _gate_status(checks)
    missing = [check["label"] for check in checks if check.get("status") == "block"]
    warnings = [check["label"] for check in checks if check.get("status") == "warn"]
    prompts: list[str] = []
    for check in _top_pending_checks(checks):
        key = str(check.get("key", ""))
        prompt = prompt_map.get(key) or str(check.get("detail", "")).strip()
        if prompt and prompt not in prompts:
            prompts.append(prompt)
    return {
        "status": status,
        "checks": checks,
        "missing": missing,
        "warnings": warnings,
        "packet": packet,
        "coach": {
            "status": status,
            "summary": _coach_summary(status, stage_name),
            "prompts": prompts,
        },
    }


def _now_iso8601() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _parse_iso8601(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_copy(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(json.dumps(value))


def _navigation_checkpoint_digest(checkpoint: Dict[str, Any]) -> str:
    canonical = json.dumps(
        checkpoint,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _packet_artifacts_digest(packets: list[Dict[str, Any]]) -> str:
    canonical = json.dumps(
        packets,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolve_store_path(store_path: Optional[str]) -> Optional[Path]:
    configured = store_path if store_path is not None else os.getenv("NEPSIS_API_STORE_PATH")
    if configured is None:
        return None
    if not configured.strip():
        return None
    return Path(configured).expanduser().resolve()


def _is_sqlite_store_path(path: Path) -> bool:
    return path.suffix.lower() in {".db", ".sqlite", ".sqlite3"}


def _json_loads_or_none(value: Optional[str], *, encrypted: bool = False) -> Any:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if encrypted:
        text = _open_text(text)
    return json.loads(text)


def _json_dumps_or_none(value: Any, *, encrypted: bool = False) -> Optional[str]:
    if value is None:
        return None
    raw = json.dumps(value, sort_keys=True)
    return _seal_text(raw) if encrypted else raw


def _max_page_size() -> int:
    raw = os.getenv("NEPSIS_API_MAX_PAGE_SIZE", "200")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("NEPSIS_API_MAX_PAGE_SIZE must be an integer") from exc
    return max(value, 1)


def _normalize_pagination(*, limit: int, offset: int) -> tuple[int, int]:
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if limit <= 0:
        raise ValueError("limit must be > 0")
    return min(limit, _max_page_size()), offset


def _allowed_calibration_versions() -> set[str]:
    raw = os.getenv(
        "NEPSIS_API_ALLOWED_CALIBRATION_VERSIONS",
        "logit-v1,logit-v2",
    )
    return {item.strip() for item in raw.split(",") if item.strip()}


def _validate_calibration_version(version: str) -> None:
    allowed = _allowed_calibration_versions()
    if version not in allowed:
        raise ValueError(
            f"Unsupported calibration version '{version}'. "
            f"Allowed: {', '.join(sorted(allowed))}"
        )


def _configured_retention_seconds() -> Optional[float]:
    raw = os.getenv("NEPSIS_API_RETENTION_SECONDS")
    if raw is None or not raw.strip():
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("NEPSIS_API_RETENTION_SECONDS must be a number") from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_RETENTION_SECONDS must be > 0")
    return value


def _encryption_key_bytes() -> Optional[bytes]:
    raw = os.getenv("NEPSIS_API_DATA_KEY")
    if raw is None or not raw.strip():
        return None
    try:
        key = base64.urlsafe_b64decode(raw.strip().encode("utf-8"))
    except Exception as exc:
        raise ValueError("NEPSIS_API_DATA_KEY must be urlsafe-base64 encoded bytes") from exc
    if len(key) not in {16, 24, 32}:
        raise ValueError("NEPSIS_API_DATA_KEY decoded length must be 16, 24, or 32 bytes")
    return key


def _seal_text(raw: str) -> str:
    key = _encryption_key_bytes()
    if key is None:
        return raw
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover
        raise ValueError(
            "NEPSIS_API_DATA_KEY is set but cryptography is not installed. "
            "Install optional dependency 'cryptography'."
        ) from exc

    nonce = os.urandom(12)
    aes = AESGCM(key)
    ciphertext = aes.encrypt(nonce, raw.encode("utf-8"), None)
    return "enc:v1:" + base64.urlsafe_b64encode(nonce).decode("utf-8") + ":" + base64.urlsafe_b64encode(ciphertext).decode(
        "utf-8"
    )


def _open_text(value: str) -> str:
    text = value.strip()
    if not text.startswith("enc:v1:"):
        return text
    key = _encryption_key_bytes()
    if key is None:
        raise _StoreDecryptionError("Encrypted store detected but NEPSIS_API_DATA_KEY is not configured.")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover
        raise _StoreDecryptionError("Encrypted store detected but cryptography is not installed.") from exc

    parts = text.split(":", maxsplit=3)
    if len(parts) != 4:
        raise _StoreDecryptionError("Invalid encrypted payload format.")
    try:
        nonce = base64.urlsafe_b64decode(parts[2].encode("utf-8"))
        ciphertext = base64.urlsafe_b64decode(parts[3].encode("utf-8"))
        raw = AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise _StoreDecryptionError("Failed to decrypt stored payload.") from exc
    return raw.decode("utf-8")


__all__ = [
    "EngineApiService",
]
