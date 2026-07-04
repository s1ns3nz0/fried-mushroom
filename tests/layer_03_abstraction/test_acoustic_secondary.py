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
