"""AI 채널 stub↔실모델 계약·하향 파리티 프레임워크 (ADR-002 전환 안전망, #336).

전 AI 채널을 레지스트리로 관리하고 세 가지 계약을 강제한다:
1. 스텁 출력 스키마 계약: 각 채널 stub 출력이 선언된 키/타입/범위를 만족
2. 하향(graceful degrade): 선택 의존 미설치 시 크래시 없이 폴백
3. 결정론 계약: 결정론 채널은 같은 입력 → 같은 출력

SCC-1 (CLAUDE.md CRITICAL): advisory 채널(embedding/NLP)은 결정론 RAC 판정에
어떤 영향도 주지 않는다. 이 파일은 그 경계를 명시적으로 검증한다.

채널별 분류 — 통과 / 미충족 / 모델-미구현(stub 고정, 실 모델 PR 대기).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# infra/log 임포트 (embedding 모듈 위치)
_INFRA_LOG = Path(__file__).resolve().parents[2] / "infra" / "log"
if str(_INFRA_LOG) not in sys.path:
    sys.path.insert(0, str(_INFRA_LOG))

import embedding as _emb
from gcs.layer_01_info_center import nlp_extract as _nlp
from onboard.ai_stubs import segmentation_stub as _seg
from onboard.ai_stubs import yamnet_stub as _yamnet
from onboard.ai_stubs import yolo_stub as _yolo


# ── 채널 레지스트리 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChannelEntry:
    """AI 채널 계약 레지스트리 항목.

    새 AI 모델을 추가할 때 이 레지스트리에 항목을 추가하면
    이후 파리티 테스트가 자동으로 신규 채널을 포함한다.
    """

    name: str
    # 출력 계약: 키 → 허용 타입 튜플 (None 허용 시 type(None) 포함)
    output_contract: dict[str, tuple[type, ...]]
    # 선택 의존 패키지 (미설치 시 하향 경로 검증)
    optional_dep: str | None = None
    # 결정론 채널 여부 (같은 입력 → 같은 출력이 보장돼야 하면 True)
    deterministic: bool = True
    # SCC-1: RAC/위협 판정에 영향 없는 advisory 채널
    advisory: bool = False
    # 실 모델 구현 여부 (stub 고정이면 False → 모델-미구현 분류)
    real_model_implemented: bool = False


# 레지스트리 — 새 채널은 여기에 추가한다
_REGISTRY: list[ChannelEntry] = [
    ChannelEntry(
        name="embedding",
        output_contract={},  # list[float] | None — 별도 검증
        optional_dep="sentence_transformers",
        deterministic=True,
        advisory=True,
        real_model_implemented=True,  # infra/log/embedding.py 실 모델 존재
    ),
    ChannelEntry(
        name="nlp_extract",
        output_contract={
            "source_phrase": (str,),
            "signal_type": (str,),
            "confidence": (float,),
        },
        optional_dep=None,
        deterministic=True,
        advisory=True,
        real_model_implemented=False,  # 키워드룰 구현, NLP 모델 미구현
    ),
    ChannelEntry(
        name="yolo",
        output_contract={
            "class": (str, type(None)),
            "weapon_shape": (bool,),
            "bearing_deg": (float, int, type(None)),
            "closing": (bool,),
            "closure_rate_mps": (float, int),
            "quality": (float, int),
            "degraded_reason": (str, type(None)),
        },
        optional_dep=None,
        deterministic=True,
        advisory=False,
        real_model_implemented=False,  # stub 고정 (YOLOv8 PR 대기)
    ),
    ChannelEntry(
        name="yamnet",
        output_contract={
            "event_type": (str,),
            "yamnet_confidence": (float, int),
        },
        optional_dep=None,
        deterministic=True,
        advisory=False,
        real_model_implemented=False,  # stub 고정 (YAMNet PR 대기)
    ),
    ChannelEntry(
        name="segmentation",
        output_contract={
            "dominant_class": (str,),
            "camera_confidence": (float, int),
            "optimal_terrain_bearing_deg": (float, int, type(None)),
            "lowest_exposure_bearing_deg": (float, int, type(None)),
        },
        optional_dep=None,
        deterministic=True,
        advisory=False,
        real_model_implemented=False,  # stub 고정 (Fast-SCNN PR 대기)
    ),
]

_REGISTRY_BY_NAME = {e.name: e for e in _REGISTRY}

# 샘플 입력 — 채널별 stub 호출용
_SAMPLE_INPUTS: dict[str, Any] = {
    "embedding": "적 저격조 조우, 고도 상승 회피 기동",
    "nlp_extract": "저격조 확인됨. 대구경화기 식별. 사이버 재밍 가능성.",
    "yolo": {"object_label": {"class": "person", "weapon_shape": True,
                               "bearing_deg": 45.0, "closing": False,
                               "closure_rate_mps": 0.0}},
    "yamnet": {"mock_label": "gunshot"},
    "segmentation": {"terrain_label": {"dominant_class": "urban",
                                        "camera_confidence": 0.85,
                                        "optimal_terrain_bearing_deg": 270.0,
                                        "lowest_exposure_bearing_deg": None}},
}


def _call_stub(name: str, inp: Any) -> Any:
    """채널 이름으로 stub 함수 호출."""
    if name == "embedding":
        return _emb.embed(inp)
    if name == "nlp_extract":
        return _nlp.extract_signals(inp)
    if name == "yolo":
        return _yolo.detect_proximity(inp)
    if name == "yamnet":
        return _yamnet.classify_acoustic(inp)
    if name == "segmentation":
        return _seg.classify_terrain(inp)
    raise ValueError(f"알 수 없는 채널: {name}")


# ── 1. 레지스트리 완전성 ───────────────────────────────────────────────────────


def test_registry_covers_all_ai_channels():
    """레지스트리가 5개 AI 채널 전체를 포함해야 한다."""
    expected = {"embedding", "nlp_extract", "yolo", "yamnet", "segmentation"}
    assert set(_REGISTRY_BY_NAME) == expected, (
        f"레지스트리 누락: {expected - set(_REGISTRY_BY_NAME)}"
    )


def test_registry_entries_have_name_and_contract():
    """각 레지스트리 항목이 name + output_contract 를 보유해야 한다."""
    for entry in _REGISTRY:
        assert entry.name, "빈 채널 이름"
        assert isinstance(entry.output_contract, dict), f"{entry.name}: contract가 dict 아님"


# ── 2. 스텁 출력 스키마 계약 ──────────────────────────────────────────────────


def _assert_output_contract(name: str, output: Any, contract: dict) -> None:
    """출력값이 contract 키/타입을 만족하는지 검증."""
    assert isinstance(output, dict), f"{name}: 출력이 dict 아님 (got {type(output).__name__})"
    for key, allowed_types in contract.items():
        assert key in output, f"{name}: 출력 키 '{key}' 누락"
        val = output[key]
        assert isinstance(val, allowed_types), (
            f"{name}.{key}: 타입 불일치 — expected {allowed_types}, got {type(val).__name__}={val!r}"
        )


def test_yolo_stub_output_contract():
    """YOLO stub 출력이 선언된 7-키 계약을 만족해야 한다."""
    entry = _REGISTRY_BY_NAME["yolo"]
    out = _call_stub("yolo", _SAMPLE_INPUTS["yolo"])
    _assert_output_contract("yolo", out, entry.output_contract)


def test_yolo_stub_default_output_contract():
    """YOLO stub 기본값(힌트 없음)도 계약을 만족해야 한다."""
    entry = _REGISTRY_BY_NAME["yolo"]
    out = _call_stub("yolo", {})
    _assert_output_contract("yolo", out, entry.output_contract)
    assert out["class"] is None, "힌트 없음 → class=None"
    assert out["weapon_shape"] is False, "힌트 없음 → weapon_shape=False"


def test_yamnet_stub_output_contract():
    """YAMNet stub 출력이 2-키 계약을 만족해야 한다."""
    entry = _REGISTRY_BY_NAME["yamnet"]
    out = _call_stub("yamnet", _SAMPLE_INPUTS["yamnet"])
    _assert_output_contract("yamnet", out, entry.output_contract)


def test_yamnet_stub_default_output_contract():
    """YAMNet stub 기본값(힌트 없음)도 계약을 만족해야 한다."""
    entry = _REGISTRY_BY_NAME["yamnet"]
    out = _call_stub("yamnet", {})
    _assert_output_contract("yamnet", out, entry.output_contract)
    assert out["event_type"] == "unknown", "힌트 없음 → event_type=unknown"


def test_segmentation_stub_output_contract():
    """Segmentation stub 출력이 4-키 계약을 만족해야 한다."""
    entry = _REGISTRY_BY_NAME["segmentation"]
    out = _call_stub("segmentation", _SAMPLE_INPUTS["segmentation"])
    _assert_output_contract("segmentation", out, entry.output_contract)


def test_segmentation_stub_default_output_contract():
    """Segmentation stub 기본값(힌트 없음)도 계약을 만족해야 한다."""
    entry = _REGISTRY_BY_NAME["segmentation"]
    out = _call_stub("segmentation", {})
    _assert_output_contract("segmentation", out, entry.output_contract)
    assert out["dominant_class"] == "open_field", "힌트 없음 → open_field"


def test_nlp_extract_output_is_list_of_signals():
    """nlp_extract 출력이 list[dict] 이고 각 dict 가 계약 키를 갖춰야 한다."""
    entry = _REGISTRY_BY_NAME["nlp_extract"]
    result = _call_stub("nlp_extract", _SAMPLE_INPUTS["nlp_extract"])
    assert isinstance(result, list), "nlp_extract: 출력이 list 아님"
    assert len(result) >= 1, "nlp_extract: 샘플 입력에서 최소 1개 신호 기대"
    for sig in result:
        _assert_output_contract("nlp_extract.signal", sig, entry.output_contract)
        assert 0.0 <= sig["confidence"] <= 1.0, f"confidence 범위 위반: {sig['confidence']}"


def test_nlp_extract_empty_input_returns_empty_list():
    """빈 지시서 → 빈 신호 리스트 (크래시 없음)."""
    result = _call_stub("nlp_extract", "")
    assert result == [], "빈 입력 → 빈 리스트"


def test_embedding_returns_list_or_none():
    """embed() 는 list[float] 또는 None 을 반환해야 한다 (크래시 없음)."""
    result = _call_stub("embedding", _SAMPLE_INPUTS["embedding"])
    assert result is None or isinstance(result, list), (
        f"embedding: list 또는 None 기대, got {type(result).__name__}"
    )
    if isinstance(result, list):
        assert all(isinstance(x, float) for x in result), "embedding: 요소가 모두 float 이어야 함"
        assert len(result) > 0, "embedding: 빈 리스트 불가"


def test_embedding_none_for_empty_text():
    """빈/None 텍스트 → None 반환 (계약)."""
    assert _emb.embed("") is None
    assert _emb.embed(None) is None


# ── 3. 하향(graceful degrade) ────────────────────────────────────────────────


def test_embedding_degrades_when_model_unavailable(monkeypatch):
    """sentence-transformers 미설치 시 embed() → None (크래시 없음)."""
    monkeypatch.setattr(_emb, "_load", lambda name: None)
    result = _emb.embed("테스트 텍스트")
    assert result is None, "모델 미가용 → None 하향"


def test_yolo_no_crash_on_missing_keys():
    """YOLO stub 은 임의 불완전 입력에도 크래시 없이 기본값을 반환해야 한다."""
    for inp in [{}, {"object_label": None}, {"object_label": {}}]:
        out = _yolo.detect_proximity(inp)
        assert isinstance(out, dict), f"입력 {inp}: dict 반환 기대"
        assert "class" in out


def test_yamnet_no_crash_on_missing_keys():
    """YAMNet stub 은 임의 불완전 입력에도 크래시 없이 기본값을 반환해야 한다."""
    for inp in [{}, {"mock_label": None}]:
        out = _yamnet.classify_acoustic(inp)
        assert isinstance(out, dict), f"입력 {inp}: dict 반환 기대"
        assert "event_type" in out


def test_segmentation_no_crash_on_missing_keys():
    """Segmentation stub 은 임의 불완전 입력에도 크래시 없이 기본값을 반환해야 한다."""
    for inp in [{}, {"terrain_label": None}, {"terrain_label": {}}]:
        out = _seg.classify_terrain(inp)
        assert isinstance(out, dict), f"입력 {inp}: dict 반환 기대"
        assert "dominant_class" in out


def test_nlp_extract_no_crash_on_none_input():
    """nlp_extract 는 None 입력에도 크래시 없이 빈 리스트를 반환해야 한다."""
    result = _nlp.extract_signals(None)
    assert isinstance(result, list)


# ── 4. 결정론 계약 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["yolo", "yamnet", "segmentation", "nlp_extract"])
def test_stub_determinism(name: str):
    """결정론 채널: 같은 입력으로 두 번 호출 시 동일 출력."""
    entry = _REGISTRY_BY_NAME[name]
    assert entry.deterministic, f"{name}: 결정론 채널이어야 함"
    inp = _SAMPLE_INPUTS[name]
    out1 = _call_stub(name, inp)
    out2 = _call_stub(name, inp)
    assert out1 == out2, f"{name}: 결정론 위반 — 같은 입력에 다른 출력"


def test_embedding_determinism_when_model_available(monkeypatch):
    """embed() 는 모델이 있을 때 같은 텍스트 → 같은 벡터를 반환해야 한다."""
    fixed_vec = [0.1, 0.2, 0.3]
    monkeypatch.setattr(_emb, "_load", lambda name: _FakeModel(fixed_vec))
    text = "동일한 입력 텍스트"
    assert _emb.embed(text) == _emb.embed(text), "결정론 위반"


class _FakeModel:
    """embed() 결정론 테스트용 더미 모델."""
    def __init__(self, vec: list):
        self._vec = vec

    def encode(self, texts, normalize_embeddings=False):
        import numpy as np
        return np.array([self._vec] * len(texts))


# ── 5. SCC-1: advisory 채널이 RAC 에 영향 없음 ───────────────────────────────


def test_advisory_channels_marked_in_registry():
    """embedding, nlp_extract 는 레지스트리에서 advisory=True 로 표시돼야 한다 (SCC-1)."""
    for name in ("embedding", "nlp_extract"):
        entry = _REGISTRY_BY_NAME[name]
        assert entry.advisory, (
            f"{name}: SCC-1 위반 — advisory 채널은 advisory=True 로 표시 필요"
        )


def test_non_advisory_channels_not_marked_advisory():
    """YOLO/YAMNet/Segmentation 은 advisory=False (직접 위협 감지 채널)."""
    for name in ("yolo", "yamnet", "segmentation"):
        entry = _REGISTRY_BY_NAME[name]
        assert not entry.advisory, (
            f"{name}: advisory=False 이어야 함 (직접 위협 감지 채널)"
        )


def test_embedding_output_not_in_rac_pipeline(monkeypatch):
    """embedding 출력이 RAC 파이프라인(run_cycle)에 전달되지 않는다 (SCC-1 구조 검증).

    run_cycle 의 입력 계약(raw+brief)에 embedding 관련 키가 없음을 확인한다.
    """
    from onboard.run import run_cycle
    from onboard.layer_02_sensor.mock_source import build_normal_envelope

    raw = build_normal_envelope("SCC1-TEST", 0, 0)
    brief = {
        "sortie_id": "SCC1-01",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
    }

    # embedding 을 강제로 비-None 값으로 설정해도 RAC 출력이 변하지 않아야 한다
    monkeypatch.setattr(_emb, "embed", lambda text, name=None: [0.99] * 384)
    out_with_emb = run_cycle(raw, brief)

    monkeypatch.setattr(_emb, "embed", lambda text, name=None: None)
    out_without_emb = run_cycle(raw, brief)

    assert out_with_emb["risk"] == out_without_emb["risk"], (
        "SCC-1 위반: embedding 출력이 RAC(risk) 판정에 영향을 줌"
    )


# ── 6. 채널 분류 리포트 ───────────────────────────────────────────────────────


def test_channel_classification_report():
    """채널별 (통과/미충족/모델-미구현) 분류를 출력하고 회귀를 잠근다.

    - 통과: 스텁 계약 + 하향 검증 모두 통과
    - 모델-미구현: stub 고정, 실 모델 PR 대기 (real_model_implemented=False)
    - 미충족: real_model_implemented=True 이나 추가 검증 필요
    """
    implemented = [e for e in _REGISTRY if e.real_model_implemented]
    stub_only = [e for e in _REGISTRY if not e.real_model_implemented]

    # 현재 상태 고정 — 신규 모델 구현 시 이 값이 바뀌며 리뷰어에게 명시됨
    assert len(implemented) == 1, (
        f"실 모델 구현 채널 수 변경: 기대 1, 실제 {len(implemented)} "
        f"({[e.name for e in implemented]})"
    )
    assert len(stub_only) == 4, (
        f"stub-only 채널 수 변경: 기대 4, 실제 {len(stub_only)} "
        f"({[e.name for e in stub_only]})"
    )
    assert implemented[0].name == "embedding", "실 모델 구현 채널: embedding"


# ── 7. 실 모델 smoke (선택 의존, 네트워크 필요 시 skip) ──────────────────────


def test_embedding_real_model_smoke():
    """sentence-transformers 설치 시 실 모델로 벡터를 생성하고 계약을 검증한다."""
    pytest.importorskip("sentence_transformers")
    vec = _emb.embed("적 저격조 조우 후 고도 상승 회피 기동")
    if vec is None:
        pytest.skip("임베딩 모델 가중치 로드 불가(네트워크/캐시 부재)")
    assert isinstance(vec, list), "실 모델: list[float] 반환 기대"
    assert all(isinstance(x, float) for x in vec), "실 모델: 요소 모두 float"
    assert len(vec) > 0, "실 모델: 빈 벡터 불가"
    # L2 정규화 확인
    import math
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-3, f"실 모델: L2 정규화 벡터 기대 (norm={norm:.4f})"
    # 결정론
    vec2 = _emb.embed("적 저격조 조우 후 고도 상승 회피 기동")
    assert vec == vec2, "실 모델: 결정론 위반"


# --- 폴백 안전망: stub 이 malformed(비-dict) 라벨에 크래시하지 않음 ---


def test_yolo_stub_non_dict_label_falls_back():
    from onboard.ai_stubs.yolo_stub import detect_proximity
    for bad in ("person", ["x"], 123, True):
        out = detect_proximity({"object_label": bad})
        assert out["class"] is None  # malformed → 안전 기본값(크래시 없음)


def test_segmentation_stub_non_dict_label_falls_back():
    from onboard.ai_stubs.segmentation_stub import classify_terrain
    for bad in ("forest", ["x"], 123):
        out = classify_terrain({"terrain_label": bad})
        assert out["dominant_class"] == "open_field"


def test_channels_no_crash_on_non_dict_labels():
    from onboard.layer_02_sensor.mock_source import build_normal_envelope
    from onboard.layer_03_abstraction import proximity_object, terrain_class
    raw = build_normal_envelope("s", 0, 0)
    raw["imagery"]["object_label"] = "person"
    raw["imagery"]["terrain_label"] = "forest"
    assert proximity_object.run(raw)["payload"]["class"] is None
    assert terrain_class.run(raw)["payload"]["dominant_class"] in {"open_field", "forest"}
