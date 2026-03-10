from __future__ import annotations

import json
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

from ..core import FrameVersion, GovernanceCalibration, GovernanceCosts, NavigationController
from ..core.interpretant import WordPuzzleSign
from ..core.runtime import build_navigation_controller
from ..manifolds.clinical import ClinicalSign
from ..manifolds.red_blue import SafetySign

Family = Literal["puzzle", "clinical", "safety"]
_STORE_SCHEMA_ID = "nepsis.engine_api_sessions"
_STORE_SCHEMA_VERSION = "1.1.0"
_SQLITE_SCHEMA_VERSION = 2
_STAGE_AUDIT_POLICY = {
    "name": "nepsis_cgn.stage_audit",
    "version": "2026-03-10",
}
LOGGER = logging.getLogger("nepsis_cgn.api.service")


class _StoreDecryptionError(ValueError):
    pass


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
    actions: list[Dict[str, Any]] = field(default_factory=list)
    branch_id: str = ""
    lineage_version: int = 1
    parent_frame_id: Optional[str] = None


class EngineApiService:
    def __init__(self, *, store_path: Optional[str] = None) -> None:
        self._sessions: Dict[str, EngineSession] = {}
        self._lock = RLock()
        self._store_path = _resolve_store_path(store_path)
        self._load_sessions()
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
    ) -> Dict[str, Any]:
        with self._lock:
            session_id = str(uuid4())
            costs = _parse_governance_costs(governance_costs)
            calibration = _parse_governance_calibration(governance_calibration)
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
            )
            created_at = _now_iso8601()
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
                branch_id=_initial_branch_id(session_id),
                lineage_version=max(1, _frame_lineage_version(nav.frame)),
                parent_frame_id=None,
            )
            self._persist_sessions()
            return self.get_session(session_id)

    def list_sessions(self, *, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        with self._lock:
            page_limit, page_offset = _normalize_pagination(limit=limit, offset=offset)
            summaries = [self._session_summary(s) for s in self._sessions.values()]
            paged = summaries[page_offset : page_offset + page_limit]
            return {
                "sessions": paged,
                "pagination": {
                    "limit": page_limit,
                    "offset": page_offset,
                    "total": len(summaries),
                },
            }

    def get_session(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            return self._session_summary(session)

    def reframe_session(
        self,
        session_id: str,
        *,
        frame: Dict[str, Any],
        branch_id: Optional[str] = None,
        parent_frame_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
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
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            return self._step_session_internal(
                session,
                sign=sign,
                commit=commit,
                user_decision=user_decision,
                override_reason=override_reason,
                carry_forward=carry_forward,
                record_action=True,
                persist=True,
            )

    def get_packets(self, session_id: str, *, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
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

    def stage_audit_session(
        self,
        session_id: str,
        *,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            normalized_context = _normalize_stage_audit_context(context)
            latest_packet = _latest_iteration_packet(session)

            frame_packet = _build_frame_stage_packet(session, normalized_context.get("frame"))
            interpretation_packet = _build_interpretation_stage_packet(
                normalized_context.get("interpretation"),
                latest_packet,
            )
            threshold_packet = _build_threshold_stage_packet(
                normalized_context.get("threshold"),
                latest_packet,
            )

            frame_checks = _evaluate_frame_checks(frame_packet)
            interpretation_checks = _evaluate_interpretation_checks(interpretation_packet)
            threshold_checks = _evaluate_threshold_checks(threshold_packet)

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
                "interpretation": _build_stage_gate(
                    checks=interpretation_checks,
                    packet=interpretation_packet,
                    stage_name="Interpretation",
                    prompt_map=_INTERPRETATION_COACH_PROMPTS,
                ),
                "threshold": _build_stage_gate(
                    checks=threshold_checks,
                    packet=threshold_packet,
                    stage_name="Threshold",
                    prompt_map=_THRESHOLD_COACH_PROMPTS,
                ),
                "source": {
                    "packet_count": len(session.packets),
                    "latest_packet_id": _packet_meta_value(latest_packet, "packet_id"),
                    "latest_iteration": _packet_meta_value(latest_packet, "iteration"),
                    "context_applied": bool(normalized_context),
                },
            }

    def delete_session(self, session_id: str) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
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
    ) -> Dict[str, Any]:
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be > 0.")

        with self._lock:
            now = datetime.now(timezone.utc)
            cutoff = now.timestamp() - float(max_age_seconds)
            to_delete: list[str] = []

            for sid, session in self._sessions.items():
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
    ) -> Dict[str, Any]:
        nav = session.navigation
        typed_sign = _build_sign(session.family, sign)
        entry = nav.step(
            typed_sign,
            commit=commit,
            user_decision=user_decision,
            override_reason=override_reason,
            carry_forward_policy=carry_forward,
        )
        session.steps += 1

        payload = _trace_payload(entry)
        if entry.iteration_packet is not None:
            # API session_id is canonical for all externally exposed packets.
            entry.iteration_packet["meta"]["session_id"] = session.session_id
            session.packets.append(entry.iteration_packet)
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
            "storage": "disk" if self._store_path is not None else "memory",
            "manifest_path": session.manifest_path,
            "governance": _serialize_governance_costs(session.governance_costs),
            "calibration": _serialize_governance_calibration(session.governance_calibration),
        }

    def _require_session(self, session_id: str) -> EngineSession:
        if session_id not in self._sessions:
            raise KeyError(f"Unknown session_id: {session_id}")
        return self._sessions[session_id]

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
                           governance_costs_json, governance_calibration_json, seed_frame_json, actions_json,
                           branch_id, lineage_version, parent_frame_id
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
                "seed_frame": _json_loads_or_none(row[8], encrypted=True),
                "actions": _json_loads_or_none(row[9], encrypted=True) or [],
                "branch_id": row[10],
                "lineage_version": row[11],
                "parent_frame_id": row[12],
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
        emit_packet = bool(payload.get("emit_packet", True))
        costs = _parse_governance_costs(payload.get("governance_costs"))
        calibration = _parse_governance_calibration(payload.get("governance_calibration"))

        seed_frame_payload = _json_copy(payload.get("seed_frame"))
        seed_frame = _frame_from_payload(seed_frame_payload, costs)
        nav = build_navigation_controller(
            manifest_path=manifest_path,
            families=[family],
            governance_costs=costs,
            governance_calibration=calibration,
            emit_iteration_packet=emit_packet,
            session_id=session_id,
            frame=seed_frame,
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
            branch_id=_initial_branch_id(session_id),
            lineage_version=max(1, _frame_lineage_version(nav.frame)),
            parent_frame_id=None,
        )

        actions = payload.get("actions")
        if isinstance(actions, list):
            for action in actions:
                if not isinstance(action, dict):
                    continue
                kind = action.get("kind")
                if kind == "step":
                    self._step_session_internal(
                        session,
                        sign=_json_copy(action.get("sign")) or {},
                        commit=bool(action.get("commit", False)),
                        user_decision=action.get("user_decision"),
                        override_reason=action.get("override_reason"),
                        carry_forward=_json_copy(action.get("carry_forward")),
                        record_action=True,
                        persist=False,
                    )
                elif kind == "reframe":
                    frame = _json_copy(action.get("frame"))
                    if isinstance(frame, dict):
                        self._reframe_session_internal(
                            session,
                            frame=frame,
                            branch_id=action.get("branch_id"),
                            parent_frame_id=action.get("parent_frame_id"),
                            record_action=True,
                            persist=False,
                        )

        stored_steps = int(payload.get("steps") or 0)
        if stored_steps > session.steps:
            session.steps = stored_steps
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
                            governance_costs_json, governance_calibration_json, seed_frame_json, actions_json,
                            branch_id, lineage_version, parent_frame_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            _json_dumps_or_none(row.get("seed_frame"), encrypted=True),
                            _json_dumps_or_none(row.get("actions"), encrypted=True),
                            row["branch_id"],
                            int(row["lineage_version"]),
                            row["parent_frame_id"],
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
                seed_frame_json TEXT,
                actions_json TEXT NOT NULL,
                branch_id TEXT,
                lineage_version INTEGER NOT NULL DEFAULT 1,
                parent_frame_id TEXT
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
            "seed_frame": _json_copy(session.seed_frame_payload),
            "actions": _json_copy(session.actions) or [],
            "branch_id": session.branch_id,
            "lineage_version": int(session.lineage_version),
            "parent_frame_id": session.parent_frame_id,
        }


