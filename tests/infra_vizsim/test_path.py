"""Tests for arc-length parameterization of a waypoint list (path.py).

Heading convention: compass bearing of the segment direction vector (dx, dy)
in the normalized xy plane (y=0 at top, y grows downward).
  heading_deg = atan2(dx, -dy) in degrees, normalized to [0, 360).
This yields north (-y, "up" on screen) = 0 deg, east (+x) = 90 deg,
south (+y, "down" on screen) = 180 deg, west (-x) = 270 deg.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))       # vizsim 패키지
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vizsim import path  # noqa: E402


def test_total_length_single_segment():
    wps = [{"x": 0, "y": 0, "alt_m": 100}, {"x": 1, "y": 0, "alt_m": 200}]
    assert path.total_length(wps) == 1.0


def test_total_length_multi_segment():
    wps = [
        {"x": 0, "y": 0, "alt_m": 0},
        {"x": 3, "y": 0, "alt_m": 0},
        {"x": 3, "y": 4, "alt_m": 0},
    ]
    assert path.total_length(wps) == 7.0


def test_point_at_s_midpoint_east_heading():
    wps = [{"x": 0, "y": 0, "alt_m": 100}, {"x": 1, "y": 0, "alt_m": 200}]
    result = path.point_at_s(wps, 0.5)
    assert result == {
        "x": 0.5,
        "y": 0.0,
        "alt_m": 150,
        "heading_deg": 90,
        "seg_index": 0,
    }


def test_point_at_s_negative_clamps_to_start():
    wps = [{"x": 0, "y": 0, "alt_m": 100}, {"x": 1, "y": 0, "alt_m": 200}]
    result = path.point_at_s(wps, -1)
    assert result["x"] == 0.0
    assert result["y"] == 0.0
    assert result["alt_m"] == 100
    assert result["seg_index"] == 0
    assert result["heading_deg"] == 90


def test_point_at_s_beyond_total_clamps_to_end():
    wps = [{"x": 0, "y": 0, "alt_m": 100}, {"x": 1, "y": 0, "alt_m": 200}]
    result = path.point_at_s(wps, 9)
    assert result["x"] == 1.0
    assert result["y"] == 0.0
    assert result["alt_m"] == 200
    assert result["seg_index"] == 0
    assert result["heading_deg"] == 90


def test_point_at_s_north_heading():
    # segment goes from y=1 to y=0, i.e. "up" on screen -> north -> 0 deg
    wps = [{"x": 0, "y": 1, "alt_m": 0}, {"x": 0, "y": 0, "alt_m": 0}]
    result = path.point_at_s(wps, 0.5)
    assert result["heading_deg"] == 0


def test_point_at_s_south_heading():
    # segment goes from y=0 to y=1, i.e. "down" on screen -> south -> 180 deg
    wps = [{"x": 0, "y": 0, "alt_m": 0}, {"x": 0, "y": 1, "alt_m": 0}]
    result = path.point_at_s(wps, 0.5)
    assert result["heading_deg"] == 180


def test_point_at_s_west_heading():
    wps = [{"x": 1, "y": 0, "alt_m": 0}, {"x": 0, "y": 0, "alt_m": 0}]
    result = path.point_at_s(wps, 0.5)
    assert result["heading_deg"] == 270


def test_point_at_s_second_segment_index():
    wps = [
        {"x": 0, "y": 0, "alt_m": 0},
        {"x": 1, "y": 0, "alt_m": 100},
        {"x": 2, "y": 0, "alt_m": 200},
    ]
    result = path.point_at_s(wps, 1.5)
    assert result["seg_index"] == 1
    assert result["x"] == 1.5
    assert result["alt_m"] == 150
    assert result["heading_deg"] == 90


def test_total_length_zero_for_single_waypoint():
    wps = [{"x": 0.5, "y": 0.5, "alt_m": 10}]
    assert path.total_length(wps) == 0.0
