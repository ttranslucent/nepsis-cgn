from __future__ import annotations

import os
from pathlib import Path

_FALSEY_ENV_VALUES = {"0", "false", "no", "off"}
_SERVERLESS_ENV_FLAGS = (
    "VERCEL",
    "AWS_LAMBDA_FUNCTION_NAME",
    "AWS_EXECUTION_ENV",
)


def is_serverless_runtime() -> bool:
    return any(_env_flag_enabled(name) for name in _SERVERLESS_ENV_FLAGS)


def serverless_runtime_sessions_path(filename: str) -> Path:
    if not filename or Path(filename).name != filename:
        raise ValueError("runtime session filename must be a bare filename")
    tmp_root = os.getenv("TMPDIR", "").strip() or "/tmp"
    return Path(tmp_root).expanduser().resolve() / "nepsis-cgn" / "sessions" / filename


def _env_flag_enabled(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return bool(value) and value not in _FALSEY_ENV_VALUES
