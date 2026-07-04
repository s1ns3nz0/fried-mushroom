"""proximity_object — 🟡 AI(필수). YOLO stub 로 사람/무기/접근 탐지.

규칙기반으로 사람·무기 형태 판별이 불가능해 AI 가 필수인 채널. 실제 모델은 step4
에서도 stub 으로 둔다(ai_stubs.yolo_stub).
"""

from onboard.ai_stubs.yolo_stub import detect_proximity
from onboard.layer_03_abstraction import perception_model
from onboard.layer_03_abstraction._common import make_output
from onboard.layer_03_abstraction.perception_input import has_real_frame, resolve_frame
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

_CLOSING_THREAT_CLASSES = {"person", "vehicle", "drone"}


def _detect_proximity(imagery: dict) -> dict:
    """opt-in 실모델(실프레임 존재 시) 우선, 실패/미가용/미활성 시 stub 힌트 폴백 (#364).

    실모델은 stub 과 동일 키셋을 반환하므로 아래 판정 로직은 무변경(결정론·골든 유지).
    """
    if perception_model.enabled() and has_real_frame(imagery):
        frame = resolve_frame(imagery)
        if frame is not None:
            det = perception_model.detect_proximity_model(frame)
            if det is not None:
                return det
    return detect_proximity(imagery)


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    det = _detect_proximity(raw["imagery"])
    cls = det["class"]

    # 무기 형태 소지, 또는 위협 클래스가 접근 중이면 anomaly.
    if det["weapon_shape"] or (det["closing"] and cls in _CLOSING_THREAT_CLASSES):
        state = "anomaly"
    else:
        state = "normal"

    payload = {
        "class": cls,
        "weapon_shape": det["weapon_shape"],
        "bearing_deg": det["bearing_deg"],
        "closing": det["closing"],
        "closure_rate_mps": det["closure_rate_mps"],
        "degraded_reason": det["degraded_reason"],
    }
    return make_output("proximity_object", state, det["quality"], payload, previous_quality)
