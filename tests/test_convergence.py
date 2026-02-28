from __future__ import annotations

from nepsis_cgn.core.convergence import explain_trigger_codes


def test_explain_trigger_codes_maps_known_code() -> None:
    reasons = explain_trigger_codes(["MARGIN_COLLAPSE"])
    assert len(reasons) == 1
    reason = reasons[0]
    assert reason.code == "MARGIN_COLLAPSE"
    assert "Top Margin" in reason.title


def test_explain_trigger_codes_fallback_for_unknown_code() -> None:
    reasons = explain_trigger_codes(["UNKNOWN_CODE"])
    assert len(reasons) == 1
    reason = reasons[0]
    assert reason.code == "UNKNOWN_CODE"
    assert reason.title == "Unmapped Trigger"
