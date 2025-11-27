from nepsis.manifolds import Utf8StreamManifold


def test_utf8_stream_rejects_overlong():
    mf = Utf8StreamManifold()
    triage = mf.triage("check utf8", "")
    projection = mf.project(triage)
    bad_bytes = b"\xc0\xaf"  # overlong encoding for '/'
    result = mf.validate(projection, bad_bytes)
    assert result.outcome == "REJECTED"
    assert result.metrics["error_count"] > 0


def test_utf8_stream_accepts_valid_utf8():
    mf = Utf8StreamManifold()
    triage = mf.triage("check utf8", "")
    projection = mf.project(triage)
    good = "hello – world ✓"
    result = mf.validate(projection, good)
    assert result.outcome == "SUCCESS"
    assert result.metrics["error_count"] == 0
    assert result.metrics["blue_score"] == 1.0
