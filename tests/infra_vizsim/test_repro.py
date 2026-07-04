"""Golden repro tests for runner.run_ticks (Plan TODO 14, 검증기준 3).

Covers:
  1. Determinism: run_ticks(42, ...) called twice yields identical results
     (double-run comparison, not a golden file — avoids float platform issues).
  2. Seed sensitivity (control): event placement differs between seeds.
  3. ts_ms is seq-derived (deterministic), not wall-clock.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))       # vizsim 패키지
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vizsim import events  # noqa: E402
from vizsim import path  # noqa: E402
from vizsim import route  # noqa: E402
from vizsim import runner  # noqa: E402

BRIEF_PATH = Path(__file__).resolve().parents[2] / "examples" / "mission_brief_t3.json"
N_TICKS = 20
DT = 1.0


def _load_brief() -> dict:
    return json.loads(BRIEF_PATH.read_text(encoding="utf-8"))


def _candidate_racs(result: dict) -> list:
    return [c["rac"] for c in result["risk"]["candidates"]]


def test_run_ticks_is_deterministic_for_same_seed():
    brief = _load_brief()
    run1 = runner.run_ticks(42, brief, N_TICKS, DT)
    run2 = runner.run_ticks(42, brief, N_TICKS, DT)

    assert len(run1) == len(run2) == N_TICKS
    for r1, r2 in zip(run1, run2):
        assert r1["s"] == r2["s"]
        assert r1["snapshot"]["x"] == r2["snapshot"]["x"]
        assert r1["snapshot"]["y"] == r2["snapshot"]["y"]
        assert r1["snapshot"]["alt_m"] == r2["snapshot"]["alt_m"]
        assert (
            r1["result"]["response"]["flight_action"]
            == r2["result"]["response"]["flight_action"]
        )
        assert _candidate_racs(r1["result"]) == _candidate_racs(r2["result"])


def test_ts_ms_is_seq_derived_not_wall_clock():
    brief = _load_brief()
    run1 = runner.run_ticks(42, brief, N_TICKS, DT)
    run2 = runner.run_ticks(42, brief, N_TICKS, DT)

    for r1, r2 in zip(run1, run2):
        assert r1["snapshot"]["ts_ms"] == r2["snapshot"]["ts_ms"]


def test_seed_changes_event_placement_control():
    brief = _load_brief()
    rt = route.generate_route(brief)
    total_s = path.total_length(rt["waypoints"])

    events_42 = events.generate_events(42, total_s)
    events_43 = events.generate_events(43, total_s)

    assert events_42 != events_43


def test_closed_loop_run_ticks_deterministic():
    brief = _load_brief()
    run1 = runner.run_ticks(42, brief, 40, 1.0)
    run2 = runner.run_ticks(42, brief, 40, 1.0)

    assert len(run1) == len(run2) == 40
    for r1, r2 in zip(run1, run2):
        assert r1["snapshot"]["x"] == r2["snapshot"]["x"]
        assert r1["snapshot"]["y"] == r2["snapshot"]["y"]
        assert r1["snapshot"]["alt_m"] == r2["snapshot"]["alt_m"]
        assert r1["snapshot"]["phase"] == r2["snapshot"]["phase"]
        assert (
            r1["flight_plan"]["flight_action"] == r2["flight_plan"]["flight_action"]
        )


def test_proximity_injection_fires_threat_during_enemy_pass():
    # Seed 0's T3 enemy sits on the outbound route; with proximity-driven
    # active_events the envelope must inject its sensor signals while the
    # drone is inside the radius, and onboard must detect T3 on those ticks.
    brief = _load_brief()
    records = runner.run_ticks(0, brief, 200, 1.0)

    hits = [
        rec
        for rec in records
        if rec["snapshot"]["active_events"]
        and (rec["result"]["threat"]["primary"] or {}).get("threat_event") == "T3"
    ]
    assert hits, "no tick had an enemy-proximity injection detected as a T3 primary"


def test_evasion_actually_bends_trajectory():
    brief = _load_brief()

    records = None
    first_non_maintain = None
    for seed in range(42, 61):
        candidate = runner.run_ticks(seed, brief, 40, 1.0)
        for i, rec in enumerate(candidate):
            if rec["flight_plan"]["flight_action"] != "MAINTAIN":
                records = candidate
                first_non_maintain = i
                break
        if records is not None:
            break
    assert records is not None, "no seed in 42..60 produced a non-MAINTAIN action"

    # run_ticks internally calls build_scenario(seed, brief); rebuild it to get
    # the identical deterministic route the run steered against.
    rt = runner.build_scenario(seed, brief)["route"]

    # Physical motion deviation vs. the pure route point at the same s.
    # Only REROUTE-type actions bend x/y; ALTITUDE_CHANGE bends alt_m —
    # both count as the command altering physical motion.
    max_dev = 0.0
    for rec in records[first_non_maintain + 1 :]:
        snap = rec["snapshot"]
        pt = path.point_at_s(rt["waypoints"], snap["s"])
        dev = math.hypot(
            snap["x"] - pt["x"], snap["y"] - pt["y"], snap["alt_m"] - pt["alt_m"]
        )
        max_dev = max(max_dev, dev)
    assert max_dev > 1e-6
