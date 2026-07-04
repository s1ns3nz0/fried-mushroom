"""카메라 지형 세그멘테이션 stub (ADR-002: stub 우선).

실제 모델(Fast-SCNN/BiSeNetV2/PIDNet-S)은 로딩하지 않는다. raw imagery 의 mock 라벨
힌트(`terrain_label`)를 읽어 고정 결과를 리턴한다.
"""

_DEFAULT = {
    "dominant_class": "open_field",
    "camera_confidence": 0.9,
    # 지형 방위(#40 option a): 세그멘테이션으로 방위를 못 정하면 null → 07 corridor fallback.
    "optimal_terrain_bearing_deg": None,
    "lowest_exposure_bearing_deg": None,
}


def classify_terrain(raw_imagery: dict) -> dict:
    """imagery.terrain_label 힌트 → 카메라 지형 분류 + 지형 방위. 힌트 없으면 기본값."""
    label = raw_imagery.get("terrain_label")
    if not label:
        return dict(_DEFAULT)
    return {
        "dominant_class": label.get("dominant_class", "open_field"),
        "camera_confidence": label.get("camera_confidence", 0.9),
        "optimal_terrain_bearing_deg": label.get("optimal_terrain_bearing_deg"),
        "lowest_exposure_bearing_deg": label.get("lowest_exposure_bearing_deg"),
    }
