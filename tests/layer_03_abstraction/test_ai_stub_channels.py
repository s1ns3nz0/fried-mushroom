"""step4 — AI stub 채널(proximity_object, terrain_class) 테스트."""

import json
from pathlib import Path

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction.run import run

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def _channel(out, name):
    return next(c for c in out["channels"] if c["channel"] == name)


def _load_raw(scenario):
    return json.loads((EXAMPLES_DIR / f"raw_{scenario}.json").read_text("utf-8"))


def test_t3_proximity_weapon_anomaly():
    ch = _channel(run(_load_raw("t3")), "proximity_object")
    assert ch["payload"]["weapon_shape"] is True
    assert ch["state"] == "anomaly"


def test_t4_proximity_person_closing_anomaly():
    ch = _channel(run(_load_raw("t4")), "proximity_object")
    assert ch["payload"]["class"] == "person"
    assert ch["payload"]["closing"] is True
    assert ch["state"] == "anomaly"


def test_t7_terrain_defined_and_proximity_normal():
    out = run(_load_raw("t7"))
    terrain = _channel(out, "terrain_class")
    assert terrain["payload"]["dominant_class"]
    assert isinstance(terrain["payload"]["exposure_score"], (int, float))
    # T7 은 지형이 위협이지 근접객체가 아님.
    assert _channel(out, "proximity_object")["state"] == "normal"


def test_terrain_class_always_normal():
    for scenario in ("t3", "t4", "t7"):
        assert _channel(run(_load_raw(scenario)), "terrain_class")["state"] == "normal"
    assert _channel(run(build_normal_envelope("s", 0, 0)), "terrain_class")["state"] == "normal"


# --- proximity_object 열화(degraded) 경로 커버리지 ---
# 골든 시나리오(t3/t4/t7)는 전부 degraded_reason=None(고신뢰). 저시정 등으로 모델
# 확신도가 하락하는 경로가 종단 커버리지 0 이라 유닛으로 잠근다.


def _raw_with_object_label(**label):
    raw = build_normal_envelope("s", 0, 0)
    raw["imagery"]["object_label"] = label
    return raw


def test_proximity_degraded_reason_lowers_quality_and_surfaces_reason():
    raw = _raw_with_object_label(
        **{"class": "person", "closing": False, "closure_rate_mps": 0.0,
           "weapon_shape": False, "bearing_deg": 12.0, "degraded_reason": "low_visibility"}
    )
    ch = _channel(run(raw), "proximity_object")
    assert ch["quality"] == 0.55  # 저시정 → 확신도 하락 (기본 0.9 대비)
    assert ch["payload"]["degraded_reason"] == "low_visibility"


def test_proximity_degraded_still_anomaly_when_threat_closing():
    # 저시정이어도 무기형태/접근 위협 판정 자체는 유지(결정론) — 확신도만 낮다.
    raw = _raw_with_object_label(
        **{"class": "person", "closing": True, "closure_rate_mps": 4.0,
           "weapon_shape": False, "bearing_deg": 30.0, "degraded_reason": "sensor_noise"}
    )
    ch = _channel(run(raw), "proximity_object")
    assert ch["state"] == "anomaly"
    assert ch["quality"] == 0.55
    assert ch["payload"]["degraded_reason"] == "sensor_noise"


def test_proximity_no_degraded_reason_keeps_high_quality():
    raw = _raw_with_object_label(
        **{"class": "person", "closing": True, "closure_rate_mps": 4.0,
           "weapon_shape": False, "bearing_deg": 30.0, "degraded_reason": None}
    )
    ch = _channel(run(raw), "proximity_object")
    assert ch["quality"] == 0.9
    assert ch["payload"]["degraded_reason"] is None
