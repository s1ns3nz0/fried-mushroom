"""raw_t{3,4,7}.json 원시 센서 입력 fixture smoke 테스트.

raw 스키마 정본은 layer 02(김수지)의 `RawSensorEnvelope`(nested) — 이슈 #14 결정 A.
여기서는 로드 가능·JSON 직렬화 가능·필수 키·시나리오 구분 값만 회귀 잠금한다.
"""

import json
import pathlib

import pytest

from onboard.layer_02_sensor.schema import REQUIRED_KEYS

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"

# 시나리오별 declared 국면을 유도하는 raw 필드(mission_status.flight_mode).
FLIGHT_MODE = {
    "raw_t1.json": "AUTO",    # → declared WAYPOINT (GPS 스푸핑)
    "raw_t2.json": "AUTO",    # → declared WAYPOINT (사이버)
    "raw_t3.json": "LOITER",  # → declared LOITER_ROI
    "raw_t4.json": "AUTO",    # → declared WAYPOINT
    "raw_t7.json": "LAND",    # → declared LAND
}


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(FLIGHT_MODE))
def test_raw_fixture_loads_serializable_and_keyed(name: str) -> None:
    raw = _load(name)
    json.dumps(raw, allow_nan=False)  # 레이어 간 dict 계약: 직렬화 가능
    assert set(REQUIRED_KEYS).issubset(raw.keys())
    assert raw["mission_status"]["flight_mode"] == FLIGHT_MODE[name]


def test_raw_t1_carries_gps_spoof_signal() -> None:
    raw = _load("raw_t1.json")
    # T1 GPS 스푸핑: GPS 보고 위치가 IMU 관성 추정과 >5m 어긋남 + RF 광대역 이상.
    gps, imu = raw["navigation"]["gps"], raw["navigation"]["imu"]
    assert abs(gps["lat"] - imu["est_lat"]) * 111_320.0 > 5.0
    assert raw["ew"]["rf_wideband_scan"]["wideband_anomaly"] is True


def test_raw_t2_carries_cyber_signal() -> None:
    raw = _load("raw_t2.json")
    # T2 사이버: 암호 다운그레이드 + 링크 무결성 손상.
    assert raw["c2_link"]["downgrade_detected"] is True
    assert (
        raw["c2_link"]["checksum_fail_rate"] > 0.05
        or raw["c2_link"]["seq_gap_count"] > 0
    )


def test_raw_t3_carries_gunshot_and_weapon_signal() -> None:
    raw = _load("raw_t3.json")
    # T3 근접 소화기: 총성 결정론 기준 + 무장 형상 라벨.
    assert raw["acoustic"]["peak_db"] > 90
    assert raw["acoustic"]["rise_time_ms"] < 3
    assert raw["imagery"]["object_label"]["weapon_shape"] is True


def test_raw_t4_carries_link_anomaly_and_person_closing() -> None:
    raw = _load("raw_t4.json")
    # T4 물리 포획: link anomaly + person 접근.
    assert raw["c2_link"]["rssi_dbm"] < -95
    assert raw["imagery"]["object_label"]["class"] == "person"
    assert raw["imagery"]["object_label"]["closing"] is True


def test_raw_t7_time_to_collision_under_3s() -> None:
    raw = _load("raw_t7.json")
    # T7 지형충돌: 충돌예상시간(TTC) < 3.0s
    ttc = raw["lidar"]["distance_m"] / raw["lidar"]["closure_rate_mps"]
    assert ttc < 3.0
