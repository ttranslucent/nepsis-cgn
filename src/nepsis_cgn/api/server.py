from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import sys
import time
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from ..core.mvp import PUBLIC_MVP_CASE_IDS, build_nepsis_mvp_packet
from ..core.runtime import default_manifest_path
from ..mcp.handler import handle_mcp_request
from ..provenance import record_packet_observation
from .operator_packet import (
    abandon_packet,
    commit_iteration,
    guide_patch_action,
    guide_turn,
    inspect_operator_packet,
    lock_frame as lock_operator_packet_frame,
    lock_report as lock_operator_packet_report,
    lock_v3_operator_layer,
    propose_v3_operator_layer,
    run_report as run_operator_packet_report,
    set_threshold_decision as set_operator_packet_threshold_decision,
    set_v3_layer_field,
    start_v3_layer_loop,
    start_operator_packet,
)
from .service import EngineApiService, Family

LOGGER = logging.getLogger("nepsis_cgn.api")
_RATE_LIMIT_LOCK = RLock()
_RATE_LIMIT_STATE: dict[str, list[float]] = {}


class _RequestBodyError(ValueError):
    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


def _default_store_path() -> str:
    configured = os.getenv("NEPSIS_API_STORE_PATH")
    if configured and configured.strip():
        return configured
    return str(
        (Path.cwd() / "ledger" / "sessions" / "engine_api_sessions.db").resolve()
    )


API = EngineApiService(store_path=_default_store_path())
ROUTES = (
    {
        "method": "POST",
        "path": "/mcp",
        "description": "Model Context Protocol JSON-RPC tool endpoint",
    },
    {"method": "GET", "path": "/v1/health", "description": "Health check"},
    {"method": "GET", "path": "/v1/routes", "description": "API route manifest"},
    {
        "method": "GET",
        "path": "/v1/openapi.json",
        "description": "OpenAPI specification",
    },
    {
        "method": "POST",
        "path": "/v1/mvp",
        "description": "Run canonical MVP packet demo",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/start",
        "description": "Start stateless operator packet",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/state",
        "description": "Inspect stateless operator packet state",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/frame",
        "description": "Lock frame into stateless operator packet",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/report",
        "description": "Run report through stateless operator packet",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/report/lock",
        "description": "Lock stateless operator packet report",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/threshold",
        "description": "Set stateless operator packet threshold decision",
    },
        {
            "method": "POST",
            "path": "/v1/operator-packet/guide",
            "description": "Append a structured operator guide turn to a stateless packet",
        },
        {
            "method": "POST",
            "path": "/v1/operator-packet/guide/patch-action",
            "description": "Append an operator disposition for a guide packet patch",
        },
    {
        "method": "POST",
        "path": "/v1/operator-packet/v3/start",
        "description": "Start stateless operator packet V3 layer loop",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/v3/field",
        "description": "Set a stateless V3 operator layer field",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/v3/propose",
        "description": "Propose a stateless V3 operator layer lock",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/v3/lock",
        "description": "Lock a stateless V3 operator layer",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/commit",
        "description": "Commit stateless operator packet iteration",
    },
    {
        "method": "POST",
        "path": "/v1/operator-packet/abandon",
        "description": "Abandon stateless operator packet loop",
    },
    {
        "method": "GET",
        "path": "/v1/operator/session",
        "description": "Get ambient operator session phase state",
    },
    {
        "method": "POST",
        "path": "/v1/operator/frame",
        "description": "Lock ambient operator frame",
    },
    {
        "method": "POST",
        "path": "/v1/operator/report",
        "description": "Run ambient operator report",
    },
    {
        "method": "POST",
        "path": "/v1/operator/report/lock",
        "description": "Lock ambient operator report",
    },
    {
        "method": "POST",
        "path": "/v1/operator/threshold",
        "description": "Set ambient operator threshold decision",
    },
    {
        "method": "POST",
        "path": "/v1/operator/commit",
        "description": "Commit ambient operator iteration audit",
    },
    {
        "method": "POST",
        "path": "/v1/operator/abandon",
        "description": "Abandon ambient operator session",
    },
    {"method": "POST", "path": "/v1/sessions", "description": "Create engine session"},
    {"method": "GET", "path": "/v1/sessions", "description": "List sessions"},
    {
        "method": "DELETE",
        "path": "/v1/sessions",
        "description": "Purge old sessions by TTL",
    },
    {
        "method": "GET",
        "path": "/v1/sessions/{session_id}",
        "description": "Get session summary",
    },
    {
        "method": "DELETE",
        "path": "/v1/sessions/{session_id}",
        "description": "Delete session",
    },
    {
        "method": "POST",
        "path": "/v1/sessions/{session_id}/step",
        "description": "Run one step",
    },
    {
        "method": "POST",
        "path": "/v1/sessions/{session_id}/reframe",
        "description": "Update frame version",
    },
    {
        "method": "POST",
        "path": "/v1/sessions/{session_id}/workspace",
        "description": "Persist UI workspace state",
    },
    {
        "method": "GET",
        "path": "/v1/sessions/{session_id}/stage-audit",
        "description": "Audit stage gate readiness",
    },
    {
        "method": "POST",
        "path": "/v1/sessions/{session_id}/stage-audit",
        "description": "Audit stage gate readiness with context",
    },
    {
        "method": "GET",
        "path": "/v1/sessions/{session_id}/packets",
        "description": "Get replay packets",
    },
    {
        "method": "GET",
        "path": "/v1/sessions/{session_id}/provenance",
        "description": "Get packet provenance graph",
    },
    {
        "method": "GET",
        "path": "/v1/sessions/{session_id}/audit-export",
        "description": "Export session audit trail",
    },
    {
        "method": "GET",
        "path": "/v1/provenance/requests/{request_id}",
        "description": "Reconstruct packet flow by request",
    },
    {
        "method": "GET",
        "path": "/v1/provenance/packets/{packet_id}/lineage",
        "description": "Get packet lineage graph",
    },
)


