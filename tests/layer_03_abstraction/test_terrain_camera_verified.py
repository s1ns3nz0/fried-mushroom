"""t6 시나리오 — camera_verified 지형 경로 + 노출도→T6 커버리지 (#45).

기존 골든 6종은 전부 gis_lookup(camera_mismatch=false)이라 카메라 검증 분기가
종단 커버리지 0이었다. t6: GIS=forest 인데 카메라가 open_field 감지(벌목형) →
source=camera_verified, exposure_score=0.8 → 04 background_exposure_score.
"""

from onboard.layer_02_sensor.mock_source import build_scenario_envelope
from onboard.layer_03_abstraction.run import run as run03
from onboard.layer_04_threat.run import run as run04

_CTX = {"optimal_terrain_bearing_deg": 0.0, "lowest_exposure_bearing_deg": 0.0}


def _terrain(scenario):
    out = run03(build_scenario_envelope(scenario, 0, 0))
    return next(c for c in out["channels"] if c["channel"] == "terrain_class")


def test_t6_camera_verified_branch():
    ch = _terrain("t6")
    p = ch["payload"]
    assert p["source"] == "camera_verified"
    assert p["camera_mismatch"] is True
    assert p["dominant_class"] == "open_field"   # 카메라 우선(벌목 보정)
    assert p["risk_map_ref"] is not None
    assert p["exposure_score"] == 0.8
    assert ch["state"] == "normal"                # 배경 정보 — 위협 아님


def test_t6_exposure_flows_to_background_exposure_score():
    # 노출도 경로: terrain_class.exposure_score → 04 background_exposure_score (T6 배경).
    abstraction = run03(build_scenario_envelope("t6", 0, 0))
    threat = run04(abstraction, _CTX)
    assert threat["background_exposure_score"] == 0.8


def test_t6_no_primary_threat():
    # t6 는 배경 노출 시나리오 — 능동 위협 채널 없음 → primary 없음.
    abstraction = run03(build_scenario_envelope("t6", 0, 0))
    threat = run04(abstraction, _CTX)
    assert threat["primary"] is None
