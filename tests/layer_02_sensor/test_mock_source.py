"""step2 — mock 원시 센서 소스 테스트."""

import json
from pathlib import Path

import pytest

from onboard.layer_02_sensor.mock_source import (
    build_normal_envelope,
    build_scenario_envelope,
)
from onboard.layer_02_sensor.schema import REQUIRED_KEYS

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
GOLDEN_SEQ = 0
GOLDEN_TS_MS = 1730620801200


@pytest.mark.parametrize("scenario", ["t1", "t2", "t3", "t4", "t7"])
def test_scenario_fills_required_keys(scenario):
    env = build_scenario_envelope(scenario, 0, 0)
    assert set(REQUIRED_KEYS).issubset(env.keys())


def test_t1_gps_imu_residual_signal():
    # T1 GPS 스푸핑: gps 보고 위치와 imu 추정 위치의 잔차가 5m 임계값을 초과해야 함.
    env = build_scenario_envelope("t1", 0, 0)
    gps, imu = env["navigation"]["gps"], env["navigation"]["imu"]
    residual_m = abs(gps["lat"] - imu["est_lat"]) * 111_320.0
    assert residual_m > 5.0


def test_t2_encryption_and_integrity_signal():
    # T2 사이버: 암호화 다운그레이드 + 링크 무결성 이상.
    env = build_scenario_envelope("t2", 0, 0)
    c2 = env["c2_link"]
    assert c2["downgrade_detected"] is True
    assert c2["checksum_fail_rate"] > 0.05 or c2["seq_gap_count"] > 0


def test_t3_gunshot_thresholds():
    env = build_scenario_envelope("t3", 0, 0)
    assert env["acoustic"]["peak_db"] > 90
    assert env["acoustic"]["rise_time_ms"] < 3


def test_t3_proximity_weapon_label():
    env = build_scenario_envelope("t3", 0, 0)
    label = env["imagery"]["object_label"]
    assert label["class"] == "person"
    assert label["weapon_shape"] is True


def test_t4_link_anomaly_rssi():
    env = build_scenario_envelope("t4", 0, 0)
    assert env["c2_link"]["rssi_dbm"] < -95


def test_t4_multi_channel_conditions():
    env = build_scenario_envelope("t4", 0, 0)
    label = env["imagery"]["object_label"]
    assert label["class"] in {"person", "vehicle"}
    assert label["closing"] is True


def test_t7_time_to_collision_below_threshold():
    env = build_scenario_envelope("t7", 0, 0)
    ttc = env["lidar"]["distance_m"] / env["lidar"]["closure_rate_mps"]
    assert ttc < 3.0


def test_normal_envelope_is_deterministic():
    assert build_normal_envelope("s", 0, 0) == build_normal_envelope("s", 0, 0)


def test_scenario_envelope_is_deterministic():
    assert build_scenario_envelope("t3", 0, 0) == build_scenario_envelope("t3", 0, 0)


def test_unknown_scenario_raises():
    with pytest.raises(ValueError):
        build_scenario_envelope("t9", 0, 0)


@pytest.mark.parametrize("scenario", ["t1", "t2", "t3", "t4", "t7"])
def test_golden_fixture_matches_builder(scenario):
    fixture = EXAMPLES_DIR / f"raw_{scenario}.json"
    saved = json.loads(fixture.read_text(encoding="utf-8"))
    generated = build_scenario_envelope(scenario, GOLDEN_SEQ, GOLDEN_TS_MS)
    # JSON 라운드트립과 동일하게 비교(튜플→리스트 등 정규화).
    assert saved == json.loads(json.dumps(generated))
