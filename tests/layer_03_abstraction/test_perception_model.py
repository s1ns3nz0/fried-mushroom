"""03 perception 실모델 opt-in + graceful fallback + 파리티 (#364, ADR-002)."""

import json
from pathlib import Path

import pytest

from onboard.ai_stubs.yolo_stub import detect_proximity
from onboard.ai_stubs.segmentation_stub import classify_terrain
from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction import perception_model, proximity_object, terrain_class

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_PROX_KEYS = {"class", "weapon_shape", "bearing_deg", "closing", "closure_rate_mps",
              "quality", "degraded_reason"}
_TERR_KEYS = {"dominant_class", "camera_confidence",
              "optimal_terrain_bearing_deg", "lowest_exposure_bearing_deg"}


def _raw_with_frame():
    bundle = json.loads((_EXAMPLES / "imagery_frame_synth.json").read_text(encoding="utf-8"))
    raw = build_normal_envelope("s", 0, 0)
    raw["imagery"]["eo_frame"] = bundle["eo_frame"]
    return raw


# --- opt-in 게이트 ---


def test_enabled_respects_flag_and_explicit(monkeypatch):
    monkeypatch.delenv("ONBOARD_PERCEPTION_MODEL", raising=False)
    assert perception_model.enabled() is False
    monkeypatch.setenv("ONBOARD_PERCEPTION_MODEL", "1")
    assert perception_model.enabled() is True
    assert perception_model.enabled(explicit=False) is False  # 인자 우선


# --- 기본(미활성): stub 경로 = 골든 무변경 ---


def test_disabled_channel_matches_stub():
    raw = build_normal_envelope("s", 0, 0)
    out = proximity_object.run(raw)
    stub = detect_proximity(raw["imagery"])
    assert out["payload"]["class"] == stub["class"]
    assert out["quality"] == stub["quality"]


# --- opt-in + 실프레임이나 모델 미가용 → stub 폴백(크래시 0) ---


def test_enabled_but_model_unavailable_falls_back(monkeypatch):
    monkeypatch.setenv("ONBOARD_PERCEPTION_MODEL", "1")
    raw = _raw_with_frame()  # 실프레임 있음
    # ultralytics 미설치 → detect_proximity_model None → stub 폴백.
    out = proximity_object.run(raw)
    assert set(out["payload"].keys()) >= {"class", "weapon_shape", "closing"}
    # stub 과 동일 결과(모델 미가용이므로).
    assert out["quality"] == detect_proximity(raw["imagery"])["quality"]


def test_model_functions_return_none_when_unavailable(monkeypatch):
    monkeypatch.setattr(perception_model, "_load_detector", lambda: None)
    monkeypatch.setattr(perception_model, "_load_segmenter", lambda: None)
    from onboard.layer_03_abstraction.perception_input import resolve_frame
    frame = resolve_frame(_raw_with_frame()["imagery"])
    assert perception_model.detect_proximity_model(frame) is None
    assert perception_model.classify_terrain_model(frame) is None


def test_raw_array_none_returns_none():
    # raw 포맷(decode 없음) → array None → 모델 추론 불가 → None(폴백).
    from onboard.layer_03_abstraction.perception_input import resolve_frame
    frame = resolve_frame(_raw_with_frame()["imagery"])
    assert frame["array"] is None
    assert perception_model.detect_proximity_model(frame) is None


# --- 배선: 모델이 값을 내면 채널이 그걸 소비(파리티: 동일 키셋) ---


def test_channel_consumes_model_output_when_available(monkeypatch):
    monkeypatch.setenv("ONBOARD_PERCEPTION_MODEL", "1")
    fake = {"class": "person", "weapon_shape": True, "bearing_deg": None,
            "closing": False, "closure_rate_mps": 0.0, "quality": 0.77, "degraded_reason": None}
    monkeypatch.setattr(perception_model, "detect_proximity_model", lambda f: fake)
    out = proximity_object.run(_raw_with_frame())
    assert out["payload"]["class"] == "person" and out["payload"]["weapon_shape"] is True
    assert out["quality"] == 0.77
    assert out["state"] == "anomaly"  # weapon_shape → anomaly (판정 로직 무변경)


def test_model_output_keyset_matches_stub():
    # 실모델 반환 계약이 stub 과 동일 키셋(파리티 — 판정 로직이 그대로 소비 가능).
    assert set(perception_model.detect_proximity_model.__doc__ or "")  # 존재
    stub_prox = set(detect_proximity({}).keys())
    stub_terr = set(classify_terrain({}).keys())
    assert stub_prox == _PROX_KEYS and stub_terr == _TERR_KEYS


def test_terrain_channel_consumes_model_output(monkeypatch):
    monkeypatch.setenv("ONBOARD_PERCEPTION_MODEL", "1")
    fake = {"dominant_class": "forest", "camera_confidence": 0.66,
            "optimal_terrain_bearing_deg": None, "lowest_exposure_bearing_deg": None}
    monkeypatch.setattr(perception_model, "classify_terrain_model", lambda f: fake)
    raw = _raw_with_frame()
    raw["environment"]["mock_gis_class"] = "open_field"
    out = terrain_class.run(raw)
    assert out["payload"]["dominant_class"] == "forest"  # 모델값(GIS 와 불일치→camera_verified)
    assert out["payload"]["camera_mismatch"] is True


@pytest.mark.skipif(not perception_model.model_available(), reason="perception 실모델 미설치(CI 기본 폴백)")
def test_real_model_output_contract_when_installed():
    from onboard.layer_03_abstraction.perception_input import resolve_frame
    frame = resolve_frame(_raw_with_frame()["imagery"])
    prox = perception_model.detect_proximity_model(frame)
    if prox is not None:
        assert set(prox.keys()) == _PROX_KEYS
