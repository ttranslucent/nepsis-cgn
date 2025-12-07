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
