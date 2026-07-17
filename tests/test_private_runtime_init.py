from __future__ import annotations

import json
from pathlib import Path
import re
import shlex
import shutil
import stat
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
import pytest

from nepsis_cgn.canonical_runs import private_runtime_init
from nepsis_cgn.canonical_runs.private_runtime import (
    build_private_runtime_app,
    load_private_runtime_settings,
)
from nepsis_cgn.canonical_runs.private_runtime_init import (
    PrivateRuntimeInitializationError,
    initialize_private_runtime,
)
from nepsis_cgn.canonical_runs.trust_anchor_registry import (
    ReceiptTrustAnchorRegistry,
)
from nepsis_cgn.contracts.canonical_json import canonical_json


@pytest.fixture
def durable_parent() -> Path:
    parent = Path.home() / ".nepsis" / "pytest-private-runtime-init" / uuid.uuid4().hex
    parent.mkdir(parents=True, mode=0o700, exist_ok=False)
    try:
        yield parent
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def test_initializer_writes_canonical_private_state_with_required_modes(
    durable_parent: Path,
) -> None:
    root = durable_parent / "runtime state"
    result = initialize_private_runtime(
        root,
        bind_host="127.0.0.1",
        port=18789,
        profile_id="profile-local",
    )

    assert result.state_root == root.resolve()
    assert _mode(root) == 0o700
    for protected_name in (
        "canonical-runs.sqlite",
        "governance-profiles.sqlite",
        "receipt-trust-anchor.sqlite",
        "receipt-signing-key.pem",
        "receipt-trust-anchor.json",
        "cgn-runtime.env",
        "mc-profile.env",
    ):
        assert _mode(root / protected_name) == 0o600

    private_key = serialization.load_pem_private_key(
        (root / "receipt-signing-key.pem").read_bytes(), password=None
    )
    assert isinstance(private_key, Ed25519PrivateKey)
    assert (
        (root / "receipt-signing-key.pem")
        .read_bytes()
        .startswith(b"-----BEGIN PRIVATE KEY-----")
    )

    raw_anchor = (root / "receipt-trust-anchor.json").read_text("utf-8")
    anchor = json.loads(raw_anchor)
    assert raw_anchor == canonical_json(anchor)
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z",
        anchor["activated_at"],
    )
    assert "private" not in anchor

    runtime_environment = _read_environment(root / "cgn-runtime.env")
    assert runtime_environment["NEPSIS_CANONICAL_RUNS_ENABLED"] == "1"
    assert runtime_environment["NEPSIS_CANONICAL_RUNS_BIND_HOST"] == "127.0.0.1"
    assert runtime_environment["NEPSIS_CANONICAL_RUNS_PORT"] == "18789"
    assert (
        runtime_environment["NEPSIS_CANONICAL_RUNS_SIGNING_KEY_ACTIVATED_AT"]
        == anchor["activated_at"]
    )
    assert runtime_environment["NEPSIS_CANONICAL_RUNS_STORE_PATH"] == str(
        root / "canonical-runs.sqlite"
    )

    tokens = {
        runtime_environment["NEPSIS_CANONICAL_RUNS_MODEL_TOKEN"],
        runtime_environment["NEPSIS_CANONICAL_RUNS_OPERATOR_TOKEN"],
        runtime_environment["NEPSIS_CANONICAL_RUNS_PROFILE_TOKEN"],
        runtime_environment["NEPSIS_CANONICAL_RUNS_VALIDATOR_TOKEN"],
    }
    assert len(tokens) == 4
    assert all(re.fullmatch(r"[0-9a-f]{64}", token) for token in tokens)

    mc_environment = _read_environment(root / "mc-profile.env")
    assert set(mc_environment) == {
        "NEPSISMC_RUNTIME_MODE",
        "NEPSISMC_CGN_PROFILE_BASE_URL",
        "NEPSISMC_CGN_PROFILE_ID",
        "NEPSISMC_CGN_PROFILE_OPERATOR_TOKEN",
    }
    assert mc_environment == {
        "NEPSISMC_RUNTIME_MODE": "legacy",
        "NEPSISMC_CGN_PROFILE_BASE_URL": "http://127.0.0.1:18789",
        "NEPSISMC_CGN_PROFILE_ID": "profile-local",
        "NEPSISMC_CGN_PROFILE_OPERATOR_TOKEN": runtime_environment[
            "NEPSIS_CANONICAL_RUNS_PROFILE_TOKEN"
        ],
    }
    assert (
        mc_environment["NEPSISMC_CGN_PROFILE_OPERATOR_TOKEN"]
        != runtime_environment["NEPSIS_CANONICAL_RUNS_OPERATOR_TOKEN"]
    )


