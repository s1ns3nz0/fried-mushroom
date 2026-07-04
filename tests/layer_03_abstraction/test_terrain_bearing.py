"""terrain_class 지형 방위 필드 (#40 option a / #45).

03 terrain_class 가 optimal/lowest-exposure 방위를 payload 로 산출해 07 reroute 의
정본 소스가 되게 한다. 세그멘테이션/GIS 로 방위를 못 정하면 null(→ 07 corridor fallback).
"""

from onboard.ai_stubs.segmentation_stub import classify_terrain
from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction import terrain_class

_BEARING_KEYS = {"optimal_terrain_bearing_deg", "lowest_exposure_bearing_deg"}


def _terrain(raw):
    return terrain_class.run(raw)["payload"]


def test_bearing_keys_always_present():
    payload = _terrain(build_normal_envelope("s", 0, 0))
    assert _BEARING_KEYS.issubset(payload.keys())


def test_bearing_null_when_no_hint():
    # 힌트 없으면(GIS-only stub) 방위 미확정 → null → 07 corridor heuristic fallback.
    payload = _terrain(build_normal_envelope("s", 0, 0))
    assert payload["optimal_terrain_bearing_deg"] is None
    assert payload["lowest_exposure_bearing_deg"] is None


def test_bearing_from_terrain_label_hint():
    raw = build_normal_envelope("s", 0, 0)
    raw["imagery"]["terrain_label"] = {
        "dominant_class": "forest",
        "optimal_terrain_bearing_deg": 47.0,
        "lowest_exposure_bearing_deg": 137.0,
    }
    payload = _terrain(raw)
    assert payload["optimal_terrain_bearing_deg"] == 47.0
    assert payload["lowest_exposure_bearing_deg"] == 137.0


def test_segmentation_stub_returns_bearing_keys():
    out = classify_terrain({"terrain_label": {"optimal_terrain_bearing_deg": 10.0}})
    assert out["optimal_terrain_bearing_deg"] == 10.0
    assert out["lowest_exposure_bearing_deg"] is None  # 힌트 없는 필드는 null
    # 힌트 자체가 없으면 둘 다 null
    assert classify_terrain({})["optimal_terrain_bearing_deg"] is None
