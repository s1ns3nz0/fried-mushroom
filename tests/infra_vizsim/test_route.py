"""Tests for route.py — METT+TC route generator (corridor lat/lon -> normalized
plane waypoints with terrain-aware altitude and stealth/timeliness biased
midpoints)."""
import copy
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))       # vizsim 패키지
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vizsim import route  # noqa: E402
from vizsim import terrain  # noqa: E402

BRIEF_PATH = Path(__file__).resolve().parents[2] / "examples" / "mission_brief_t3.json"


def _load_t3_brief():
    with open(BRIEF_PATH) as f:
        return json.load(f)


def test_to_norm_to_geo_round_trip():
    brief = _load_t3_brief()
    bbox = route.compute_bbox(brief["corridor"]["waypoints"])
    for wp in brief["corridor"]["waypoints"]:
        x, y = route.to_norm(wp["lat"], wp["lon"], bbox)
        lat, lon = route.to_geo(x, y, bbox)
        assert abs(lat - wp["lat"]) < 1e-9
        assert abs(lon - wp["lon"]) < 1e-9


def test_generate_route_waypoints_within_unit_square():
    brief = _load_t3_brief()
    result = route.generate_route(brief)
    for wp in result["waypoints"]:
        assert 0.0 <= wp["x"] <= 1.0
        assert 0.0 <= wp["y"] <= 1.0


def test_generate_route_alt_clears_terrain():
    brief = _load_t3_brief()
    result = route.generate_route(brief)
    for wp in result["waypoints"]:
        elev = terrain.elev_m(terrain.height_at(wp["x"], wp["y"]))
        assert wp["alt_m"] > elev


def test_generate_route_has_at_least_three_waypoints():
    brief = _load_t3_brief()
    result = route.generate_route(brief)
    assert len(result["waypoints"]) >= 3


def test_generate_route_stealth_route_has_lower_avg_alt_than_timeliness_route():
    stealth_brief = _load_t3_brief()  # weights.stealth = 0.40 (dominant)

    timeliness_brief = copy.deepcopy(stealth_brief)
    timeliness_brief["weights"]["stealth"] = 0.05
    timeliness_brief["weights"]["timeliness"] = 0.40

    stealth_route = route.generate_route(stealth_brief)
    timeliness_route = route.generate_route(timeliness_brief)

    def _avg_alt(r):
        wps = r["waypoints"]
        return sum(wp["alt_m"] for wp in wps) / len(wps)

    assert _avg_alt(stealth_route) < _avg_alt(timeliness_route)


def test_generate_route_avoids_enemy_zone():
    brief = _load_t3_brief()
    mid = route.generate_route(brief)["waypoints"][1]
    enemy = {"x": mid["x"], "y": mid["y"], "radius": 0.08, "kind": "sam"}

    result = route.generate_route(brief, enemies=[enemy])

    min_dist = enemy["radius"] + route.ENEMY_AVOID_MARGIN
    for wp in result["waypoints"]:
        dist = math.hypot(wp["x"] - enemy["x"], wp["y"] - enemy["y"])
        assert dist >= min_dist


def test_route_segments_do_not_cross_enemy():
    brief = _load_t3_brief()
    base = route.generate_route(brief)["waypoints"]

    # Pick the longest segment so both endpoints sit outside the keep-out,
    # then place the enemy exactly on the segment midpoint.
    seg = max(
        range(len(base) - 1),
        key=lambda i: math.hypot(
            base[i + 1]["x"] - base[i]["x"], base[i + 1]["y"] - base[i]["y"]
        ),
    )
    a, b = base[seg], base[seg + 1]
    enemy = {
        "x": (a["x"] + b["x"]) / 2.0,
        "y": (a["y"] + b["y"]) / 2.0,
        "radius": 0.06,
        "kind": "sam",
    }

    result = route.generate_route(brief, enemies=[enemy])["waypoints"]

    keep_out = enemy["radius"] + route.ENEMY_AVOID_MARGIN
    for p, q in zip(result, result[1:]):
        dist = route._point_segment_dist(
            enemy["x"], enemy["y"], p["x"], p["y"], q["x"], q["y"]
        )
        assert dist >= keep_out


def test_generate_route_no_enemies_matches_default():
    brief = _load_t3_brief()
    baseline = route.generate_route(brief)
    assert route.generate_route(brief, enemies=None) == baseline
    assert route.generate_route(brief, enemies=[]) == baseline


def test_generate_route_with_enemies_is_deterministic():
    brief = _load_t3_brief()
    enemies = [{"x": 0.4, "y": 0.6, "radius": 0.05}]
    first = route.generate_route(brief, enemies=enemies)
    second = route.generate_route(brief, enemies=enemies)
    assert first == second
