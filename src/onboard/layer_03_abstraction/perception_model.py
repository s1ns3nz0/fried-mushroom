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
    """ultralytics result → [(class_name, confidence)] (내림차순). 실패 시 [].

    **detection(boxes)·classification/segmentation(probs) 둘 다 지원**(codex #368 P2):
    proximity 는 detection(YOLO boxes), terrain 은 씬-classification/segmentation(probs)
    모델을 쓰므로 출력 형태가 다르다. probs 가 있으면(cls/seg) 그걸 우선 읽고, 없으면 boxes.
    """
    try:
        names = result.names
        probs = getattr(result, "probs", None)
        if probs is not None:  # classification/scene-seg 모델 (terrain).
            if hasattr(probs, "top5") and hasattr(probs, "top5conf"):
                idxs = list(probs.top5)
                confs = [float(c) for c in probs.top5conf.tolist()]
            else:
                idxs = [int(probs.top1)]
                confs = [float(probs.top1conf)]
            out = [(str(names.get(i, i)).lower(), c) for i, c in zip(idxs, confs)]
            out.sort(key=lambda t: t[1], reverse=True)
            return out
        out = []  # detection/segmentation 모델 (proximity) — boxes.
        for b in (result.boxes or []):
            out.append((str(names.get(int(b.cls[0]), int(b.cls[0]))).lower(), float(b.conf[0])))
        out.sort(key=lambda t: t[1], reverse=True)
        return out
    except Exception:
        return []


def _frame_array(frame: PerceptionFrame):
    """frame.array 우선. 없으면 fmt=="raw" + 치수로 raw_bytes 를 (h,w,c) uint8 배열 복원
    (#407: shipped raw 예시가 실모델에 도달하도록). numpy 부재·치수 불일치 등 실패 시 None."""
    arr = frame.get("array")
    if arr is not None:
        return arr
    if frame.get("fmt") != "raw":
        return None
    w, h, c = frame.get("width") or 0, frame.get("height") or 0, frame.get("channels") or 0
    raw = frame.get("raw_bytes")
    if not (w and h and c) or not raw or len(raw) != w * h * c:
        return None  # 치수 없음/불일치 → 안전 폴백(오해석 방지).
    try:
        import numpy as np  # noqa: PLC0415

        return np.frombuffer(raw, dtype=np.uint8).reshape(h, w, c)
    except Exception:
        return None


def detect_proximity_model(frame: PerceptionFrame) -> Optional[dict]:
    """EO 프레임 → proximity 탐지(yolo_stub 와 동일 키셋). 실패/미가용 시 None.

    단일 프레임이라 시계열 필드(closing/closure_rate)는 추정 불가 → 기본값(False/0.0);
    시계열 보강은 후속. bearing 은 gimbal 메타가 있으면 bbox 수평위치로 근사, 없으면 None.
    """
    arr = _frame_array(frame)  # #407: raw 예시도 픽셀 복원해 실모델 투입.
    if arr is None:  # decode/복원 불가 → 실추론 불가 → 폴백.
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
    """지형 시맨틱 씬-segmentation 모델 lazy load — 미설치/실패 시 None.

    **주의(codex #368 P2)**: COCO instance-seg(yolov8-seg)는 tree/grass/road/mountain 같은
    지형 씬 라벨을 내지 않는다. 지형 분류에는 **ADE20K 계열 시맨틱 씬 segmentation**
    (tree/grass/road/building/mountain/field/water …)이 필요하다. env `ONBOARD_TERRAIN_SEG_MODEL`
    로 씬-seg 모델명을 지정(미지정/미설치 시 None → stub 폴백). 라벨이 지형클래스가 아니면
    classify_terrain_model 이 None 을 반환해 오보 대신 폴백한다.
    """
    if "seg" in _DETECTOR_CACHE:
        return _DETECTOR_CACHE["seg"]
    model_name = os.environ.get("ONBOARD_TERRAIN_SEG_MODEL")
    if not model_name:
        return None  # 지형용 씬-seg 모델 미지정 → 폴백(COCO-seg 오분류 방지).
    try:
        from ultralytics import YOLO  # noqa: PLC0415

        model = YOLO(model_name)
    except Exception:
        return None
    _DETECTOR_CACHE["seg"] = model
    return model


# ADE20K 계열 시맨틱 씬 라벨 → D4D 지형 클래스 매핑. 여기 없는 라벨은 "지형 아님"으로 보고
# None 반환(오보 방지). D4D 지형: open_field / forest / urban / mountain.
_TERRAIN_MAP = {
    "tree": "forest", "forest": "forest", "palm": "forest",
    "grass": "open_field", "field": "open_field", "earth": "open_field",
    "sand": "open_field", "dirt": "open_field", "path": "open_field",
    "building": "urban", "house": "urban", "road": "urban", "skyscraper": "urban",
    "wall": "urban", "sidewalk": "urban",
    "mountain": "mountain", "rock": "mountain", "hill": "mountain",
}


def classify_terrain_model(frame: PerceptionFrame) -> Optional[dict]:
    """EO 프레임 → 지형 분류(segmentation_stub 와 동일 4키). 실패/미가용/비-지형 라벨 시 None.

    top 씬 라벨이 지형 클래스로 매핑되지 않으면(예: COCO 객체 라벨) None → stub 폴백해
    지배 지형 오보(전부 open_field)를 막는다(codex #368 P2).
    """
    arr = _frame_array(frame)  # #407: raw 예시도 픽셀 복원해 실모델 투입.
    if arr is None:
        return None
    model = _load_segmenter()
    if model is None:
        return None
    try:
        result = model(arr, verbose=False)[0]
    except Exception:
        return None
    for cls, conf in _class_names(result):  # 신뢰도순 — 첫 지형 라벨 채택.
        mapped = _TERRAIN_MAP.get(cls)
        if mapped is not None:
            return {
                "dominant_class": mapped,
                "camera_confidence": round(float(conf), 6),
                "optimal_terrain_bearing_deg": None,   # 방위 추정 후속(07 corridor fallback).
                "lowest_exposure_bearing_deg": None,
            }
    return None  # 지형 라벨 없음 → 폴백(오보 방지).