def _operator_family(value: Any) -> Family:
    if value not in {"puzzle", "clinical", "safety"}:
        raise ValueError("family must be one of: puzzle, clinical, safety")
    return value


def _required_operator_packet(body: dict[str, Any]) -> dict[str, Any]:
    packet = body.get("packet")
    if not isinstance(packet, dict):
        raise ValueError("operator packet payload requires object field 'packet'")
    return packet


class EngineApiHandler(BaseHTTPRequestHandler):
    server_version = "NepsisApi/0.3"

    def setup(self) -> None:  # noqa: D401
        super().setup()
        timeout = _request_timeout_seconds()
        if timeout > 0:
            self.connection.settimeout(timeout)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._initialize_request_context()
        origin = self.headers.get("Origin")
        if origin and not _is_origin_allowed(origin):
            self._send_json(403, {"error": "CORS origin not allowed"})
            return
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        self._initialize_request_context()
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=False)
        if not self._authorize_request("GET", path):
            return
        if path in {"/health", "/v1/health"}:
            self._send_json(200, {"ok": True})
            return
        if path == "/v1/routes":
            self._send_json(200, {"routes": route_manifest()})
            return
        if path == "/v1/openapi.json":
            self._send_json(200, openapi_spec())
            return
        if path == "/v1/sessions":
            self._safe(lambda: self._list_sessions(query))
            return
        if path == "/v1/operator/session":
            self._safe(lambda: API.get_operator_session_state())
            return

        m_session = re.fullmatch(r"/v1/sessions/([^/]+)", path)
        if m_session:
            session_id = m_session.group(1)
            self._safe(
                lambda: API.get_session(session_id, owner_id=_handler_owner_id(self))
            )
            return

        m_packets = re.fullmatch(r"/v1/sessions/([^/]+)/packets", path)
        if m_packets:
            session_id = m_packets.group(1)
            self._safe(lambda: self._get_packets(session_id, query))
            return

        m_provenance = re.fullmatch(r"/v1/sessions/([^/]+)/provenance", path)
        if m_provenance:
            session_id = m_provenance.group(1)
            self._safe(
                lambda: API.get_packet_provenance(
                    session_id, owner_id=_handler_owner_id(self)
                )
            )
            return

        m_audit_export = re.fullmatch(r"/v1/sessions/([^/]+)/audit-export", path)
        if m_audit_export:
            session_id = m_audit_export.group(1)
            self._safe(
                lambda: API.export_session_audit(
                    session_id, owner_id=_handler_owner_id(self)
                )
            )
            return

        m_request_provenance = re.fullmatch(r"/v1/provenance/requests/([^/]+)", path)
        if m_request_provenance:
            request_id = m_request_provenance.group(1)
            self._safe(
                lambda: API.get_request_provenance(
                    request_id, owner_id=_handler_owner_id(self)
                )
            )
            return

        m_packet_lineage = re.fullmatch(r"/v1/provenance/packets/([^/]+)/lineage", path)
        if m_packet_lineage:
            packet_id = m_packet_lineage.group(1)
            self._safe(
                lambda: API.get_packet_lineage(
                    packet_id, owner_id=_handler_owner_id(self)
                )
            )
            return

        m_stage_audit = re.fullmatch(r"/v1/sessions/([^/]+)/stage-audit", path)
        if m_stage_audit:
            session_id = m_stage_audit.group(1)
            self._safe(
                lambda: API.stage_audit_session(
                    session_id,
                    owner_id=_handler_owner_id(self),
                    request_context=_handler_request_context(self),
                )
            )
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        self._initialize_request_context()
        path = urlparse(self.path).path
        if not self._authorize_request("POST", path):
            return

        try:
            body = self._read_json()
        except _RequestBodyError as exc:
            self._send_json(exc.status, {"error": str(exc)})
            return

        if path == "/v1/sessions":
            self._safe(lambda: self._create_session(body))
            return

        if path == "/v1/mvp":
            self._safe(lambda: self._run_mvp(body))
            return

        if path == "/mcp":
            self._handle_mcp(body)
            return

        if path == "/v1/operator/frame":
            self._safe(lambda: self._operator_lock_frame(body))
            return

        if path == "/v1/operator-packet/start":
            self._safe(lambda: self._operator_packet_start(body))
            return

        if path == "/v1/operator-packet/state":
            self._safe(lambda: self._operator_packet_state(body))
            return

        if path == "/v1/operator-packet/frame":
            self._safe(lambda: self._operator_packet_lock_frame(body))
            return

        if path == "/v1/operator-packet/report":
            self._safe(lambda: self._operator_packet_run_report(body))
            return

        if path == "/v1/operator-packet/report/lock":
            self._safe(lambda: self._operator_packet_lock_report(body))
            return

        if path == "/v1/operator-packet/threshold":
            self._safe(lambda: self._operator_packet_set_threshold_decision(body))
            return

        if path == "/v1/operator-packet/guide":
            self._safe(lambda: self._operator_packet_guide_turn(body))
            return

        if path == "/v1/operator-packet/guide/patch-action":
            self._safe(lambda: self._operator_packet_guide_patch_action(body))
            return

        if path == "/v1/operator-packet/v3/start":
            self._safe(lambda: self._operator_packet_v3_start(body))
            return

        if path == "/v1/operator-packet/v3/field":
            self._safe(lambda: self._operator_packet_v3_set_field(body))
            return

        if path == "/v1/operator-packet/v3/propose":
            self._safe(lambda: self._operator_packet_v3_propose(body))
            return

        if path == "/v1/operator-packet/v3/lock":
            self._safe(lambda: self._operator_packet_v3_lock(body))
            return

        if path == "/v1/operator-packet/commit":
            self._safe(lambda: self._operator_packet_commit_iteration(body))
            return

        if path == "/v1/operator-packet/abandon":
            self._safe(lambda: self._operator_packet_abandon(body))
            return

        if path == "/v1/operator/report":
            self._safe(lambda: self._operator_run_report(body))
            return

        if path == "/v1/operator/report/lock":
            self._safe(lambda: API.operator_lock_report())
            return

        if path == "/v1/operator/threshold":
            self._safe(lambda: self._operator_set_threshold_decision(body))
            return

        if path == "/v1/operator/commit":
            self._safe(lambda: self._operator_commit_iteration(body))
            return

        if path == "/v1/operator/abandon":
            self._safe(lambda: self._operator_abandon_session(body))
            return

        m_step = re.fullmatch(r"/v1/sessions/([^/]+)/step", path)
        if m_step:
            session_id = m_step.group(1)
            self._safe(lambda: self._step_session(session_id, body))
            return

        m_reframe = re.fullmatch(r"/v1/sessions/([^/]+)/reframe", path)
        if m_reframe:
            session_id = m_reframe.group(1)
            self._safe(lambda: self._reframe_session(session_id, body))
            return

        m_stage_audit = re.fullmatch(r"/v1/sessions/([^/]+)/stage-audit", path)
        if m_stage_audit:
            session_id = m_stage_audit.group(1)
            self._safe(lambda: self._stage_audit_session(session_id, body))
            return

        m_workspace = re.fullmatch(r"/v1/sessions/([^/]+)/workspace", path)
        if m_workspace:
            session_id = m_workspace.group(1)
            self._safe(lambda: self._update_workspace_state(session_id, body))
            return

        self._send_json(404, {"error": "Not found"})

    def do_DELETE(self) -> None:  # noqa: N802
        self._initialize_request_context()
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query, keep_blank_values=False)
        if not self._authorize_request("DELETE", path):
            return
        if path == "/v1/sessions":
            self._safe(lambda: self._purge_sessions(query))
            return
        m_session = re.fullmatch(r"/v1/sessions/([^/]+)", path)
        if m_session:
            session_id = m_session.group(1)
            self._safe(
                lambda: API.delete_session(session_id, owner_id=_handler_owner_id(self))
            )
            return
        self._send_json(404, {"error": "Not found"})

    def _create_session(self, body: dict[str, Any]) -> dict[str, Any]:
        family = body.get("family")
        if family not in {"puzzle", "clinical", "safety"}:
            raise ValueError("family must be one of: puzzle, clinical, safety")
        governance = body.get("governance")
        if governance is not None and not isinstance(governance, dict):
            raise ValueError("governance must be an object when provided")
        calibration = body.get("calibration")
        if calibration is not None and not isinstance(calibration, dict):
            raise ValueError("calibration must be an object when provided")
        manifest_path = _validated_manifest_path(body.get("manifest_path"))
        return API.create_session(
            family=family,
            manifest_path=manifest_path,
            governance_costs=governance,
            governance_calibration=calibration,
            emit_packet=bool(body.get("emit_packet", True)),
            frame=body.get("frame"),
            owner_id=_handler_owner_id(self),
        )

    def _step_session(self, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
        sign = body.get("sign")
        if not isinstance(sign, dict):
            raise ValueError("step payload requires object field 'sign'")
        return API.step_session(
            session_id,
            sign=sign,
            commit=bool(body.get("commit", False)),
            user_decision=body.get("user_decision"),
            override_reason=body.get("override_reason"),
            carry_forward=body.get("carry_forward"),
            owner_id=_handler_owner_id(self),
            request_context=_handler_request_context(self),
        )

    def _reframe_session(self, session_id: str, body: dict[str, Any]) -> dict[str, Any]:
        frame = body.get("frame")
        if not isinstance(frame, dict):
            raise ValueError("reframe payload requires object field 'frame'")
        branch_id = body.get("branch_id")
        if branch_id is not None and (
            not isinstance(branch_id, str) or not branch_id.strip()
        ):
            raise ValueError("branch_id must be a non-empty string when provided")
        parent_frame_id = body.get("parent_frame_id")
        if parent_frame_id is not None and (not isinstance(parent_frame_id, str)):
            raise ValueError("parent_frame_id must be a string when provided")
        return API.reframe_session(
            session_id,
            frame=frame,
            branch_id=branch_id.strip() if isinstance(branch_id, str) else None,
            parent_frame_id=(
                parent_frame_id.strip() if isinstance(parent_frame_id, str) else None
            ),
            owner_id=_handler_owner_id(self),
        )

    def _stage_audit_session(
        self, session_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        raw_context = body.get("context", body)
        if raw_context is None:
            context = None
        else:
            if not isinstance(raw_context, dict):
                raise ValueError(
                    "stage-audit payload 'context' must be an object when provided"
                )
            context = raw_context
        return API.stage_audit_session(
            session_id,
            context=context,
            persist_context=bool(body.get("persist_context", False)),
            owner_id=_handler_owner_id(self),
            request_context=_handler_request_context(self),
        )

    def _update_workspace_state(
        self, session_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        workspace_state = body.get("workspace_state", body.get("state", body))
        if not isinstance(workspace_state, dict):
            raise ValueError("workspace_state must be an object")
        return API.update_workspace_state(
            session_id,
            workspace_state=workspace_state,
            owner_id=_handler_owner_id(self),
        )

    def _run_mvp(self, body: dict[str, Any]) -> dict[str, Any]:
        case_id = body.get("case_id", body.get("case", "jailing"))
        if case_id not in PUBLIC_MVP_CASE_IDS:
            raise ValueError(
                f"case_id must be one of: {', '.join(PUBLIC_MVP_CASE_IDS)}"
            )
        input_text = body.get("input_text", body.get("inputText"))
        if input_text is not None and not isinstance(input_text, str):
            raise ValueError("input_text must be a string when provided")
        packet = build_nepsis_mvp_packet(case_id=case_id, input_text=input_text)
        record_packet_observation(
            packet=packet,
            source="backend_mvp",
            retention_mode="retained",
            request_context=_handler_request_context(self),
        )
        return packet

    def _operator_lock_frame(self, body: dict[str, Any]) -> dict[str, Any]:
        frame = body.get("frame")
        if not isinstance(frame, dict):
            raise ValueError("operator frame payload requires object field 'frame'")
        family = body.get("family", "safety")
        if family not in {"puzzle", "clinical", "safety"}:
            raise ValueError("family must be one of: puzzle, clinical, safety")
        governance = body.get("governance_costs", body.get("governance"))
        if governance is not None and not isinstance(governance, dict):
            raise ValueError("governance must be an object when provided")
        calibration = body.get("governance_calibration", body.get("calibration"))
        if calibration is not None and not isinstance(calibration, dict):
            raise ValueError("calibration must be an object when provided")
        return API.operator_lock_frame(
            family=family,
            frame=frame,
            governance_costs=governance,
            governance_calibration=calibration,
            manifest_path=_validated_manifest_path(body.get("manifest_path")),
        )

    def _operator_run_report(self, body: dict[str, Any]) -> dict[str, Any]:
        report_text = body.get("report_text", body.get("reportText"))
        sign = body.get("sign")
        interpretation = body.get("interpretation")
        if not isinstance(report_text, str):
            raise ValueError(
                "operator report payload requires string field 'report_text'"
            )
        if not isinstance(sign, dict):
            raise ValueError("operator report payload requires object field 'sign'")
        if interpretation is not None and not isinstance(interpretation, dict):
            raise ValueError("interpretation must be an object when provided")
        return API.operator_run_report(
            report_text=report_text,
            sign=sign,
            interpretation=interpretation,
        )

    def _operator_set_threshold_decision(self, body: dict[str, Any]) -> dict[str, Any]:
        decision = body.get("decision")
        hold_reason = body.get("hold_reason", body.get("holdReason", ""))
        if not isinstance(decision, str):
            raise ValueError("threshold payload requires string field 'decision'")
        if not isinstance(hold_reason, str):
            raise ValueError("hold_reason must be a string when provided")
        return API.operator_set_threshold_decision(
            decision=decision, hold_reason=hold_reason
        )

    def _operator_commit_iteration(self, body: dict[str, Any]) -> dict[str, Any]:
        carry_forward_frame = body.get(
            "carry_forward_frame", body.get("carryForwardFrame")
        )
        if carry_forward_frame is not None and not isinstance(
            carry_forward_frame, dict
        ):
            raise ValueError("carry_forward_frame must be an object when provided")
        return API.operator_commit_iteration(
            carry_forward_frame=carry_forward_frame,
            request_context=_handler_request_context(self),
        )

    def _operator_abandon_session(self, body: dict[str, Any]) -> dict[str, Any]:
        reason = body.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("reason must be a string when provided")
        return API.operator_abandon_session(
            reason=reason, request_context=_handler_request_context(self)
        )

    def _operator_packet_start(self, body: dict[str, Any]) -> dict[str, Any]:
        family = _operator_family(body.get("family", "safety"))
        frame = body.get("frame")
        if frame is not None and not isinstance(frame, dict):
            raise ValueError("frame must be an object when provided")
        governance = body.get("governance_costs", body.get("governance"))
        if governance is not None and not isinstance(governance, dict):
            raise ValueError("governance must be an object when provided")
        calibration = body.get("governance_calibration", body.get("calibration"))
        if calibration is not None and not isinstance(calibration, dict):
            raise ValueError("calibration must be an object when provided")
        return self._record_stateless_packet_result(
            start_operator_packet(
                family=family,
                frame=frame,
                governance_costs=governance,
                governance_calibration=calibration,
                manifest_path=_validated_manifest_path(body.get("manifest_path")),
            )
        )

    def _operator_packet_state(self, body: dict[str, Any]) -> dict[str, Any]:
        packet = body.get("packet")
        if packet is not None and not isinstance(packet, dict):
            raise ValueError(
                "operator packet payload requires object field 'packet' when provided"
            )
        return self._record_stateless_packet_result(inspect_operator_packet(packet))

    def _operator_packet_lock_report(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._record_stateless_packet_result(
            lock_operator_packet_report(packet=_required_operator_packet(body))
        )

    def _record_stateless_packet_result(self, result: dict[str, Any]) -> dict[str, Any]:
        if result.get("schema_id") in {
            "nepsis.operator_packet",
            "nepsis.operator_packet_state",
            "nepsis.phase_rejection",
        }:
            record_packet_observation(
                packet=result,
                source="stateless_operator_packet",
                retention_mode="hash_only",
                request_context=_handler_request_context(self),
            )
        return result

    def _request_context(self) -> dict[str, Any]:
        return {
            "request_id": self._request_id,
            "method": self.command,
            "path": urlparse(self.path).path,
        }

    def _operator_packet_lock_frame(self, body: dict[str, Any]) -> dict[str, Any]:
        packet = _required_operator_packet(body)
        frame = body.get("frame")
        if not isinstance(frame, dict):
            raise ValueError(
                "operator packet frame payload requires object field 'frame'"
            )
        family = body.get("family")
        governance = body.get("governance_costs", body.get("governance"))
        if governance is not None and not isinstance(governance, dict):
            raise ValueError("governance must be an object when provided")
        calibration = body.get("governance_calibration", body.get("calibration"))
        if calibration is not None and not isinstance(calibration, dict):
            raise ValueError("calibration must be an object when provided")
        return self._record_stateless_packet_result(
            lock_operator_packet_frame(
                packet=packet,
                frame=frame,
                family=_operator_family(family) if family is not None else None,
                governance_costs=governance,
                governance_calibration=calibration,
                manifest_path=_validated_manifest_path(body.get("manifest_path")),
                assist_acceptances=body.get("assist_acceptances"),
            )
        )

    def _operator_packet_run_report(self, body: dict[str, Any]) -> dict[str, Any]:
        packet = _required_operator_packet(body)
        report_text = body.get("report_text", body.get("reportText"))
        sign = body.get("sign")
        interpretation = body.get("interpretation")
        if not isinstance(report_text, str):
            raise ValueError(
                "operator packet report payload requires string field 'report_text'"
            )
        if not isinstance(sign, dict):
            raise ValueError(
                "operator packet report payload requires object field 'sign'"
            )
        if interpretation is not None and not isinstance(interpretation, dict):
            raise ValueError("interpretation must be an object when provided")
        return self._record_stateless_packet_result(
            run_operator_packet_report(
                packet=packet,
                report_text=report_text,
                sign=sign,
                interpretation=interpretation,
            )
        )

    def _operator_packet_set_threshold_decision(
        self, body: dict[str, Any]
    ) -> dict[str, Any]:
        packet = _required_operator_packet(body)
        decision = body.get("decision")
        hold_reason = body.get("hold_reason", body.get("holdReason", ""))
        if not isinstance(decision, str):
            raise ValueError(
                "operator packet threshold payload requires string field 'decision'"
            )
        if not isinstance(hold_reason, str):
            raise ValueError("hold_reason must be a string when provided")
        return self._record_stateless_packet_result(
            set_operator_packet_threshold_decision(
                packet=packet,
                decision=decision,
                hold_reason=hold_reason,
                assist_acceptances=body.get("assist_acceptances"),
            )
        )

    def _operator_packet_guide_turn(self, body: dict[str, Any]) -> dict[str, Any]:
        packet = _required_operator_packet(body)
        user_message = body.get("user_message", body.get("userMessage"))
        domain_adapter = body.get("domain_adapter", body.get("domainAdapter", "general"))
        guide = body.get("guide")
        if not isinstance(user_message, str):
            raise ValueError("operator packet guide payload requires string field 'user_message'")
        if not isinstance(domain_adapter, str):
            raise ValueError("domain_adapter must be a string when provided")
        if not isinstance(guide, dict):
            raise ValueError("operator packet guide payload requires object field 'guide'")
        return self._record_stateless_packet_result(
            guide_turn(
                packet=packet,
                user_message=user_message,
                domain_adapter=domain_adapter,
                guide=guide,
            )
        )

    def _operator_packet_guide_patch_action(self, body: dict[str, Any]) -> dict[str, Any]:
        packet = _required_operator_packet(body)
        patch_id = body.get("patch_id", body.get("patchId"))
        action = body.get("action")
        if not isinstance(patch_id, str):
            raise ValueError("guide patch action payload requires string field 'patch_id'")
        if not isinstance(action, str):
            raise ValueError("guide patch action payload requires string field 'action'")
        confirmation = body.get("confirmation")
        if confirmation is not None and not isinstance(confirmation, dict):
            raise ValueError("confirmation must be an object when provided")
        return self._record_stateless_packet_result(
            guide_patch_action(
                packet=packet,
                patch_id=patch_id,
                action=action,
                final_value=body.get("final_value", body.get("finalValue")),
                confirmation=confirmation,
                receipt_id=body.get("receipt_id", body.get("receiptId")),
                batch_id=body.get("batch_id", body.get("batchId")),
            )
        )

    def _operator_packet_v3_start(self, body: dict[str, Any]) -> dict[str, Any]:
        goal = body.get("goal")
        scope = body.get("scope")
        initial_context = body.get("initial_context", body.get("initialContext"))
        if not isinstance(goal, str):
            raise ValueError("v3 layer loop payload requires string field 'goal'")
        if not isinstance(scope, str):
            raise ValueError("v3 layer loop payload requires string field 'scope'")
        if initial_context is not None and not isinstance(initial_context, str):
            raise ValueError("initial_context must be a string when provided")
        return self._record_stateless_packet_result(
            start_v3_layer_loop(
                packet=_required_operator_packet(body),
                goal=goal,
                scope=scope,
                initial_context=initial_context,
            )
        )

    def _operator_packet_v3_set_field(self, body: dict[str, Any]) -> dict[str, Any]:
        layer = body.get("layer")
        field = body.get("field")
        if not isinstance(layer, str):
            raise ValueError("v3 layer field payload requires string field 'layer'")
        if not isinstance(field, str):
            raise ValueError("v3 layer field payload requires string field 'field'")
        if "value" not in body:
            raise ValueError("v3 layer field payload requires field 'value'")
        return self._record_stateless_packet_result(
            set_v3_layer_field(
                packet=_required_operator_packet(body),
                layer=layer,
                field=field,
                value=body.get("value"),
                assist_acceptances=body.get("assist_acceptances"),
            )
        )

    def _operator_packet_v3_propose(self, body: dict[str, Any]) -> dict[str, Any]:
        layer = body.get("layer")
        if not isinstance(layer, str):
            raise ValueError("v3 layer proposal payload requires string field 'layer'")
        return self._record_stateless_packet_result(
            propose_v3_operator_layer(
                packet=_required_operator_packet(body), layer=layer
            )
        )

    def _operator_packet_v3_lock(self, body: dict[str, Any]) -> dict[str, Any]:
        layer = body.get("layer")
        lock_assertion = body.get("lock_assertion", body.get("lockAssertion"))
        if not isinstance(layer, str):
            raise ValueError("v3 layer lock payload requires string field 'layer'")
        if not isinstance(lock_assertion, dict):
            raise ValueError(
                "v3 layer lock payload requires object field 'lock_assertion'"
            )
        return self._record_stateless_packet_result(
            lock_v3_operator_layer(
                packet=_required_operator_packet(body),
                layer=layer,
                lock_assertion=lock_assertion,
            )
        )

    def _operator_packet_commit_iteration(self, body: dict[str, Any]) -> dict[str, Any]:
        packet = _required_operator_packet(body)
        carry_forward_frame = body.get(
            "carry_forward_frame", body.get("carryForwardFrame")
        )
        if carry_forward_frame is not None and not isinstance(
            carry_forward_frame, dict
        ):
            raise ValueError("carry_forward_frame must be an object when provided")
        return self._record_stateless_packet_result(
            commit_iteration(
                packet=packet,
                carry_forward_frame=carry_forward_frame,
                assist_acceptances=body.get("assist_acceptances"),
            )
        )

    def _operator_packet_abandon(self, body: dict[str, Any]) -> dict[str, Any]:
        packet = _required_operator_packet(body)
        reason = body.get("reason", "")
        if not isinstance(reason, str):
            raise ValueError("reason must be a string when provided")
        return self._record_stateless_packet_result(
            abandon_packet(packet=packet, reason=reason)
        )

    def _list_sessions(self, query: dict[str, list[str]]) -> dict[str, Any]:
        limit = _query_optional_int(query, "limit", default=50)
        offset = _query_optional_int(query, "offset", default=0)
        return API.list_sessions(
            limit=limit, offset=offset, owner_id=_handler_owner_id(self)
        )

    def _get_packets(
        self, session_id: str, query: dict[str, list[str]]
    ) -> dict[str, Any]:
        limit = _query_optional_int(query, "limit", default=100)
        offset = _query_optional_int(query, "offset", default=0)
        return API.get_packets(
            session_id, limit=limit, offset=offset, owner_id=_handler_owner_id(self)
        )

    def _purge_sessions(self, query: dict[str, list[str]]) -> dict[str, Any]:
        max_age_seconds = _query_required_float(query, "max_age_seconds")
        dry_run = _query_optional_bool(query, "dry_run", default=False)
        return API.purge_sessions(
            max_age_seconds=max_age_seconds,
            dry_run=dry_run,
            owner_id=_handler_owner_id(self),
        )

    def _safe(self, op: Callable[[], dict[str, Any]]) -> None:
        try:
            payload = op()
            status = (
                409 if payload.get("schema_id") == "nepsis.phase_rejection" else 200
            )
            self._send_json(status, payload)
        except KeyError:
            self._send_json(404, {"error": "Not found"})
        except PermissionError:
            LOGGER.info(
                "permission_denied",
                extra={"request_id": self._request_id, "path": self.path},
            )
            self._send_json(404, {"error": "Not found"})
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception:  # pragma: no cover
            LOGGER.exception(
                "request_failed",
                extra={
                    "request_id": self._request_id,
                    "method": self.command,
                    "path": self.path,
                },
            )
            self._send_json(
                500, {"error": "Internal server error", "request_id": self._request_id}
            )

    def _read_json(self) -> dict[str, Any]:
        length_header = self.headers.get("Content-Length", "0")
        try:
            length = int(length_header)
        except ValueError as exc:
            raise _RequestBodyError(
                "Invalid Content-Length header", status=400
            ) from exc
        if length < 0:
            raise _RequestBodyError("Content-Length must be >= 0", status=400)

        max_bytes = _max_request_body_bytes()
        if length > max_bytes:
            raise _RequestBodyError(
                f"Request body too large (max {max_bytes} bytes)",
                status=413,
            )

        try:
            raw = self.rfile.read(length) if length > 0 else b"{}"
        except TimeoutError as exc:
            raise _RequestBodyError("Request body read timeout", status=408) from exc
        except OSError as exc:
            raise _RequestBodyError("Request body read failed", status=400) from exc

        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise _RequestBodyError("Invalid JSON body", status=400) from exc

        if not isinstance(data, dict):
            raise _RequestBodyError("JSON body must be an object", status=400)
        return data

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Request-ID", self._request_id)

        allowed_origin = self._allowed_origin_for_request()
        if allowed_origin is not None:
            self.send_header("Access-Control-Allow-Origin", allowed_origin)
            self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Headers",
                "Content-Type, Authorization, X-API-Key, X-Request-ID, X-Nepsis-Capability-Token",
            )
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS"
            )
            self.send_header("Access-Control-Max-Age", "600")

        self.end_headers()
        self.wfile.write(body)
        if not self._response_logged:
            duration_ms = int((time.perf_counter() - self._request_started_at) * 1000)
            LOGGER.info(
                json.dumps(
                    {
                        "event": "api_response",
                        "request_id": self._request_id,
                        "method": self.command,
                        "path": urlparse(self.path).path,
                        "status": status,
                        "duration_ms": duration_ms,
                        "remote_addr": (
                            self.client_address[0] if self.client_address else None
                        ),
                    }
                )
            )
            self._response_logged = True

    def _allowed_origin_for_request(self) -> str | None:
        origin = self.headers.get("Origin")
        if not origin:
            return None
        if not _is_origin_allowed(origin):
            return None
        if "*" in _allowed_origins():
            return "*"
        return origin

    def _initialize_request_context(self) -> None:
        incoming_request_id = self.headers.get("X-Request-ID")
        if incoming_request_id and incoming_request_id.strip():
            self._request_id = incoming_request_id.strip()[:128]
        else:
            self._request_id = str(uuid4())
        self._request_started_at = time.perf_counter()
        self._response_logged = False

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
        return

    def _authorize_request(self, method: str, path: str) -> bool:
        origin = self.headers.get("Origin")
        if origin and not _is_origin_allowed(origin):
            self._send_json(403, {"error": "CORS origin not allowed"})
            return False

        if method == "OPTIONS":
            return True
        if path in {"/health", "/v1/health", "/v1/routes", "/v1/openapi.json", "/mcp"}:
            return True

        if not self._enforce_rate_limit(path):
            return False

        expected_token = _configured_api_token()
        if _auth_required() and expected_token is None:
            self._send_json(503, {"error": "Server auth misconfigured"})
            return False
        if expected_token is None:
            return True

        token = _request_api_token(self.headers)
        if _api_token_matches(token, expected_token):
            return True

        self._send_json(401, {"error": "Unauthorized"})
        return False

    def _enforce_rate_limit(self, path: str) -> bool:
        # Public informational routes are not rate-limited.
        if path in {"/health", "/v1/health", "/v1/routes", "/v1/openapi.json"}:
            return True
        key = _rate_limit_key(self)
        window_seconds = _rate_limit_window_seconds()
        max_requests = _rate_limit_max_requests()
        now = time.monotonic()
        cutoff = now - window_seconds

        with _RATE_LIMIT_LOCK:
            bucket = _RATE_LIMIT_STATE.get(key, [])
            bucket = [ts for ts in bucket if ts >= cutoff]
            if len(bucket) >= max_requests:
                _RATE_LIMIT_STATE[key] = bucket
                self._send_json(
                    429,
                    {
                        "error": "Rate limit exceeded",
                        "retry_after_seconds": int(
                            max(window_seconds - (now - bucket[0]), 1)
                        ),
                    },
                )
                return False
            bucket.append(now)
            _RATE_LIMIT_STATE[key] = bucket
        return True

    def _handle_mcp(self, body: dict[str, Any]) -> None:
        response = handle_mcp_request(
            body,
            headers=dict(self.headers),
            require_capability_token=True,
            server_name="nepsis-cgn",
            route_manifest_fn=route_manifest,
            request_id=self._request_id,
        )
        if response is None:
            self._send_json(202, {})
            return
        self._send_json(200, response)


def run(host: str = "127.0.0.1", port: int = 8787) -> None:
    _assert_runtime_auth_configuration()
    try:
        server = ThreadingHTTPServer((host, port), EngineApiHandler)
    except PermissionError as exc:
        raise SystemExit(_bind_error_message(host, port, exc)) from exc
    except OSError as exc:
        raise SystemExit(_bind_error_message(host, port, exc)) from exc

    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.server_close()


def _bind_error_message(host: str, port: int, exc: OSError) -> str:
    suggested = _suggest_open_port(host, port)
    suggestion_text = (
        f"1) Use a different port, e.g. --port {suggested}"
        if suggested is not None
        else "1) Use a different free port"
    )
    return (
        f"Failed to bind Nepsis API on {host}:{port}: {exc}\n"
        "Try one of:\n"
        f"{suggestion_text}\n"
        "2) Use host 127.0.0.1 explicitly\n"
        "3) Run outside restricted sandbox/container if local bind is blocked"
    )


def _suggest_open_port(host: str, port: int, span: int = 20) -> int | None:
    candidates: list[int] = []
    for offset in range(1, span + 1):
        plus = port + offset
        minus = port - offset
        if plus <= 65535:
            candidates.append(plus)
        if minus >= 1:
            candidates.append(minus)

    for candidate in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
            except OSError:
                continue
            return candidate
    return None


def _auth_required() -> bool:
    return os.getenv("NEPSIS_API_ALLOW_ANON", "false").strip().lower() not in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _assert_runtime_auth_configuration() -> None:
    if _auth_required() and _configured_api_token() is None:
        raise SystemExit(
            "NEPSIS_API_TOKEN is required when anonymous access is disabled "
            "(set NEPSIS_API_ALLOW_ANON=true only for local development)."
        )


def _configured_api_token() -> str | None:
    raw = os.getenv("NEPSIS_API_TOKEN")
    if raw is None:
        return None
    token = raw.strip()
    return token or None


def _request_api_token(headers: Any) -> str | None:
    auth = headers.get("Authorization")
    if isinstance(auth, str) and auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    x_api_key = headers.get("X-API-Key")
    if isinstance(x_api_key, str):
        token = x_api_key.strip()
        if token:
            return token
    return None


def _api_token_matches(token: str | None, expected: str) -> bool:
    if token is None:
        return False
    return hmac.compare_digest(token, expected)


def _request_owner_id(headers: Any) -> str | None:
    owner_id = headers.get("X-Nepsis-Session-Owner")
    if not isinstance(owner_id, str):
        return None
    normalized = owner_id.strip().lower()
    if not normalized:
        return None
    if len(normalized) > 256:
        raise ValueError("X-Nepsis-Session-Owner must be 256 characters or fewer.")
    return normalized


def _handler_owner_id(handler: Any) -> str | None:
    return _request_owner_id(getattr(handler, "headers", {}))


def _handler_request_context(handler: Any) -> dict[str, Any] | None:
    request_context = getattr(handler, "_request_context", None)
    if not callable(request_context):
        return None
    return request_context()


def _query_required_float(query: dict[str, list[str]], name: str) -> float:
    values = query.get(name)
    if not values:
        raise ValueError(f"Missing required query param: {name}")
    raw = values[0]
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid float for query param '{name}': {raw}") from exc


def _query_optional_bool(
    query: dict[str, list[str]], name: str, *, default: bool
) -> bool:
    values = query.get(name)
    if not values:
        return default
    raw = values[0].strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean for query param '{name}': {values[0]}")


def _query_optional_int(query: dict[str, list[str]], name: str, *, default: int) -> int:
    values = query.get(name)
    if not values:
        return default
    raw = values[0]
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid integer for query param '{name}': {raw}") from exc
    return value


def _request_timeout_seconds() -> float:
    raw = os.getenv("NEPSIS_API_REQUEST_TIMEOUT_SECONDS", "15")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError("NEPSIS_API_REQUEST_TIMEOUT_SECONDS must be a number") from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_REQUEST_TIMEOUT_SECONDS must be > 0")
    return value


def _max_request_body_bytes() -> int:
    raw = os.getenv("NEPSIS_API_MAX_REQUEST_BODY_BYTES", "1048576")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            "NEPSIS_API_MAX_REQUEST_BODY_BYTES must be an integer"
        ) from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_MAX_REQUEST_BODY_BYTES must be > 0")
    return value


def _allowed_origins() -> set[str]:
    raw = os.getenv("NEPSIS_API_ALLOWED_ORIGINS", "")
    items = {item.strip() for item in raw.split(",") if item.strip()}
    return items


def _is_origin_allowed(origin: str) -> bool:
    allowed = _allowed_origins()
    if not allowed:
        return False
    if "*" in allowed and _wildcard_cors_forbidden():
        return False
    return "*" in allowed or origin in allowed


def _wildcard_cors_forbidden() -> bool:
    return (
        os.getenv("NODE_ENV", "").strip().lower() == "production"
        or os.getenv("NEPSIS_DEPLOYMENT_MODE", "").strip().lower() == "operator"
        or os.getenv("NEXT_PUBLIC_NEPSIS_OPERATOR_SITE", "").strip().lower()
        in {"1", "true", "yes", "y", "on"}
    )


def _validated_manifest_path(manifest_path: Any) -> str | None:
    if manifest_path is None:
        return None
    if not isinstance(manifest_path, str) or not manifest_path.strip():
        raise ValueError("manifest_path must be a non-empty string when provided")

    resolved = Path(manifest_path).expanduser().resolve()
    for root in _allowed_manifest_roots():
        if _is_path_within(resolved, root):
            return str(resolved)

    allowed = ", ".join(
        str(root) for root in sorted(_allowed_manifest_roots(), key=str)
    )
    raise ValueError(f"manifest_path is not allowed. Allowed roots: {allowed}")


def _allowed_manifest_roots() -> set[Path]:
    roots = {default_manifest_path().resolve().parent}
    raw = os.getenv("NEPSIS_API_ALLOWED_MANIFEST_ROOTS", "")
    for item in raw.split(","):
        value = item.strip()
        if value:
            roots.add(Path(value).expanduser().resolve())
    return roots


def _is_path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _rate_limit_window_seconds() -> float:
    raw = os.getenv("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS", "60")
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(
            "NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS must be a number"
        ) from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_RATE_LIMIT_WINDOW_SECONDS must be > 0")
    return value


def _rate_limit_max_requests() -> int:
    raw = os.getenv("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS", "120")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            "NEPSIS_API_RATE_LIMIT_MAX_REQUESTS must be an integer"
        ) from exc
    if value <= 0:
        raise ValueError("NEPSIS_API_RATE_LIMIT_MAX_REQUESTS must be > 0")
    return value


