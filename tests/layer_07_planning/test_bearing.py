import math

import pytest

from onboard.layer_07_planning.bearing import compute_bearing
from onboard.run import _compute_terrain_bearings


def test_physical_with_bearing():
    assert compute_bearing("PHYSICAL", 45.0, {}) == (225.0, "threat_reverse(channel)")


def test_physical_bearing_wraparound():
    assert compute_bearing("PHYSICAL", 270.0, {}) == (90.0, "threat_reverse(channel)")


def test_physical_no_bearing_fallback():
    ctx = {"lowest_exposure_bearing_deg": 90}
    assert compute_bearing("PHYSICAL", None, ctx) == (90, "terrain_fallback")


def test_remote_with_bearing():
    bearing, anchor = compute_bearing("REMOTE", 45.0, {})
    assert bearing == 225.0
    assert anchor == "threat_reverse(channel)"


def test_remote_with_bearing_wraparound():
    bearing, anchor = compute_bearing("REMOTE", 270.0, {})
    assert bearing == 90.0
    assert anchor == "threat_reverse(channel)"


def test_remote_no_bearing():
    bearing, anchor = compute_bearing("REMOTE", None, {})
    assert bearing is None
    assert anchor == "last_known_good_position"


def test_remote_no_bearing_ctx_ignored():
    ctx = {"lowest_exposure_bearing_deg": 90, "optimal_terrain_bearing_deg": 180}
    bearing, anchor = compute_bearing("REMOTE", None, ctx)
    assert bearing is None
    assert anchor == "last_known_good_position"


def test_navigation():
    ctx = {"optimal_terrain_bearing_deg": 180}
    assert compute_bearing("NAVIGATION", None, ctx) == (180, "optimal_terrain")


def test_none_category():
    assert compute_bearing(None, None, {}) == (None, None)


def test_terrain_bearing_rounded_for_cross_python_portability():
    """_compute_terrain_bearings 반환값은 소수 6자리로 반올림돼야 한다.

    math.atan2/cos 의 마지막 ULP 는 libm(Python/플랫폼) 버전마다 다르다.
    풀정밀 float 을 골든에 박으면 CI(3.11) vs 로컬(3.13) 이 어긋난다.
    6자리 반올림(≈0.1m 손실)으로 이식성 확보.
    """
    mb = {
        "corridor": {
            "waypoints": [
                {"lat": 37.5, "lon": 127.0},
                {"lat": 37.6, "lon": 127.1},
            ]
        }
    }
    result = _compute_terrain_bearings(mb)
    optimal = result["optimal_terrain_bearing_deg"]
    lowest = result["lowest_exposure_bearing_deg"]

    assert optimal == round(optimal, 6), "optimal_terrain_bearing_deg 는 6자리 이하여야 한다"
    assert lowest == round(lowest, 6), "lowest_exposure_bearing_deg 는 6자리 이하여야 한다"
    # 값이 0이 아닌 실수여야 한다 (waypoints 2개 이상이므로)
    assert optimal != 0.0
    assert lowest != 0.0
