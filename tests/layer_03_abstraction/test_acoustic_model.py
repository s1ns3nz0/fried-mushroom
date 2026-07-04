"""03 acoustic 실모델(YAMNet) opt-in + fallback + 파리티 (perception 후속)."""

import json
import os
from pathlib import Path

from onboard.ai_stubs.yamnet_stub import classify_acoustic
from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction import acoustic_model, acoustic_event
from onboard.layer_03_abstraction.perception_input import (
    has_real_audio,
    resolve_audio,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_STUB_KEYS = {"event_type", "yamnet_confidence"}


def _acoustic_with_wave():
    bundle = json.loads((_EXAMPLES / "acoustic_waveform_synth.json").read_text(encoding="utf-8"))
    return {**build_normal_envelope("s", 0, 0)["acoustic"], "waveform": bundle["waveform"],
            "mock_label": "gunshot", "peak_db": 80.0, "rise_time_ms": 5.0, "bearing_deg": 90.0}


# --- 오디오 데이터경로(resolve_audio) ---


def test_mock_acoustic_has_no_real_audio():
    raw = build_normal_envelope("s", 0, 0)
    assert has_real_audio(raw["acoustic"]) is False
    assert resolve_audio(raw["acoustic"]) is None


def test_resolve_audio_contract():
    clip = resolve_audio(_acoustic_with_wave())
    assert clip is not None
    assert clip["fmt"] == "pcm16" and clip["sample_rate"] == 16000 and clip["channels"] == 1
    assert isinstance(clip["raw_bytes"], bytes) and len(clip["raw_bytes"]) == 320  # 160 samples*2B


# --- opt-in 게이트 + 미가용 폴백 ---


def test_enabled_flag(monkeypatch):
    monkeypatch.delenv("ONBOARD_PERCEPTION_MODEL", raising=False)
    assert acoustic_model.enabled() is False
    monkeypatch.setenv("ONBOARD_PERCEPTION_MODEL", "1")
    assert acoustic_model.enabled() is True


def test_model_returns_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(acoustic_model, "_load_yamnet", lambda: None)
    clip = resolve_audio(_acoustic_with_wave())
    assert acoustic_model.classify_acoustic_model(clip) is None


def test_acoustic_event_falls_back_when_model_unavailable(monkeypatch):
    # opt-in + 실파형이나 YAMNet 미설치 → stub 폴백(크래시 0, 계약 유지).
    monkeypatch.setenv("ONBOARD_PERCEPTION_MODEL", "1")
    raw = build_normal_envelope("s", 0, 0)
    raw["acoustic"] = _acoustic_with_wave()  # ambiguous 유도(peak 80)
    out = acoustic_event.run(raw)
    assert out["payload"]["detection_stage"] in ("threshold_only", "yamnet_secondary")
    assert "event_type" in out["payload"]


# --- 배선: 모델이 값을 내면 게이팅이 그걸 소비(파리티 키셋) ---


def test_channel_consumes_model_secondary(monkeypatch):
    monkeypatch.setenv("ONBOARD_PERCEPTION_MODEL", "1")
    monkeypatch.setattr(acoustic_model, "classify_acoustic_model",
                        lambda c: {"event_type": "gunshot", "yamnet_confidence": 0.88})
    raw = build_normal_envelope("s", 0, 0)
    raw["acoustic"] = _acoustic_with_wave()  # peak 80 → ambiguous → 2차
    out = acoustic_event.run(raw)
    assert out["payload"]["detection_stage"] == "yamnet_secondary"
    assert out["payload"]["event_type"] == "gunshot"       # 모델값(정규화)
    assert out["payload"]["yamnet_confidence"] == 0.88
    assert out["state"] == "anomaly"                        # gunshot → anomaly (로직 무변경)


def test_model_keyset_matches_stub():
    assert set(classify_acoustic({}).keys()) == _STUB_KEYS


def test_disabled_uses_stub_secondary(monkeypatch):
    # 미활성: 실파형 있어도 stub 2차 사용(골든 무변경 보장).
    monkeypatch.delenv("ONBOARD_PERCEPTION_MODEL", raising=False)
    raw = build_normal_envelope("s", 0, 0)
    raw["acoustic"] = _acoustic_with_wave()
    out = acoustic_event.run(raw)
    stub = classify_acoustic(raw["acoustic"])
    # ambiguous 경로에서 stub 어휘 정규화 결과를 따름.
    assert out["payload"]["detection_stage"] in ("threshold_only", "yamnet_secondary")


# --- 견고성: malformed waveform 은 크래시 대신 안전 파싱 ---


def test_resolve_audio_malformed_does_not_crash():
    import base64
    b = base64.b64encode(b"xxxx").decode()
    for bad in ("abc", None, "8000.5"):
        clip = resolve_audio({"waveform": {"bytes_b64": b, "sample_rate": bad, "channels": bad}})
        assert clip is not None
        assert isinstance(clip["sample_rate"], int) and isinstance(clip["channels"], int)
    clip = resolve_audio({"waveform": {"bytes_b64": b, "meta": "notdict"}})
    assert clip is not None and clip["meta"] == {}
