"""raw_t5 시나리오 fixture 의 03 입력측 검증 (#45 배정, refs #79/#83).

02 build_scenario_envelope("t5") 가 심는 terrain_class 품질급락(camera_confidence=0.65)이,
직전 사이클 quality(1.0) 대비 quality_delta < -0.3 (T5 SIGNAL) 을 만드는지 잠근다.
사이클 간 previous_qualities 스레딩(#83, orchestrator)·04 T5 배선(#79)·종단 골든은 별건.
"""

from onboard.layer_02_sensor.mock_source import build_scenario_envelope
from onboard.layer_03_abstraction.run import run
from onboard.shared.constants import QUALITY_DELTA_DROP_THRESHOLD


def _channel(out, name):
    return next(c for c in out["channels"] if c["channel"] == name)


def test_t5_fixture_terrain_delta_triggers_t5_signal():
    # raw_t5(camera_confidence=0.65) + 직전 1.0 → terrain_class delta≈-0.35 < -0.3.
    out = run(build_scenario_envelope("t5", 0, 0), previous_qualities={"terrain_class": 1.0})
    tc = _channel(out, "terrain_class")
    assert tc["quality"] == 0.65
    assert tc["quality_delta"] < QUALITY_DELTA_DROP_THRESHOLD


def test_t5_fixture_first_cycle_no_delta_no_signal():
    # 직전 없음(1st cycle) → delta 0.0 → T5 미탐 (사이클 간 스레딩 전 상태, 정상).
    out = run(build_scenario_envelope("t5", 0, 0))
    assert _channel(out, "terrain_class")["quality_delta"] == 0.0


def test_t5_fixture_is_single_threat_no_other_anomaly():
    # T5 는 terrain 품질급락만 — 다른 채널은 정상(단일 위협 보장). terrain_class 는
    # 배경정보라 state 항상 normal, T5 판정은 04 가 quality_delta 로 한다.
    out = run(build_scenario_envelope("t5", 0, 0), previous_qualities={"terrain_class": 1.0})
    anomalous = [c["channel"] for c in out["channels"] if c["state"] == "anomaly"]
    assert anomalous == []