def test_initialized_runtime_validates_opens_and_restarts(
    durable_parent: Path,
) -> None:
    root = durable_parent / "runtime"
    initialize_private_runtime(root)
    environment = _read_environment(root / "cgn-runtime.env")
    settings = load_private_runtime_settings(environment)

    first = build_private_runtime_app(settings)
    with TestClient(first) as http:
        assert http.get("/v1/mvp").status_code == 404
        assert http.get("/openapi.json").status_code == 404
    first.state.receipt_trust_anchor_registry.close()

    second = build_private_runtime_app(settings)
    with TestClient(second) as http:
        assert http.get("/v1/operator-runs/missing/snapshot").status_code == 401
    second.state.receipt_trust_anchor_registry.close()

    registry = ReceiptTrustAnchorRegistry.open_existing(
        root / "receipt-trust-anchor.sqlite"
    )
    assert registry.export_ledger()["status"] == "active"
    assert len(registry.export_ledger()["events"]) == 1
    registry.close()


def test_cli_prints_only_nonsecret_paths_and_status(
    durable_parent: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = durable_parent / "runtime"
    private_runtime_init.main(["--state-root", str(root)])
    captured = capsys.readouterr()
    runtime_environment = _read_environment(root / "cgn-runtime.env")

    assert str(root) in captured.out
    assert "status: active" in captured.out
    assert captured.err == ""
    for name in (
        "NEPSIS_CANONICAL_RUNS_MODEL_TOKEN",
        "NEPSIS_CANONICAL_RUNS_OPERATOR_TOKEN",
        "NEPSIS_CANONICAL_RUNS_PROFILE_TOKEN",
        "NEPSIS_CANONICAL_RUNS_VALIDATOR_TOKEN",
    ):
        assert runtime_environment[name] not in captured.out


def test_initializer_refuses_existing_empty_and_partial_targets_without_change(
    durable_parent: Path,
) -> None:
    empty = durable_parent / "empty"
    empty.mkdir()
    partial = durable_parent / "partial"
    partial.mkdir()
    sentinel = partial / "sentinel.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    existing_file = durable_parent / "file"
    existing_file.write_text("preserve", encoding="utf-8")

    for target in (empty, partial, existing_file):
        with pytest.raises(PrivateRuntimeInitializationError, match="already exists"):
            initialize_private_runtime(target)

    assert empty.is_dir() and not list(empty.iterdir())
    assert sentinel.read_text("utf-8") == "preserve"
    assert existing_file.read_text("utf-8") == "preserve"


def test_initializer_refuses_relative_and_temporary_roots() -> None:
    with pytest.raises(PrivateRuntimeInitializationError, match="absolute"):
        initialize_private_runtime("relative/private-runtime")
    temporary = Path("/tmp") / f"nepsis-private-runtime-{uuid.uuid4().hex}"
    with pytest.raises(PrivateRuntimeInitializationError, match="temporary"):
        initialize_private_runtime(temporary)
    assert not temporary.exists()
    var_temporary = Path("/var/tmp") / f"nepsis-private-runtime-{uuid.uuid4().hex}"
    with pytest.raises(PrivateRuntimeInitializationError, match="temporary"):
        initialize_private_runtime(var_temporary)
    assert not var_temporary.exists()


def test_failed_initialization_cleans_only_the_root_it_created(
    durable_parent: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = durable_parent / "runtime"
    sibling = durable_parent / "preserve.txt"
    sibling.write_text("preserve", encoding="utf-8")

    def fail_open(_cls: object, path: Path) -> object:
        Path(f"{path}-journal").write_bytes(b"partial journal")
        raise RuntimeError("injected failure")

    monkeypatch.setattr(
        private_runtime_init.CanonicalRunStore,
        "open",
        classmethod(fail_open),
    )
    with pytest.raises(PrivateRuntimeInitializationError, match="failed"):
        initialize_private_runtime(root)

    assert not root.exists()
    assert sibling.read_text("utf-8") == "preserve"


def test_token_generation_retries_collisions(monkeypatch: pytest.MonkeyPatch) -> None:
    values = iter(["a" * 64, "a" * 64, "b" * 64, "c" * 64, "d" * 64])
    monkeypatch.setattr(
        private_runtime_init.secrets, "token_hex", lambda _size: next(values)
    )

    assert private_runtime_init._distinct_tokens() == (
        "a" * 64,
        "b" * 64,
        "c" * 64,
        "d" * 64,
    )


def _read_environment(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text("utf-8").splitlines():
        parsed = shlex.split(raw_line)
        assert len(parsed) == 1
        name, separator, value = parsed[0].partition("=")
        assert separator == "="
        values[name] = value
    return values


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)
