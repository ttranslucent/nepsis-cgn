from __future__ import annotations

import json

from nepsis_cgn.cli.main import main


def test_cli_puzzle_json(capsys) -> None:
    code = main(["--json", "puzzle", "--letters", "JAIILUNG", "--candidate", "JAILING"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["manifold"] in {"strict_set", "phonetic_variant"}
    assert "decision" in payload
    assert "tension" in payload


def test_cli_safety_json(capsys) -> None:
    code = main(["--json", "safety", "--critical-signal"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["manifold"] in {"blue_channel", "red_channel"}
    assert "decision" in payload
    assert "tension" in payload


def test_cli_safety_json_with_governance(capsys) -> None:
    code = main(["--json", "--c-fp", "1", "--c-fn", "9", "safety", "--critical-signal"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert "governance" in payload
    assert payload["governance"]["warning_level"] in {"green", "yellow", "red"}
    assert "theta" in payload["governance"]
    assert "stage" in payload
    assert payload["stage"] == "evaluated"
    assert payload["stage_events"] == ["CALL", "REPORT", "EVALUATE"]


def test_cli_requires_both_governance_costs() -> None:
    try:
        main(["--json", "--c-fp", "1", "safety", "--critical-signal"])
    except ValueError as exc:
        assert "Both --c-fp and --c-fn" in str(exc)
    else:
        raise AssertionError("Expected ValueError when only one governance cost is provided.")


def test_cli_can_emit_iteration_packet(capsys) -> None:
    code = main(["--json", "--emit-packet", "safety", "--critical-signal"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert "iteration_packet" in payload
    packet = payload["iteration_packet"]
    assert packet["schema_id"] == "nepsis.iteration_packet"
    assert packet["meta"]["iteration"] == 0
    assert packet["meta"]["parent_packet_id"] is None
    assert packet["stage"] == "evaluated"


def test_cli_can_emit_committed_stage(capsys) -> None:
    code = main(["--json", "--emit-packet", "--commit", "safety", "--critical-signal"])
    assert code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    packet = payload["iteration_packet"]
    assert packet["stage"] == "committed"
    assert packet["stage_events"] == ["CALL", "REPORT", "EVALUATE", "COMMIT"]


def test_cli_continue_override_requires_reason() -> None:
    try:
        main(["--json", "--c-fp", "1", "--c-fn", "9", "--continue-override", "safety", "--critical-signal"])
    except ValueError as exc:
        assert "--override-reason is required" in str(exc)
    else:
        raise AssertionError("Expected ValueError when --continue-override has no reason.")


def test_cli_writes_iteration_packet_to_directory(tmp_path, capsys) -> None:
    packet_dir = tmp_path / "packets"
    code = main(
        [
            "--json",
            "--packet-dir",
            str(packet_dir),
            "safety",
            "--critical-signal",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert "iteration_packet_path" in payload
    packet_path = payload["iteration_packet_path"]
    assert packet_path.endswith(".json")
    assert packet_dir.exists()
    files = list(packet_dir.glob("*.json"))
    assert len(files) == 1
