"""Tests for runner.build_scenario (enemies-first → avoidance route → re-anchored events).

Covers:
  1. Determinism: build_scenario(42, t3) called twice yields identical output.
  2. Enemy avoidance: every avoidance-governed waypoint of the returned route
     keeps >= enemy.radius + route.ENEMY_AVOID_MARGIN distance from every
     BRIEFED enemy ("enemies" key — popup enemies are unknown pre-mission and
     are not avoided). Route endpoints are excluded — route._avoid_enemies
     only adjusts interior points (mission-anchored start/end stay fixed).
  3. Briefed/popup split: "enemies" holds at most BRIEFED_ENEMY_COUNT briefed
     enemies and briefed + popup partition all_enemies.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))       # vizsim 패키지
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vizsim import route  # noqa: E402
from vizsim import runner  # noqa: E402

BRIEF_PATH = Path(__file__).resolve().parents[2] / "examples" / "mission_brief_t3.json"

# Float tolerance: _avoid_enemies pushes a point to exactly keep_out distance,
# so the measured distance can undershoot by a few ULPs.
EPS = 1e-9


def _load_brief() -> dict:
    return json.loads(BRIEF_PATH.read_text(encoding="utf-8"))


def _scenario_with_enemies(brief: dict) -> dict:
    """Seed 42 has events (and thus enemies); fall back to a deterministic
    scan of 0..10 for the first seed with enemies if that ever changes."""
    scenario = runner.build_scenario(42, brief)
    if scenario["enemies"]:
        return scenario
    for seed in range(11):
        scenario = runner.build_scenario(seed, brief)
        if scenario["enemies"]:
            return scenario
    raise AssertionError("no seed in {42} ∪ 0..10 produced enemies")


def test_build_scenario_is_deterministic_for_same_seed():
    brief = _load_brief()
    s1 = runner.build_scenario(42, brief)
    s2 = runner.build_scenario(42, brief)
    assert s1 == s2
    assert set(s1.keys()) == {
        "bbox", "route", "events", "enemies", "popup_enemies", "all_enemies", "total_s",
    }


def test_enemies_split_into_briefed_and_popup():
    brief = _load_brief()
    scenario = _scenario_with_enemies(brief)
    briefed = scenario["enemies"]
    popup = scenario["popup_enemies"]
    assert len(briefed) <= runner.BRIEFED_ENEMY_COUNT
    # briefed + popup partition all_enemies, order preserved within each.
    assert len(briefed) + len(popup) == len(scenario["all_enemies"])
    for e in briefed:
        assert e in scenario["all_enemies"]
    for e in popup:
        assert e in scenario["all_enemies"] and e not in briefed


def test_route_waypoints_keep_out_of_enemy_radii():
    brief = _load_brief()
    scenario = _scenario_with_enemies(brief)
    enemies = scenario["enemies"]
    assert enemies, "scenario must have enemies for the avoidance check"

    interior = scenario["route"]["waypoints"][1:-1]
    for wp in interior:
        for enemy in enemies:
            dist = math.hypot(wp["x"] - enemy["x"], wp["y"] - enemy["y"])
            keep_out = enemy["radius"] + route.ENEMY_AVOID_MARGIN
            assert dist >= keep_out - EPS, (
                f"waypoint ({wp['x']:.4f},{wp['y']:.4f}) inside keep-out of "
                f"{enemy['type']} at ({enemy['x']:.4f},{enemy['y']:.4f})"
            )
