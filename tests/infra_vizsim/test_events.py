"""Tests for seed-based event pre-placement (events.py).

Events are bound to arc-length position s (no tick/time/dt concept).
generate_events must be fully deterministic given (seed, total_s).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))       # vizsim 패키지
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vizsim import events  # noqa: E402


def test_generate_events_deterministic_same_seed():
    assert events.generate_events(42, 1.7) == events.generate_events(42, 1.7)


def test_generate_events_differs_with_different_seed():
    assert events.generate_events(42, 1.7) != events.generate_events(43, 1.7)


def test_generate_events_bounds_within_total_s():
    total_s = 1.7
    result = events.generate_events(42, total_s)
    assert len(result) > 0
    for event in result:
        assert 0 <= event["s_start"] <= event["s_end"] <= total_s


def test_generate_events_valid_types():
    result = events.generate_events(42, 1.7)
    valid_types = {"T1_jamming", "T2_link_degrade", "T3_ambush", "T4_capture", "T7_obstacle"}
    for event in result:
        assert event["type"] in valid_types


def test_generate_events_point_events_have_equal_start_end():
    result = events.generate_events(42, 1.7)
    point_types = {"T3_ambush", "T4_capture", "T7_obstacle"}
    for event in result:
        if event["type"] in point_types:
            assert event["s_start"] == event["s_end"]


def test_generate_events_sorted_by_s_start():
    result = events.generate_events(42, 1.7)
    s_starts = [event["s_start"] for event in result]
    assert s_starts == sorted(s_starts)


def test_generate_events_shape():
    result = events.generate_events(42, 1.7)
    for event in result:
        assert set(event.keys()) == {"type", "s_start", "s_end", "params"}
        assert isinstance(event["params"], dict)


def test_active_events_returns_containing_zone():
    zone_event = {"type": "T1_jamming", "s_start": 0.5, "s_end": 0.8, "params": {}}
    point_event = {"type": "T3_ambush", "s_start": 1.0, "s_end": 1.0, "params": {}}
    all_events = [zone_event, point_event]
    assert events.active_events(all_events, 0.6) == [zone_event]


def test_active_events_boundary_inclusive():
    zone_event = {"type": "T2_link_degrade", "s_start": 0.5, "s_end": 0.8, "params": {}}
    assert events.active_events([zone_event], 0.5) == [zone_event]
    assert events.active_events([zone_event], 0.8) == [zone_event]


def test_active_events_point_matches_exact_s():
    point_event = {"type": "T4_capture", "s_start": 1.0, "s_end": 1.0, "params": {}}
    assert events.active_events([point_event], 1.0) == [point_event]
    assert events.active_events([point_event], 1.01) == []


def test_active_events_empty_outside_any_zone_or_point():
    zone_event = {"type": "T1_jamming", "s_start": 0.5, "s_end": 0.8, "params": {}}
    point_event = {"type": "T7_obstacle", "s_start": 1.2, "s_end": 1.2, "params": {}}
    all_events = [zone_event, point_event]
    assert events.active_events(all_events, 0.9) == []
    assert events.active_events(all_events, 0.0) == []
