"""terrain_class — 🔵 GIS 우선 + 🟡 카메라 세그멘테이션 보조.

기본은 GIS 조회(mock). 카메라 결과가 GIS 와 다를 때만 세그멘테이션으로 보정하고
camera_mismatch=True 로 표시한다. 위협 채널이 아니라 배경정보라 state 는 항상 normal.
exposure_score 는 04 의 T6(배경노출도) 판정에 쓰인다.
"""

from onboard.ai_stubs.segmentation_stub import classify_terrain
from onboard.layer_03_abstraction import perception_model
from onboard.layer_03_abstraction._common import make_output
from onboard.layer_03_abstraction.perception_input import has_real_frame, resolve_frame
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

# dominant_class 별 노출도 하드코딩 상수 (step4).
_EXPOSURE_SCORE = {"open_field": 0.8, "forest": 0.2, "urban": 0.5, "mountain": 0.3}
_DEFAULT_EXPOSURE = 0.5
_GIS_LAST_UPDATED = "2025-11"


def _classify_terrain(imagery: dict) -> dict:
    """opt-in 실 segmentation(실프레임 존재 시) 우선, 실패/미가용/미활성 시 stub 폴백 (#364).

    실모델은 stub 과 동일 키셋을 반환하므로 아래 GIS 대조/노출도 로직 무변경(결정론·골든 유지).
    """
    if perception_model.enabled() and has_real_frame(imagery):
        frame = resolve_frame(imagery)
        if frame is not None:
            cam = perception_model.classify_terrain_model(frame)
            if cam is not None:
                return cam
    return classify_terrain(imagery)


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    # GIS 조회(mock): environment.mock_gis_class 있으면 사용, 없으면 open_field 기본.
    gis_class = raw["environment"].get("mock_gis_class", "open_field")
    cam = _classify_terrain(raw["imagery"])
    cam_class = cam["dominant_class"]

    camera_mismatch = cam_class != gis_class
    # 불일치 시 카메라 판정으로 보정, 일치 시 GIS 값 유지 (A-1).
    dominant_class = cam_class if camera_mismatch else gis_class
    source = "camera_verified" if camera_mismatch else "gis_lookup"
    risk_map_ref = f"buf://terrain_seg/{raw['seq']}" if camera_mismatch else None

    payload = {
        "dominant_class": dominant_class,
        "source": source,
        "gis_last_updated": _GIS_LAST_UPDATED,
        "camera_mismatch": camera_mismatch,
        "exposure_score": _EXPOSURE_SCORE.get(dominant_class, _DEFAULT_EXPOSURE),
        "risk_map_ref": risk_map_ref,
        # 지형 방위(#40 option a): 07 reroute anchor 정본 소스. 미확정 시 null → 07 corridor fallback.
        "optimal_terrain_bearing_deg": cam["optimal_terrain_bearing_deg"],
        "lowest_exposure_bearing_deg": cam["lowest_exposure_bearing_deg"],
    }
    # 배경 정보라 항상 normal.
    return make_output("terrain_class", "normal", cam["camera_confidence"], payload, previous_quality)