def _rate_limit_key(handler: EngineApiHandler) -> str:
    forwarded = _trusted_forwarded_ip(handler.headers)
    if forwarded:
        return f"ip:{forwarded}"
    client_ip = handler.client_address[0] if handler.client_address else "unknown"
    return f"ip:{client_ip}"


def _trusted_forwarded_ip(headers: Any) -> str | None:
    if os.getenv("NEPSIS_API_TRUST_FORWARDED_FOR", "").strip().lower() not in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }:
        return None
    real_ip = headers.get("X-Real-IP") or headers.get("x-real-ip")
    if isinstance(real_ip, str) and real_ip.strip():
        return real_ip.strip()
    forwarded = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if isinstance(forwarded, str) and forwarded.strip():
        return forwarded.split(",")[0].strip()
    return None


def route_manifest() -> list[dict[str, str]]:
    return [dict(route) for route in ROUTES]


def openapi_spec() -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for route in ROUTES:
        path = route["path"]
        method = route["method"].lower()
        operation_id = f"{method}_{path.strip('/').replace('/', '_').replace('{', '').replace('}', '') or 'root'}"
        paths.setdefault(path, {})
        paths[path][method] = {
            "operationId": operation_id,
            "summary": route["description"],
            "responses": {
                "200": {"description": "Success"},
                "400": {"description": "Bad Request"},
                "401": {"description": "Unauthorized"},
                "404": {"description": "Not Found"},
                "429": {"description": "Rate Limit Exceeded"},
                "500": {"description": "Internal Server Error"},
            },
        }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "NepsisCGN Engine API",
            "version": "0.3.0",
            "description": "Engine control API for NepsisCGN session lifecycle and governance.",
        },
        "paths": paths,
    }


def entrypoint(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=os.getenv("NEPSIS_API_LOG_LEVEL", "INFO"))
    parser = argparse.ArgumentParser(
        prog="nepsiscgn-api", description="NepsisCGN backend API server"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    run(host=args.host, port=args.port)


if __name__ == "__main__":  # pragma: no cover
    entrypoint(sys.argv[1:])
