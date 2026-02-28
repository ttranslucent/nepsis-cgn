from __future__ import annotations

import json
import logging
import os
import sqlite3
import base64
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
_STORE_SCHEMA_VERSION = "1.0.0"
_SQLITE_SCHEMA_VERSION = 1
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

    def reframe_session(self, session_id: str, *, frame: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            session = self._require_session(session_id)
            response = self._reframe_session_internal(
                session,
                frame=frame,
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
        record_action: bool,
        persist: bool,
    ) -> Dict[str, Any]:
        nav = session.navigation
        updated = nav.reframe(
            text=frame.get("text"),
            objective_type=frame.get("objective_type"),
            domain=frame.get("domain"),
            time_horizon=frame.get("time_horizon"),
            rationale_for_change=frame.get("rationale_for_change"),
            constraints_hard=frame.get("constraints_hard"),
            constraints_soft=frame.get("constraints_soft"),
        )
        if record_action:
            session.actions.append(
                {
                    "kind": "reframe",
                    "frame": _json_copy(frame),
                }
            )
        if persist:
            self._persist_sessions()
        return {
            "session_id": session.session_id,
            "frame": updated.to_dict(),
            "stage": nav.current_stage,
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
                           governance_costs_json, governance_calibration_json, seed_frame_json, actions_json
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
                            record_action=True,
                            persist=False,
                        )

        stored_steps = int(payload.get("steps") or 0)
        if stored_steps > session.steps:
            session.steps = stored_steps
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
                            governance_costs_json, governance_calibration_json, seed_frame_json, actions_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                actions_json TEXT NOT NULL
            )
            """
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
            "seed_frame": _json_copy(session.seed_frame_payload),
            "actions": _json_copy(session.actions) or [],
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
