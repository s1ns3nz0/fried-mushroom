"""step2 — mock 원시 센서 소스 테스트."""

import json
from pathlib import Path

import pytest

from onboard.layer_02_sensor.mock_source import (
    build_normal_envelope,
    build_scenario_envelope,
)
from onboard.layer_02_sensor.schema import REQUIRED_KEYS
# phase-intent 검증은 실제 03 분류기를 태운다(magic threshold 회피, codex P2).
from onboard.layer_03_abstraction import mission_phase

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
GOLDEN_SEQ = 0
GOLDEN_TS_MS = 1730620801200


@pytest.mark.parametrize("scenario", ["t1", "t2", "t3", "t4", "t5", "t6", "t7"])
def test_scenario_fills_required_keys(scenario):
    env = build_scenario_envelope(scenario, 0, 0)
    assert set(REQUIRED_KEYS).issubset(env.keys())


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


def test_t1_gps_spoof_position_divergence():
    # GPS 스푸핑: GPS 보고 위치가 IMU 관성 추정과 >5m 어긋남 (03 position_consistency anomaly 유발).
    env = build_scenario_envelope("t1", 0, 0)
    gps, imu = env["navigation"]["gps"], env["navigation"]["imu"]
    dlat_m = abs(gps["lat"] - imu["est_lat"]) * 111_320.0
    assert dlat_m > 5.0
    assert env["ew"]["rf_wideband_scan"]["wideband_anomaly"] is True  # rf_spectrum T1 보조 신호


def test_t2_cyber_link_and_encryption():
    # 사이버/C2 하이재킹: 암호 다운그레이드 + 링크 무결성 손상 (04 T2 두 조건).
    env = build_scenario_envelope("t2", 0, 0)
    c2 = env["c2_link"]
    assert c2["downgrade_detected"] is True  # encryption_status anomaly
    assert c2["checksum_fail_rate"] > 0.05 or c2["seq_gap_count"] > 0  # link_integrity anomaly


def test_normal_envelope_is_deterministic():
    assert build_normal_envelope("s", 0, 0) == build_normal_envelope("s", 0, 0)


def test_scenario_envelope_is_deterministic():
    assert build_scenario_envelope("t3", 0, 0) == build_scenario_envelope("t3", 0, 0)


def test_unknown_scenario_raises():
    with pytest.raises(ValueError):
        build_scenario_envelope("t9", 0, 0)


# --- declared-phase / 행동 mismatch / t6 주입 SIGNAL 조건 커버리지 ---
# 전체 envelope 동치는 test_golden_fixture_matches_builder 가 이미 잠근다. 여기서는
# 04 declared_phase·T4 mismatch·T6 camera_verified 를 유발하는 개별 주입 의도만 가드한다
# (기존 threshold/object 테스트가 안 짚는 축).
#
# phase-intent 는 raw 필드를 magic threshold(<3.0/<5.0)와 비교하지 않고, 실제 03
# mission_phase 분류기를 직접 태워 declared/behavioral/match 결과를 잠근다 — 그래야
# 분류기 컷오프(_LOITER_SPEED_MAX_MPS=2.0)와 어긋나 생기는 거짓 안심을 막는다 (codex P2).


def test_t3_injects_loiter_declared_phase():
    # LOITER + 저속 → 03 mission_phase declared=LOITER_ROI, behavioral=LOITER_ROI.
    ph = mission_phase.run(build_scenario_envelope("t3", 0, 0))["payload"]
    assert ph["declared"] == "LOITER_ROI"
    assert ph["behavioral"] == "LOITER_ROI"


def test_t4_injects_declared_behavior_mismatch():
    # T4 핵심 조건: declared=WAYPOINT(AUTO) ↔ behavioral=LOITER_ROI(저속) → match=False.
    ph = mission_phase.run(build_scenario_envelope("t4", 0, 0))["payload"]
    assert ph["declared"] == "WAYPOINT"
    assert ph["behavioral"] == "LOITER_ROI"
    assert ph["match"] is False


def test_t7_injects_land_declared_phase():
    # LAND + 저고도(alt_agl < 30) → declared=LAND, behavioral=LAND.
    ph = mission_phase.run(build_scenario_envelope("t7", 0, 0))["payload"]
    assert ph["declared"] == "LAND"
    assert ph["behavioral"] == "LAND"


def test_t6_injects_camera_gis_mismatch():
    # T6 camera_verified: GIS=forest ↔ 카메라 open_field 불일치 → 03 terrain_class 카메라 우선.
    env = build_scenario_envelope("t6", 0, 0)
    assert env["environment"]["mock_gis_class"] == "forest"
    terrain = env["imagery"]["terrain_label"]
    assert terrain["dominant_class"] == "open_field"
    assert terrain["camera_mismatch"] is True


def test_t5_injects_terrain_confidence_drop():
    # T5(광학 교란): terrain_class 품질(camera_confidence)이 낮게(0.65) 주입돼 직전(1.0)
    # 대비 급락 → 03 quality_delta<-0.3 (T5 SIGNAL). GIS 일치라 camera_mismatch 는 없음.
    env = build_scenario_envelope("t5", 0, 0)
    terrain = env["imagery"]["terrain_label"]
    assert terrain["camera_confidence"] == 0.65
    assert terrain["dominant_class"] == "open_field"


@pytest.mark.parametrize("scenario", ["t1", "t2", "t3", "t4", "t5", "t6", "t7"])
def test_golden_fixture_matches_builder(scenario):
    fixture = EXAMPLES_DIR / f"raw_{scenario}.json"
    saved = json.loads(fixture.read_text(encoding="utf-8"))
    generated = build_scenario_envelope(scenario, GOLDEN_SEQ, GOLDEN_TS_MS)
    # JSON 라운드트립과 동일하게 비교(튜플→리스트 등 정규화).
    assert saved == json.loads(json.dumps(generated))
