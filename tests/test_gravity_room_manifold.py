from nepsis.manifolds import GravityRoomManifold


def test_gravity_room_falls_to_floor():
    mf = GravityRoomManifold()
    triage = mf.triage("[[0,0,0],[0,1,0],[0,0,0],[2,2,2]]", context="gravity")
    projection = mf.project(triage)
    # Candidate grid with object resting just above floor after fall
    candidate = [[0, 0, 0], [0, 0, 0], [0, 1, 0], [2, 2, 2]]
    result = mf.validate(projection, candidate)
    assert result.outcome == "SUCCESS"
    assert result.metrics["red_violations"] == []
    assert result.metrics["blue_score"] == 1.0


def test_gravity_room_rejects_clipping():
    mf = GravityRoomManifold()
    triage = mf.triage("[[0,0,0],[0,1,0],[0,0,0],[2,2,2]]", context="gravity")
    projection = mf.project(triage)
    # Candidate grid with object inside the floor (clipping)
    candidate = [[0, 0, 0], [0, 0, 0], [0, 0, 0], [2, 1, 2]]
    result = mf.validate(projection, candidate)
    assert result.outcome == "REJECTED"
    assert result.metrics["red_violations"]
