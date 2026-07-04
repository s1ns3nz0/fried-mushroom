"""Tests for pre-input enemy positions (enemy_tracks) flowing into build_scenario.

Covers:
  1. examples/set_mission_recon.json carries exactly 2 enemy_tracks with
     lat/lon/radius_m.
  2. build_scenario(seed, brief, enemy_tracks=...) uses the tracks as the
     BRIEFED enemies at their exact geo->norm positions (briefed=True) and
     demotes ALL seed-derived enemies to popups.
  3. The route keeps out of the briefed tracks' keep-out radii — checked
     segment-aware (every route segment, not just waypoints).
  4. Determinism: same args twice yields identical output.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

# Mirror runner.py's sys.path setup: repo src/ (onboard), infra/log/
# (pipeline_feeder) and infra/sim/ (flat sim modules) importable regardless
# of how this test is invoked.
_SIM_DIR = Path(__file__).resolve().parent
_INFRA_DIR = _SIM_DIR.parent
_REPO = _INFRA_DIR.parent
_SRC = _REPO / "src"

for _path in (_REPO / "infra" / "sim", _REPO / "infra" / "log", _SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import route  # noqa: E402
import runner  # noqa: E402
import world  # noqa: E402

BRIEF_PATH = _INFRA_DIR.parent / "examples" / "mission_brief_t3.json"
SET_MISSION_PATH = _INFRA_DIR.parent / "examples" / "set_mission_recon.json"

# Float tolerance: avoidance pushes a point to exactly keep_out distance,
# so the measured distance can undershoot by a few ULPs.
EPS = 1e-9


def _load_brief() -> dict:
    return json.loads(BRIEF_PATH.read_text(encoding="utf-8"))


def _load_tracks() -> list[dict]:
    return json.loads(SET_MISSION_PATH.read_text(encoding="utf-8"))["enemy_tracks"]


def test_set_mission_recon_has_two_enemy_tracks():
    tracks = _load_tracks()
    assert len(tracks) == 2
    for trk in tracks:
        assert "lat" in trk and "lon" in trk and "radius_m" in trk


def test_enemy_tracks_become_briefed_enemies_at_exact_positions():
    brief = _load_brief()
    tracks = _load_tracks()
    scenario = runner.build_scenario(0, brief, enemy_tracks=tracks)
    briefed = scenario["enemies"]
    assert len(briefed) == 2

    bbox = route.compute_bbox(brief["corridor"]["waypoints"])
    for trk, enemy in zip(tracks, briefed):
        x, y = route.to_norm(trk["lat"], trk["lon"], bbox)
        assert abs(enemy["x"] - x) <= EPS
        assert abs(enemy["y"] - y) <= EPS
        assert enemy["briefed"] is True
        assert enemy["id"] == trk["id"]
        assert enemy["kind"] == trk["kind"]
        assert abs(enemy["radius"] - trk["radius_m"] / world.MAP_EXTENT_M) <= EPS

    popup = scenario["popup_enemies"]
    assert len(popup) >= 1
    for e in popup:
        assert not e.get("briefed")
    assert scenario["all_enemies"] == briefed + popup


def test_route_keeps_out_of_briefed_track_radii_segment_aware():
    brief = _load_brief()
    tracks = _load_tracks()
    scenario = runner.build_scenario(0, brief, enemy_tracks=tracks)
    enemies = scenario["enemies"]
    assert enemies, "scenario must have briefed enemies for the avoidance check"

    waypoints = scenario["route"]["waypoints"]
    interior = waypoints[1:-1]
    for wp in interior:
        for enemy in enemies:
            dist = math.hypot(wp["x"] - enemy["x"], wp["y"] - enemy["y"])
            keep_out = enemy["radius"] + route.ENEMY_AVOID_MARGIN
            assert dist >= keep_out - EPS, (
                f"waypoint ({wp['x']:.4f},{wp['y']:.4f}) inside keep-out of "
                f"{enemy['kind']} at ({enemy['x']:.4f},{enemy['y']:.4f})"
            )
    # Segment-aware: every route segment must also clear every keep-out circle.
    for a, b in zip(waypoints, waypoints[1:]):
        for enemy in enemies:
            dist = route._point_segment_dist(
                enemy["x"], enemy["y"], a["x"], a["y"], b["x"], b["y"]
            )
            keep_out = enemy["radius"] + route.ENEMY_AVOID_MARGIN
            assert dist >= keep_out - EPS, (
                f"segment ({a['x']:.4f},{a['y']:.4f})->({b['x']:.4f},{b['y']:.4f}) "
                f"clips keep-out of {enemy['kind']} at "
                f"({enemy['x']:.4f},{enemy['y']:.4f})"
            )


def test_build_scenario_with_tracks_is_deterministic():
    brief = _load_brief()
    tracks = _load_tracks()
    s1 = runner.build_scenario(0, brief, enemy_tracks=tracks)
    s2 = runner.build_scenario(0, brief, enemy_tracks=tracks)
    assert s1 == s2


def test_c4i_canonical_track_shape_is_accepted():
    """C4I/B-1 canonical enemy_tracks entries use track_id/pos/radius (#195/#219),
    not the flat dashboard id/lat/lon/radius_m shape. Both must work."""
    brief = _load_brief()
    track = {
        "track_id": "trk-9",
        "kind": "T3",
        "pos": {"lat": 37.508, "lon": 127.006},
        "radius": 40,
    }
    scenario = runner.build_scenario(0, brief, enemy_tracks=[track])
    briefed = scenario["enemies"]
    assert len(briefed) == 1
    enemy = briefed[0]
    assert enemy["id"] == "trk-9"
    assert abs(enemy["radius"] - 40 / world.MAP_EXTENT_M) <= EPS


def test_flat_radius_m_wins_over_radius_when_both_present():
    brief = _load_brief()
    track = {
        "id": "trk-10",
        "kind": "T3",
        "lat": 37.508,
        "lon": 127.006,
        "radius_m": 260,
        "radius": 999,
        "confidence": 0.9,
    }
    scenario = runner.build_scenario(0, brief, enemy_tracks=[track])
    enemy = scenario["enemies"][0]
    assert abs(enemy["radius"] - 260 / world.MAP_EXTENT_M) <= EPS
