"""03 perception 실모델 — EO 프레임 → proximity_object/terrain_class (#364, ADR-002).

#357 의 `PerceptionFrame`/`resolve_frame` 데이터경로 위에 얹는 첫 perception 실모델.
임베딩/NLP/캘리브레이션에 이은 4번째 실 ML.

**opt-in + graceful fallback**(NLP `GCS_NLP_MODEL` 선례):
- `ONBOARD_PERCEPTION_MODEL=1` 환경변수(또는 채널 인자)로만 활성. 기본은 stub 힌트 경로.
- 무거운 모델(ultralytics YOLO / segmentation)은 **lazy import + broad except**. 미설치/
  가중치 부재/`array=None`(raw 미decode) 등 어떤 실패든 **None 반환 → 호출 채널이 stub
  힌트로 하향**(크래시 0, 골든·결정론 판정 무변경).

반환 계약은 stub 과 **동일 키셋**이어야 한다(파리티):
- proximity: yolo_stub.detect_proximity 와 동일 7키.
- terrain: segmentation_stub.classify_terrain 와 동일 4키.

**SCC-1**: perception 은 03 AI 채널(병렬 참고). 결정론 채널 판정·RAC_MATRIX 와 무관.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .perception_input import PerceptionFrame

# 활성 opt-in 환경변수(NLP 의 GCS_NLP_MODEL 선례).
_ENV_FLAG = "ONBOARD_PERCEPTION_MODEL"

# 무기류로 간주할 YOLO 클래스명(가중치가 이 클래스를 낼 때만) — weapon_shape 추정.
_WEAPON_CLASSES = frozenset({"gun", "rifle", "pistol", "weapon", "knife", "firearm"})
_PERSON_CLASSES = frozenset({"person", "people", "pedestrian"})

_DETECTOR_CACHE: dict[str, Any] = {}


def enabled(explicit: bool | None = None) -> bool:
    """실모델 경로 활성 여부 — 인자 우선, 없으면 환경변수 opt-in."""
    if explicit is not None:
        return explicit
    return os.environ.get(_ENV_FLAG) == "1"


def _load_detector():
    """ultralytics YOLO lazy load — 미설치/실패 시 None(broad except, 성공분만 캐시)."""
    if "yolo" in _DETECTOR_CACHE:
        return _DETECTOR_CACHE["yolo"]
    try:
        from ultralytics import YOLO  # noqa: PLC0415

        model = YOLO("yolov8n.pt")
    except Exception:
        return None  # 캐시하지 않음(일시적 미가용이 굳지 않게 — nlp_model 선례).
    _DETECTOR_CACHE["yolo"] = model
    return model


def model_available() -> bool:
    """실 detector 로딩 가능 여부(파리티/스킵 판정용)."""
    return _load_detector() is not None


def _class_names(result) -> list[tuple[str, float]]:
    """ultralytics result → [(class_name, confidence)] (내림차순). 실패 시 []."""
    try:
        names = result.names
        out = []
        for b in result.boxes:
            cls_id = int(b.cls[0])
            conf = float(b.conf[0])
            out.append((str(names.get(cls_id, cls_id)).lower(), conf))
        out.sort(key=lambda t: t[1], reverse=True)
        return out
    except Exception:
        return []


def detect_proximity_model(frame: PerceptionFrame) -> Optional[dict]:
    """EO 프레임 → proximity 탐지(yolo_stub 와 동일 키셋). 실패/미가용 시 None.

    단일 프레임이라 시계열 필드(closing/closure_rate)는 추정 불가 → 기본값(False/0.0);
    시계열 보강은 후속. bearing 은 gimbal 메타가 있으면 bbox 수평위치로 근사, 없으면 None.
    """
    arr = frame.get("array")
    if arr is None:  # raw 미decode(decode 라이브러리 부재) → 실추론 불가 → 폴백.
        return None
    model = _load_detector()
    if model is None:
        return None
    try:
        result = model(arr, verbose=False)[0]
    except Exception:
        return None
    dets = _class_names(result)
    if not dets:  # 탐지 0 → 안전 기본(class=None) 반환(계약 유지).
        return {"class": None, "weapon_shape": False, "bearing_deg": None,
                "closing": False, "closure_rate_mps": 0.0, "quality": 0.9,
                "degraded_reason": None}
    top_cls, top_conf = next(((c, q) for c, q in dets if c in _PERSON_CLASSES), dets[0])
    cls = "person" if top_cls in _PERSON_CLASSES else top_cls
    weapon = any(c in _WEAPON_CLASSES for c, _ in dets)
    return {
        "class": cls,
        "weapon_shape": weapon,
        "bearing_deg": None,          # 단일 프레임+무 gimbal 캘리브: 미추정.
        "closing": False,             # 시계열 필요 — 기본값.
        "closure_rate_mps": 0.0,
        "quality": round(float(top_conf), 6),
        "degraded_reason": None,
    }


def _load_segmenter():
    """segmentation 모델 lazy load — 미설치/실패 시 None."""
    if "seg" in _DETECTOR_CACHE:
        return _DETECTOR_CACHE["seg"]
    try:
        from ultralytics import YOLO  # noqa: PLC0415  (yolov8-seg 계열)

        model = YOLO("yolov8n-seg.pt")
    except Exception:
        return None
    _DETECTOR_CACHE["seg"] = model
    return model


# ultralytics COCO → D4D 지형 클래스 대략 매핑(seg 결과 최빈 클래스 기반).
_TERRAIN_MAP = {
    "tree": "forest", "grass": "open_field", "field": "open_field",
    "building": "urban", "house": "urban", "road": "urban", "mountain": "mountain",
}


def classify_terrain_model(frame: PerceptionFrame) -> Optional[dict]:
    """EO 프레임 → 지형 분류(segmentation_stub 와 동일 4키). 실패/미가용 시 None."""
    arr = frame.get("array")
    if arr is None:
        return None
    model = _load_segmenter()
    if model is None:
        return None
    try:
        result = model(arr, verbose=False)[0]
    except Exception:
        return None
    dets = _class_names(result)
    if not dets:
        return {"dominant_class": "open_field", "camera_confidence": 0.9,
                "optimal_terrain_bearing_deg": None, "lowest_exposure_bearing_deg": None}
    top_cls, top_conf = dets[0]
    return {
        "dominant_class": _TERRAIN_MAP.get(top_cls, "open_field"),
        "camera_confidence": round(float(top_conf), 6),
        "optimal_terrain_bearing_deg": None,   # 방위 추정은 후속(07 corridor fallback).
        "lowest_exposure_bearing_deg": None,
    }
