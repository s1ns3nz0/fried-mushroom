"""Tests for world.py — World state evolution (tick/snapshot) driven by
route.py (arc-length path), events.py (seed-placed threat events), and a
mission brief's drone_profile.battery_pct.
"""
import sys
from pathlib import Path

# infra/sim (flat sim modules), infra/log (pipeline_feeder), src (onboard)
# on sys.path so bare imports resolve when run from tests/.
_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "infra" / "sim", _REPO / "infra" / "log", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import json  # noqa: E402
import os  # noqa: E402

import events  # noqa: E402
import path  # noqa: E402
import route  # noqa: E402
import world  # noqa: E402

BRIEF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "examples", "mission_brief_t3.json"
)


def _load_t3_brief():
    with open(BRIEF_PATH) as f:
        return json.load(f)


def _make_world():
    brief = _load_t3_brief()
    rt = route.generate_route(brief)
    from path import total_length

    evts = events.generate_events(42, total_length(rt["waypoints"]))
    return world.World(rt, evts, brief)


def test_tick_speed_invariance_small_steps_vs_one_big_step():
    w_small = _make_world()
    for _ in range(5):
        w_small.tick(0.2)

    w_big = _make_world()
    w_big.tick(1.0)

    assert abs(w_small.s - w_big.s) < 1e-9


def test_initial_battery_pct_from_t3_brief():
    w = _make_world()
    assert w.battery_pct == 65


def test_snapshot_has_all_expected_keys():
    w = _make_world()
    w.tick(1.0)
    snap = w.snapshot()
    expected_keys = {
        "seq",
        "ts_ms",
        "s",
        "phase",
        "x",
        "y",
        "alt_m",
        "terrain_m",
        "heading_deg",
        "speed_mps",
        "battery_pct",
        "active_events",
    }
    assert set(snap.keys()) == expected_keys


def test_tick_advances_seq_and_ts_ms():
    w = _make_world()
    w.tick(0.5)
    assert w.seq == 1
    assert w.ts_ms == 500


def test_tick_drains_battery():
    w = _make_world()
    initial_battery = w.battery_pct
    w.tick(1.0)
    assert w.battery_pct < initial_battery


def test_s_clamped_at_total_length():
    w = _make_world()
    w.tick(10_000.0)
    assert w.s <= w._total_length


def test_phase_switches_to_return_at_goal_and_s_decreases():
    w = _make_world()
    w.tick(10_000.0)
    assert w.phase == "return"
    assert w.s == w._total_length
    w.tick(1.0)
    assert w.s < w._total_length


def test_phase_switches_to_complete_at_start_and_s_stays_zero():
    w = _make_world()
    w.tick(10_000.0)
    w.tick(10_000.0)
    assert w.phase == "complete"
    assert w.s == 0.0
    w.tick(1.0)
    assert w.phase == "complete"
    assert w.s == 0.0


def test_snapshot_has_phase_key():
    w = _make_world()
    assert w.snapshot()["phase"] == "outbound"


def test_tick_with_command_none_matches_plain_tick():
    w_plain = _make_world()
    w_cmd = _make_world()
    for _ in range(5):
        w_plain.tick(1.0)
        w_cmd.tick(1.0, command=None)
    assert w_plain.snapshot() == w_cmd.snapshot()


def test_rtl_command_switches_outbound_to_return_immediately():
    w = _make_world()
    w.tick(1.0)
    assert w.phase == "outbound"
    w.tick(1.0, command={"flight_action": "RTL"})
    assert w.phase == "return"


def test_reroute_command_deviates_from_route_with_capped_offset():
    import math

    w = _make_world()
    cmd = {
        "flight_action": "REROUTE",
        "target_bearing_deg": 90.0,
        "speed_mode": "MAX",
    }
    for _ in range(20):
        w.tick(1.0, command=cmd)

    route_point = path.point_at_s(w.route["waypoints"], w.s)
    x, y = w.pos
    deviation = math.hypot(x - route_point["x"], y - route_point["y"])
    assert deviation > 0.0
    offset_norm = math.hypot(w.offset[0], w.offset[1])
    assert offset_norm <= 100.0 / world.MAP_EXTENT_M + 1e-9


def test_maintain_after_reroute_rejoins_route():
    import math

    w = _make_world()
    cmd = {
        "flight_action": "REROUTE",
        "target_bearing_deg": 90.0,
        "speed_mode": "MAX",
    }
    for _ in range(20):
        w.tick(1.0, command=cmd)
    norm_after_evade = math.hypot(w.offset[0], w.offset[1])
    assert norm_after_evade > 0.0

    for _ in range(20):
        w.tick(1.0, command={"flight_action": "MAINTAIN"})
    norm_after_rejoin = math.hypot(w.offset[0], w.offset[1])
    assert norm_after_rejoin < norm_after_evade
    assert norm_after_rejoin < 1e-9


def test_active_events_from_enemy_proximity():
    brief = _load_t3_brief()
    rt = route.generate_route(brief)
    total = path.total_length(rt["waypoints"])
    pt = path.point_at_s(rt["waypoints"], total * 0.5)
    enemy = {
        "type": "T3_ambush",
        "kind": "T3",
        "x": pt["x"],
        "y": pt["y"],
        "radius": 0.05,
        "confidence": 0.8,
        "s": total * 0.5,
    }
    w = world.World(rt, [], brief, enemies=[enemy])

    # At s=0 the drone is far from the mid-route enemy -> no injection.
    assert w.snapshot()["active_events"] == []

    seen = set()
    while w.phase == "outbound":
        w.tick(1.0)
        for e in w.snapshot()["active_events"]:
            seen.add(e["type"])
    assert "T3_ambush" in seen


def test_altitude_change_command_offsets_alt_by_delta():
    w = _make_world()
    cmd = {"flight_action": "ALTITUDE_CHANGE", "altitude_delta_m": 15.0}
    for _ in range(10):
        w.tick(1.0, command=cmd)

    route_point = path.point_at_s(w.route["waypoints"], w.s)
    assert abs(w.alt_m - (route_point["alt_m"] + 15.0)) < 1e-6
