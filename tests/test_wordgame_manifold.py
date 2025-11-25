from nepsis.manifolds import WordGameManifold


def test_wordgame_rejects_overuse():
    manifold = WordGameManifold()
    triage = manifold.triage("JANIGLL", context="test")
    projection = manifold.project(triage)

    validation = manifold.validate(projection, "JINGLES")
    assert validation.outcome == "REJECTED"
    assert validation.metrics["red_violations"]
    assert validation.repair and validation.repair.get("needed")


def test_wordgame_accepts_valid_candidate():
    manifold = WordGameManifold()
    triage = manifold.triage("JANIGLL", context="test")
    projection = manifold.project(triage)

    validation = manifold.validate(projection, "JINGALL")
    assert validation.outcome == "SUCCESS"
    assert validation.metrics["red_violations"] == []
    assert not validation.repair.get("needed")
