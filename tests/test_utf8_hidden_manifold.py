from nepsis.manifolds import UTF8HiddenManifold


def test_utf8_hidden_rejects_missing_marker():
    manifold = UTF8HiddenManifold(target_phrase="TEST")
    triage = manifold.triage("TEST", context="test")
    projection = manifold.project(triage)

    validation = manifold.validate(projection, "TEST")
    assert validation.outcome == "REJECTED"
    assert validation.metrics["red_violations"]


def test_utf8_hidden_accepts_with_marker():
    manifold = UTF8HiddenManifold(target_phrase="TEST")
    triage = manifold.triage("TEST", context="test")
    projection = manifold.project(triage)

    candidate = "TEST\u200b"
    validation = manifold.validate(projection, candidate)
    assert validation.outcome == "SUCCESS"
    assert validation.metrics["red_violations"] == []