def _trace_payload(entry: Any) -> Dict[str, Any]:
    decision = entry.governor_decision
    evaln = entry.manifold_evaluation
    payload = {
        "manifold": evaln.manifold_id,
        "family": evaln.family,
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
            saddle_anesthesia=_coerce_bool(payload.get("saddle_anesthesia", False), field="saddle_anesthesia"),
            bladder_dysfunction=_coerce_bool(payload.get("bladder_dysfunction", False), field="bladder_dysfunction"),
            bilateral_weakness=_coerce_bool(payload.get("bilateral_weakness", False), field="bilateral_weakness"),
            progression=_coerce_bool(payload.get("progression", False), field="progression"),
            fever=_coerce_bool(payload.get("fever", False), field="fever"),
            notes=payload.get("notes"),
            followup=payload.get("followup"),
        )

    if family == "safety":
        if "critical_signal" not in payload:
            raise ValueError("Safety sign requires 'critical_signal'.")
        return SafetySign(
            critical_signal=_coerce_bool(payload["critical_signal"], field="critical_signal"),
            policy_violation=_coerce_bool(payload.get("policy_violation", False), field="policy_violation"),
            notes=payload.get("notes"),
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


def _parse_governance_calibration(payload: Optional[Dict[str, Any]]) -> Optional[GovernanceCalibration]:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError("Governance calibration must be an object.")
    calibration = GovernanceCalibration(
        prior_pi=float(payload.get("prior_pi", 0.1)),
        intercept=float(payload.get("intercept", 0.0)),
        slope=float(payload.get("slope", 1.0)),
        w_violation_pressure=float(payload.get("w_violation_pressure", 1.4)),
        w_ambiguity_pressure=float(payload.get("w_ambiguity_pressure", 1.0)),
        w_contradiction_density=float(payload.get("w_contradiction_density", 0.8)),
        w_entropy=float(payload.get("w_entropy", 0.4)),
        w_margin_collapse=float(payload.get("w_margin_collapse", 0.6)),
        version=str(payload.get("version", "logit-v1")),
    )
    _validate_calibration_version(calibration.version)
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


def _frame_from_payload(payload: Optional[Dict[str, Any]], costs: Optional[GovernanceCosts]) -> Optional[FrameVersion]:
    if payload is None:
        return None
    text = payload.get("text")
    if not text:
        raise ValueError("Frame payload requires non-empty 'text'.")
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
        c_fp=float(payload.get("c_fp")) if payload.get("c_fp") is not None else (costs.c_fp if costs else None),
        c_fn=float(payload.get("c_fn")) if payload.get("c_fn") is not None else (costs.c_fn if costs else None),
        c_delay=float(payload.get("c_delay")) if payload.get("c_delay") is not None else None,
    )


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
    "catastrophic_outcome": "What catastrophic outcome must never be allowed?",
    "optimization_goal": "What should we optimize for when red-channel risks are controlled?",
    "decision_horizon": "What decision horizon are we operating on right now?",
    "key_uncertainty": "What uncertainty could most change the decision?",
    "constraint_structure": "List at least one hard constraint and one soft constraint.",
}

