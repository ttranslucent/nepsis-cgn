import json

from nepsis.manifolds import ArcAttachManifold


def test_arc_attach_accepts_valid_grid():
    payload = {
        "train": [{"input": [[0, 1], [0, 0]], "output": [[0, 0], [0, 1]]}],
        "test": [{"input": [[1, 0], [0, 0]]}],
    }
    raw = json.dumps(payload)
    mf = ArcAttachManifold()
    triage = mf.triage(raw, context="")
    assert triage.is_well_posed
    proj = mf.project(triage)
    # Candidate output: simple grid
    artifact = "[[0,0],[1,0]]"
    result = mf.validate(proj, artifact)
    assert result.outcome == "SUCCESS"
    assert result.metrics["red_violations"] == []
    assert result.metrics["blue_score"] == 1.0


def test_arc_attach_rejects_bad_json():
    payload = {
        "train": [{"input": [[0, 1], [0, 0]], "output": [[0, 0], [0, 1]]}],
        "test": [{"input": [[1, 0], [0, 0]]}],
    }
    raw = json.dumps(payload)
    mf = ArcAttachManifold()
    triage = mf.triage(raw, context="")
    proj = mf.project(triage)
    result = mf.validate(proj, "not json")
    assert result.outcome == "REJECTED"
    assert result.metrics["blue_score"] == 0.0
