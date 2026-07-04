"""Regression tests for #255 (post-#252 P2 fixes in runner.build_scenario).

Covers:
  1. C4I list-form pos ([lat, lon]) must not crash build_scenario — the
     canonical C4I enemy_track shape uses pos as a 2-element list, not a
     {"lat","lon"} dict. Pre-fix this raised TypeError on `pos["lat"]`.
  2. When avoidance changes the route's arc length (total_s != total0),
     popup enemies must be rebuilt on the FINAL route/events so they stay
     consistent with what's actually returned (and injected into World) —
     not stranded on the discarded pre-avoidance rt0/evs0 scale.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))       # vizsim 패키지
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vizsim import events as events_module  # noqa: E402
from vizsim import path  # noqa: E402
from vizsim import route  # noqa: E402
from vizsim import runner  # noqa: E402

BRIEF_PATH = Path(__file__).resolve().parents[2] / "examples" / "mission_brief_t3.json"

EPS = 1e-9


def _load_brief() -> dict:
    return json.loads(BRIEF_PATH.read_text(encoding="utf-8"))


def _scenario_with_avoidance_length_change(brief: dict) -> dict:
    """Find a seed whose briefed-enemy avoidance actually changes the route's
    arc length (total_s != total0) — that's the condition P2-2 depends on.
    Seed 0 is known to trigger it for mission_brief_t3.json; fall back to a
    deterministic scan if the fixture/algorithm ever changes."""
    for seed in range(30):
        rt0 = route.generate_route(brief)
        total0 = path.total_length(rt0["waypoints"])
        scenario = runner.build_scenario(seed, brief)
        if scenario["enemies"] and abs(scenario["total_s"] - total0) > EPS:
            return scenario
    raise AssertionError("no seed in 0..30 produced an avoidance-driven route length change")


def test_c4i_list_form_pos_does_not_crash():
    # C4I canonical shape: pos is a 2-element [lat, lon] list, not a dict.
    brief = _load_brief()
    bbox = route.compute_bbox(brief["corridor"]["waypoints"])
    track = {
        "id": "E9",
        "kind": "T3_ambush",
        "pos": [37.55, 127.05],
        "radius_m": 300.0,
        "confidence": 0.85,
    }

    scenario = runner.build_scenario(0, brief, enemy_tracks=[track])

    briefed = scenario["enemies"]
    assert len(briefed) == 1
    x, y = route.to_norm(37.55, 127.05, bbox)
    assert abs(briefed[0]["x"] - x) <= EPS
    assert abs(briefed[0]["y"] - y) <= EPS
    assert briefed[0]["briefed"] is True
    assert briefed[0]["id"] == "E9"


def test_popup_enemies_match_final_route_and_events_after_avoidance():
    brief = _load_brief()
    scenario = _scenario_with_avoidance_length_change(brief)

    # Oracle: rebuild enemies directly from what the scenario actually
    # returns (route + events) — this must be the true source for popup
    # enemies, not the pre-avoidance rt0/evs0 the route generator discarded.
    rt = scenario["route"]
    evs = scenario["events"]
    all_final = runner.build_enemies(rt["waypoints"], evs, None)
    _briefed_ignored, expected_popup = runner.split_enemies(all_final)

    assert scenario["popup_enemies"] == expected_popup
    assert scenario["all_enemies"] == scenario["enemies"] + scenario["popup_enemies"]