_INTERPRETATION_COACH_PROMPTS: dict[str, str] = {
    "report_text": "What observations, signals, or evidence do we have so far?",
    "hypothesis_count": "What competing interpretations are still live?",
    "evidence_count": "What evidence supports or contradicts each interpretation?",
    "evaluation_freshness": "Evidence changed after the last run. Re-run CALL + REPORT now.",
    "contradictions_declared": "Declare contradiction status explicitly, or mark none identified.",
    "contradiction_density": "Contradictions are high. Add disambiguating evidence before locking.",
}

_THRESHOLD_COACH_PROMPTS: dict[str, str] = {
    "posterior_available": "Posterior is missing. Run interpretation to generate hypotheses first.",
    "loss_asymmetry": "Define loss asymmetry (false positive vs false negative cost).",
    "red_override_metadata": "Missing red-gate metadata. Re-run interpretation to refresh governance values.",
    "decision_declared": "Declare threshold decision: recommend action or hold.",
    "hold_reason": "If holding, explain what clarification or evidence is required.",
    "red_override_enforced": "Red gate is crossed. Recommendation is blocked; hold and gather more evidence.",
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


def _latest_iteration_packet(session: EngineSession) -> Optional[Dict[str, Any]]:
    if not session.packets:
        return None
    candidate = session.packets[-1]
    return candidate if isinstance(candidate, dict) else None


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
    }


