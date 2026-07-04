"""YOLO 계열 객체탐지 + 무기판별 stub (ADR-002: stub 우선).

실제 모델(YOLOv8n/YOLO-NAS nano → MobileNetV3-small)은 로딩하지 않는다. raw imagery 에
step2 가 심어둔 mock 라벨 힌트(`object_label`)를 읽어 고정 결과를 리턴한다. 실제 모델로
교체될 때 반환 dict 의 키는 동일해야 한다.
"""

_DEFAULT = {
    "class": None,
    "weapon_shape": False,
    "bearing_deg": None,
    "closing": False,
    "closure_rate_mps": 0.0,
    "quality": 0.9,
    "degraded_reason": None,
}


def detect_proximity(raw_imagery: dict) -> dict:
    """imagery.object_label 힌트 → 탐지 결과. 힌트 없으면 안전한 기본값(class=None)."""
    label = raw_imagery.get("object_label")
    if not label:
        return dict(_DEFAULT)

    cls = label.get("class")
    if cls in (None, "none"):
        cls = None
    degraded_reason = label.get("degraded_reason")
    # 저시정 등 열화 사유가 있으면 모델 확신도 하락 (A-1 예시 반영).
    quality = 0.55 if degraded_reason else 0.9

    return {
        "class": cls,
        "weapon_shape": bool(label.get("weapon_shape", False)),
        "bearing_deg": label.get("bearing_deg"),
        "closing": bool(label.get("closing", False)),
        "closure_rate_mps": label.get("closure_rate_mps", 0.0),
        "quality": quality,
        "degraded_reason": degraded_reason,
    }
