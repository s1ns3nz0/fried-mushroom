"""03 quality_delta 실계산 = T5(품질 급락) 언블록 계약 검증 (#45 배정, refs #79/#83).

_common.make_output 이 previous_quality 대비 delta 를 산출하고, layer_03.run 이 채널별
previous_qualities 를 스레딩하므로, 직전 사이클 quality 를 주면 실제 delta 가 나온다.
이 테스트는 T5 SIGNAL 조건(quality_delta < QUALITY_DELTA_DROP_THRESHOLD)이 03 출력에서
실제로 성립함을 잠근다.

주의: 사이클 간 previous_qualities 스레딩(현재 orchestrator/CLI 미구현)은 #83 소관,
04 T5 위협판정 배선은 #79(김호빈) 소관. 이 테스트는 그 둘의 '03 입력측 계약'이
준비돼 있음을 증명한다.
"""

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction.run import run
from onboard.shared.constants import QUALITY_DELTA_DROP_THRESHOLD


def _raw_terrain_confidence(conf):
    raw = build_normal_envelope("s", 0, 0)
    raw["imagery"]["terrain_label"] = {"dominant_class": "open_field", "camera_confidence": conf}
    return raw


def _channel(out, name):
    return next(c for c in out["channels"] if c["channel"] == name)


def test_first_cycle_without_previous_quality_yields_zero_delta():
    # 직전 사이클 없음 → delta 0.0 (T5 미탐, 정상 baseline).
    out = run(_raw_terrain_confidence(0.65))
    assert _channel(out, "terrain_class")["quality_delta"] == 0.0


def test_camera_confidence_drop_yields_delta_below_t5_threshold():
    # 광학 교란 급락: 직전 1.0 → 현재 0.65 → delta=-0.35 < -0.3 → T5 SIGNAL 성립.
    out = run(_raw_terrain_confidence(0.65), previous_qualities={"terrain_class": 1.0})
    tc = _channel(out, "terrain_class")
    assert tc["quality"] == 0.65
    assert tc["quality_delta"] < QUALITY_DELTA_DROP_THRESHOLD


def test_gradual_drop_stays_above_t5_threshold():
    # 완만한 하락(0.9→0.8, delta=-0.1)은 T5 미탐 — 거짓양성 방지 경계.
    out = run(_raw_terrain_confidence(0.8), previous_qualities={"terrain_class": 0.9})
    tc = _channel(out, "terrain_class")
    assert tc["quality_delta"] == -0.1
    assert tc["quality_delta"] >= QUALITY_DELTA_DROP_THRESHOLD


def test_previous_quality_matched_per_channel_no_crosstalk():
    # previous_qualities 는 채널명 키로 매칭 — 다른 채널 prev 가 새지 않는다.
    out = run(_raw_terrain_confidence(0.65), previous_qualities={"proximity_object": 1.0})
    # terrain_class 는 prev 미지정 → delta 0.0 (proximity_object prev 로 오염 안 됨).
    assert _channel(out, "terrain_class")["quality_delta"] == 0.0
