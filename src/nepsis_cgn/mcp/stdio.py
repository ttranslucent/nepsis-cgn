from __future__ import annotations

import json
import logging
import sys
from typing import Any

from .handler import handle_mcp_request

LOGGER = logging.getLogger("nepsis_cgn.mcp.stdio")


def _route_manifest() -> list[dict[str, str]]:
    from ..api.server import route_manifest

    return route_manifest()


def _write_response(response: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def run_stdio() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            body = json.loads(line)
            if not isinstance(body, dict):
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "JSON-RPC message must be an object."},
                }
            else:
                response = handle_mcp_request(
                    body,
                    require_capability_token=False,
                    route_manifest_fn=_route_manifest,
                    server_name="nepsis-cgn-local",
                )
        except Exception as exc:
            LOGGER.exception("mcp_stdio_request_failed")
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(exc)},
            }
        if response is not None:
            _write_response(response)


def entrypoint(argv: list[str] | None = None) -> None:  # pragma: no cover
    del argv
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    run_stdio()


if __name__ == "__main__":  # pragma: no cover
    entrypoint()


__all__ = ["entrypoint", "run_stdio"]
