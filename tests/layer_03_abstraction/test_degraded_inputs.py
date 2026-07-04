"""03 저하·결측·경계 입력 그레이스풀 처리 커버리지 (#187).

정상 경로는 조밀하나(#180 감사), degraded sensor / missing optional field / 경계밖 값
에서 03 이 예외 없이 스키마 적합한 출력을 내는지(NaN/None 오염 없음) 잠근다. test-only.
발견된 미처리 케이스는 별도 코드 이슈 — 현재 전 케이스 그레이스풀.
"""

import math

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction.run import run

_VALID_STATE = {"normal", "degraded", "anomaly"}


def _raw(**_):
    return build_normal_envelope("s", 0, 0)


def _channel(out, name):
    return next(c for c in out["channels"] if c["channel"] == name)


def _assert_output_healthy(out):
    """모든 채널: 예외 없이 스키마 유지 + quality/quality_delta 숫자([0,1]) + state 유효."""
    assert len(out["channels"]) == 11
    for c in out["channels"]:
        for k in ("channel", "state", "quality", "quality_delta", "payload"):
            assert k in c, f"{c.get('channel')} 키 누락: {k}"
        q = c["quality"]
        assert isinstance(q, (int, float)) and not math.isnan(q), f"{c['channel']} quality 오염: {q!r}"
        assert 0.0 <= q <= 1.0, f"{c['channel']} quality 범위밖: {q}"
        d = c["quality_delta"]
        assert isinstance(d, (int, float)) and not math.isnan(d)
        assert c["state"] in _VALID_STATE


# --- 1. degraded proximity/terrain ---


def test_degraded_proximity_falls_back_quality_drop():
    raw = _raw()
    raw["imagery"]["object_label"] = {
        "class": "person", "weapon_shape": False, "closing": False, "closure_rate_mps": 0.0,
        "bearing_deg": None, "degraded_reason": "low_visibility",
    }
    out = run(raw)
    _assert_output_healthy(out)
    px = _channel(out, "proximity_object")
    assert px["quality"] == 0.55  # 저하 확신도 반영
    assert px["payload"]["degraded_reason"] == "low_visibility"


def test_degraded_terrain_camera_confidence_drop():
    raw = _raw()
    raw["imagery"]["terrain_label"] = {"dominant_class": "open_field", "camera_confidence": 0.4}
    out = run(raw)
    _assert_output_healthy(out)
    assert _channel(out, "terrain_class")["quality"] == 0.4


# --- 2. 결측 optional 필드 (KeyError 없이 기본 처리) ---


def test_missing_object_label_uses_stub_default():
    raw = _raw()
    del raw["imagery"]["object_label"]
    _assert_output_healthy(run(raw))  # yolo_stub 기본값(class=None)


def test_missing_terrain_label_uses_stub_default():
    raw = _raw()
    del raw["imagery"]["terrain_label"]
    _assert_output_healthy(run(raw))  # segmentation_stub 기본값


def test_missing_acoustic_mock_label_ok():
    raw = _raw()
    raw["acoustic"].pop("mock_label", None)  # 힌트 없음 → unknown 경로
    _assert_output_healthy(run(raw))


# --- 3. 경계/이상치 (스키마 유지 + 오염 없음) ---


def test_negative_alt_agl_graceful():
    raw = _raw()
    raw["environment"]["alt_agl_m"] = -10.0
    _assert_output_healthy(run(raw))


def test_zero_ground_speed_graceful():
    raw = _raw()
    raw["mission_status"]["ground_speed_mps"] = 0.0
    raw["navigation"]["imu"]["est_speed_mps"] = 0.0
    _assert_output_healthy(run(raw))


def test_gnss_confidence_boundaries():
    for conf in (0.0, 1.0):
        raw = _raw()
        raw["ew"]["gnss_confidence"] = conf
        _assert_output_healthy(run(raw))


def test_zero_lidar_distance_graceful():
    # 거리 0 + 접근 → 0나눗셈/음수TTC 없이 처리(obstacle_proximity 가드).
    raw = _raw()
    raw["lidar"] = {"distance_m": 0.0, "closure_rate_mps": 5.0}
    _assert_output_healthy(run(raw))


def test_zero_battery_pct_graceful():
    raw = _raw()
    raw["health"]["battery"]["pct"] = 0
    _assert_output_healthy(run(raw))
