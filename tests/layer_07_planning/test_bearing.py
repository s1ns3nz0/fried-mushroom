from onboard.layer_07_planning.bearing import compute_bearing


def test_physical_with_bearing():
    assert compute_bearing("PHYSICAL", 45.0, {}) == (225.0, "threat_reverse(channel)")


def test_physical_bearing_wraparound():
    assert compute_bearing("PHYSICAL", 270.0, {}) == (90.0, "threat_reverse(channel)")


def test_physical_no_bearing_fallback():
    ctx = {"lowest_exposure_bearing_deg": 90}
    assert compute_bearing("PHYSICAL", None, ctx) == (90, "terrain_fallback")


def test_remote_with_bearing():
    assert compute_bearing("REMOTE", 45.0, {}) == (225.0, "threat_reverse(channel)")


def test_remote_no_bearing():
    assert compute_bearing("REMOTE", None, {}) == (None, "last_known_good_position")


def test_navigation():
    ctx = {"optimal_terrain_bearing_deg": 180}
    assert compute_bearing("NAVIGATION", None, ctx) == (180, "optimal_terrain")


def test_none_category():
    assert compute_bearing(None, None, {}) == (None, None)
