from nepsis.manifolds import SeedManifold


def test_seed_manifold_rejects_forbidden():
    manifold = SeedManifold()
    triage = manifold.triage("test", context="test")
    projection = manifold.project(triage)

    validation = manifold.validate(projection, "FORBID token present")
    assert validation.outcome == "REJECTED"
    assert validation.metrics["red_violations"]


def test_seed_manifold_accepts_ok():
    manifold = SeedManifold()
    triage = manifold.triage("test", context="test")
    projection = manifold.project(triage)

    validation = manifold.validate(projection, "OK")
    assert validation.outcome == "SUCCESS"
    assert validation.metrics["red_violations"] == []
    assert not validation.repair.get("needed")
