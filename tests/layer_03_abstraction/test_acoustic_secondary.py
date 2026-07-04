"""step4 — acoustic_event YAMNet 2차 게이팅 테스트."""

from unittest.mock import patch

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction import acoustic_event


def _raw_with_acoustic(**acoustic):
    raw = build_normal_envelope("s", 0, 0)
    raw["acoustic"].update(acoustic)
    return raw


def test_clear_gunshot_skips_yamnet():
    raw = _raw_with_acoustic(peak_db=110.0, rise_time_ms=1.0)
    with patch(
        "onboard.layer_03_abstraction.acoustic_event.classify_acoustic"
    ) as spy:
        out = acoustic_event.run(raw)
    spy.assert_not_called()
    assert out["payload"]["detection_stage"] == "threshold_only"
    assert out["payload"]["event_type"] == "gunshot"


def test_ambiguous_promotes_to_yamnet():
    # 애매한 파형 + mock_label 힌트 → YAMNet 2차 승격.
    raw = _raw_with_acoustic(peak_db=80.0, rise_time_ms=8.0, mock_label="gunshot")
    out = acoustic_event.run(raw)
    assert out["payload"]["detection_stage"] == "yamnet_secondary"
    assert out["payload"]["event_type"] == "gunshot"
    assert "yamnet_confidence" in out["payload"]


def test_ambiguous_calls_yamnet_once():
    raw = _raw_with_acoustic(peak_db=80.0, rise_time_ms=8.0, mock_label="gunshot")
    with patch(
        "onboard.layer_03_abstraction.acoustic_event.classify_acoustic",
        wraps=acoustic_event.classify_acoustic,
    ) as spy:
        acoustic_event.run(raw)
    spy.assert_called_once()


# --- 2차 게이팅 분기 커버리지 (기존은 gunshot 승격/skip 만 커버) ---


def test_quiet_skips_yamnet_and_stays_normal():
    # peak_db < 75 → 1차에서 none/normal 확정, YAMNet 미호출.
    raw = _raw_with_acoustic(peak_db=55.0, rise_time_ms=40.0, mock_label="gunshot")
    with patch(
        "onboard.layer_03_abstraction.acoustic_event.classify_acoustic"
    ) as spy:
        out = acoustic_event.run(raw)
    spy.assert_not_called()
    assert out["state"] == "normal"
    assert out["payload"]["event_type"] == "none"
    assert out["payload"]["detection_stage"] == "threshold_only"


def test_ambiguous_no_hint_stays_ambiguous_degraded():
    # 애매 + 힌트 없음 → YAMNet unknown → ambiguous 유지, degraded, conf 0.5.
    raw = _raw_with_acoustic(peak_db=80.0, rise_time_ms=8.0)
    raw["acoustic"].pop("mock_label", None)
    out = acoustic_event.run(raw)
    assert out["payload"]["detection_stage"] == "yamnet_secondary"
    assert out["payload"]["event_type"] == "ambiguous"
    assert out["state"] == "degraded"
    assert out["payload"]["yamnet_confidence"] == 0.5
    assert out["quality"] == 0.5


def test_ambiguous_explosion_promotes_to_anomaly():
    raw = _raw_with_acoustic(peak_db=80.0, rise_time_ms=8.0, mock_label="explosion")
    out = acoustic_event.run(raw)
    assert out["payload"]["event_type"] == "explosion"
    assert out["state"] == "anomaly"
    assert out["payload"]["detection_stage"] == "yamnet_secondary"


def test_ambiguous_propeller_maps_to_approach_degraded():
    # YAMNet "propeller" → A-1 어휘 "propeller_approach", degraded.
    raw = _raw_with_acoustic(peak_db=80.0, rise_time_ms=8.0, mock_label="propeller")
    out = acoustic_event.run(raw)
    assert out["payload"]["event_type"] == "propeller_approach"
    assert out["state"] == "degraded"


def test_ambiguous_unmapped_label_falls_back_to_ambiguous():
    # YAMNet 이 A-1 어휘에 없는 라벨(vehicle)을 주면 ambiguous 로 정규화.
    raw = _raw_with_acoustic(peak_db=80.0, rise_time_ms=8.0, mock_label="vehicle")
    out = acoustic_event.run(raw)
    assert out["payload"]["event_type"] == "ambiguous"
    assert out["state"] == "degraded"


# --- 1차 임계 경계값 커버리지 ---
# gunshot: peak_db > 90.0 AND rise_ms < 3.0 (둘 다 엄격 부등호)
# ambiguous: peak_db >= 75.0 (포함) / else none. 경계 테스트가 0 이라 잠근다.


def _spy_run(raw):
    """acoustic_event.run 을 돌리며 YAMNet 2차 호출 여부(spy)를 함께 반환.

    wraps 로 실제 classify_acoustic 을 감싸 ambiguous 경로도 유효 dict 를 받도록 한다
    (호출 여부만 관찰; 반환값 대체 아님).
    """
    with patch(
        "onboard.layer_03_abstraction.acoustic_event.classify_acoustic",
        wraps=acoustic_event.classify_acoustic,
    ) as spy:
        out = acoustic_event.run(raw)
    return out, spy


def test_peak_db_exactly_90_is_not_gunshot():
    # 90.0 은 > 90.0 이 아니므로 gunshot 아님 → ambiguous 경로(YAMNet 2차) 진입.
    out, spy = _spy_run(_raw_with_acoustic(peak_db=90.0, rise_time_ms=1.0))
    spy.assert_called_once()
    assert out["payload"]["event_type"] != "gunshot"


def test_rise_time_exactly_3_is_not_gunshot():
    # rise 3.0 은 < 3.0 이 아니므로 gunshot 아님 → ambiguous 경로.
    out, spy = _spy_run(_raw_with_acoustic(peak_db=95.0, rise_time_ms=3.0))
    spy.assert_called_once()
    assert out["payload"]["event_type"] != "gunshot"


def test_gunshot_just_inside_both_thresholds():
    # peak_db=90.1(>90) AND rise=2.9(<3) → 1차 gunshot 확정, YAMNet 미호출.
    out, spy = _spy_run(_raw_with_acoustic(peak_db=90.1, rise_time_ms=2.9))
    spy.assert_not_called()
    assert out["payload"]["event_type"] == "gunshot"
    assert out["state"] == "anomaly"
    assert out["payload"]["detection_stage"] == "threshold_only"


def test_peak_db_exactly_75_is_ambiguous():
    # 75.0 >= 75.0 → ambiguous 경로 진입(YAMNet 2차 호출).
    out, spy = _spy_run(_raw_with_acoustic(peak_db=75.0, rise_time_ms=40.0))
    spy.assert_called_once()


def test_peak_db_just_below_75_is_none_normal():
    # 74.9 < 75.0 → none/normal, YAMNet 미호출.
    out, spy = _spy_run(_raw_with_acoustic(peak_db=74.9, rise_time_ms=40.0))
    spy.assert_not_called()
    assert out["payload"]["event_type"] == "none"
    assert out["state"] == "normal"