def _build_threshold_stage_packet(
    context: Optional[Dict[str, Any]],
    latest_packet: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    section = context or {}

    posterior = latest_packet.get("posterior") if isinstance(latest_packet, dict) else None
    hypothesis_count = len(posterior) if isinstance(posterior, dict) else 0

    governance = latest_packet.get("governance") if isinstance(latest_packet, dict) else None
    metrics = governance.get("metrics") if isinstance(governance, dict) else None

    loss_treat = _to_optional_float(_context_value(section, "loss_treat", "lossTreat"))
    if loss_treat is None and isinstance(governance, dict):
        loss_treat = _to_optional_float(governance.get("loss_treat"))
    loss_not_treat = _to_optional_float(_context_value(section, "loss_not_treat", "lossNotTreat"))
    if loss_not_treat is None and isinstance(governance, dict):
        loss_not_treat = _to_optional_float(governance.get("loss_notreat"))

    warning_level = _string_or_default(section, keys=("warning_level", "warningLevel"), default="")
    if not warning_level and isinstance(governance, dict):
        warning_level = _as_string(governance.get("warning_level"))

    gate_crossed = _to_optional_bool(_context_value(section, "gate_crossed", "gateCrossed"))
    if gate_crossed is None and isinstance(governance, dict) and isinstance(metrics, dict):
        p_bad = _to_optional_float(metrics.get("p_bad"))
        theta = _to_optional_float(governance.get("theta"))
        if p_bad is not None and theta is not None:
            gate_crossed = p_bad >= theta

    recommendation = _string_or_default(section, keys=("recommendation",), default="")
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
        "recommendation": recommendation or None,
        "decision": decision,
        "hold_reason": _string_or_default(section, keys=("hold_reason", "holdReason"), default=""),
    }


def _evaluate_frame_checks(packet: Dict[str, Any]) -> list[Dict[str, Any]]:
    total_constraints = len(packet["hard_constraints"]) + len(packet["soft_constraints"])
    return [
        {
            "key": "problem_statement",
            "label": "Problem statement",
            "status": "pass" if _text_present(packet["problem_statement"]) else "block",
            "detail": "Defined." if _text_present(packet["problem_statement"]) else "Required before frame lock.",
        },
        {
            "key": "catastrophic_outcome",
            "label": "Catastrophic outcome",
            "status": "pass" if _text_present(packet["catastrophic_outcome"]) else "block",
            "detail": "Red-channel risk defined."
            if _text_present(packet["catastrophic_outcome"])
            else "Define what must not happen.",
        },
        {
            "key": "optimization_goal",
            "label": "Optimization goal",
            "status": "pass" if _text_present(packet["optimization_goal"]) else "block",
            "detail": "Blue-channel objective defined."
            if _text_present(packet["optimization_goal"])
            else "Define what success should optimize for.",
        },
        {
            "key": "decision_horizon",
            "label": "Decision horizon",
            "status": "pass" if _text_present(packet["decision_horizon"]) else "block",
            "detail": "Time horizon declared."
            if _text_present(packet["decision_horizon"])
            else "Set the operating horizon.",
        },
        {
            "key": "key_uncertainty",
            "label": "Key uncertainty",
            "status": "pass" if _text_present(packet["key_uncertainty"]) else "block",
            "detail": "Uncertainty source declared."
            if _text_present(packet["key_uncertainty"])
            else "Declare the dominant uncertainty source.",
        },
        {
            "key": "constraint_structure",
            "label": "Constraint structure",
            "status": "pass" if total_constraints > 0 else "block",
            "detail": f"{total_constraints} constraints captured."
            if total_constraints > 0
            else "Add at least one hard/soft constraint.",
        },
    ]


def _evaluate_interpretation_checks(packet: Dict[str, Any]) -> list[Dict[str, Any]]:
    contradiction_declared = packet["contradictions_status"] == "none_identified" or (
        packet["contradictions_status"] == "declared" and _text_present(packet["contradictions_note"])
    )
    contradiction_density = _to_optional_float(packet["contradiction_density"])
    high_contradiction_density = contradiction_density is not None and contradiction_density >= 0.35

    return [
        {
            "key": "report_text",
            "label": "Evidence narrative",
            "status": "pass" if _text_present(packet["report_text"]) else "block",
            "detail": "Evidence text captured."
            if _text_present(packet["report_text"])
            else "Add observations before evaluation.",
        },
        {
            "key": "hypothesis_count",
            "label": "Candidate hypotheses",
            "status": "pass" if packet["hypothesis_count"] > 0 else "block",
            "detail": f"{packet['hypothesis_count']} candidate interpretations generated."
            if packet["hypothesis_count"] > 0
            else "Run evaluation to generate at least one interpretation.",
        },
        {
            "key": "evidence_count",
            "label": "Evidence linkage",
            "status": "pass" if packet["evidence_count"] > 0 else "block",
            "detail": f"{packet['evidence_count']} evidence lines captured."
            if packet["evidence_count"] > 0
            else "Link at least one evidence item to proceed.",
        },
        {
            "key": "evaluation_freshness",
            "label": "Evaluation freshness",
            "status": "pass" if packet["report_synced"] else "block",
            "detail": "Current evidence has been evaluated."
            if packet["report_synced"]
            else "Evidence changed since last evaluation. Run CALL + REPORT again.",
        },
        {
            "key": "contradictions_declared",
            "label": "Contradiction declaration",
            "status": "pass" if contradiction_declared else "block",
            "detail": "Contradiction status declared."
            if contradiction_declared
            else "Set contradiction status or add contradiction notes.",
        },
        {
            "key": "contradiction_density",
            "label": "Contradiction density",
            "status": "warn" if high_contradiction_density else "pass",
            "detail": "High contradiction density. Consider gathering more evidence."
            if high_contradiction_density
            else "Contradiction density within expected range.",
        },
    ]


def _evaluate_threshold_checks(packet: Dict[str, Any]) -> list[Dict[str, Any]]:
    loss_asymmetry_defined = packet["loss_treat"] is not None and packet["loss_not_treat"] is not None
    red_gate_metadata_ready = packet["warning_level"] is not None and packet["gate_crossed"] is not None
    decision_declared = packet["decision"] != "undecided"
    hold_reason_ready = packet["decision"] != "hold" or _text_present(packet["hold_reason"])
    red_override_violation = packet["gate_crossed"] is True and packet["decision"] == "recommend"

    return [
        {
            "key": "posterior_available",
            "label": "Posterior available",
            "status": "pass" if packet["hypothesis_count"] > 0 else "block",
            "detail": f"{packet['hypothesis_count']} posterior hypotheses available."
            if packet["hypothesis_count"] > 0
            else "Posterior missing. Run interpretation first.",
        },
        {
            "key": "loss_asymmetry",
            "label": "Loss asymmetry defined",
            "status": "pass" if loss_asymmetry_defined else "block",
            "detail": "Threshold costs are defined."
            if loss_asymmetry_defined
            else "Loss asymmetry is required for threshold gating.",
        },
        {
            "key": "red_override_metadata",
            "label": "Red override check",
            "status": "pass" if red_gate_metadata_ready else "block",
            "detail": "Gate metadata available."
            if red_gate_metadata_ready
            else "Missing red-gate metadata (warning level / p_bad vs theta).",
        },
        {
            "key": "decision_declared",
            "label": "Decision declaration",
            "status": "pass" if decision_declared else "block",
            "detail": f"Decision marked as {packet['decision']}."
            if decision_declared
            else "Choose recommend or hold.",
        },
        {
            "key": "hold_reason",
            "label": "Hold rationale",
            "status": "pass" if hold_reason_ready else "block",
            "detail": "Hold rationale complete."
            if hold_reason_ready
            else "Provide hold rationale before continuing.",
        },
        {
            "key": "red_override_enforced",
            "label": "Red override enforcement",
            "status": "block" if red_override_violation else "pass",
            "detail": "Red gate crossed. Recommendation is blocked until decision is hold."
            if red_override_violation
            else "Red override discipline satisfied.",
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
    raw = os.getenv("NEPSIS_API_ALLOWED_CALIBRATION_VERSIONS", "logit-v1")
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
