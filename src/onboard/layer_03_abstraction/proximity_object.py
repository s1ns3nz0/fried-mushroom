"""proximity_object — 🟡 AI(필수). YOLO stub 로 사람/무기/접근 탐지.

규칙기반으로 사람·무기 형태 판별이 불가능해 AI 가 필수인 채널. 실제 모델은 step4
에서도 stub 으로 둔다(ai_stubs.yolo_stub).
"""

from onboard.ai_stubs.yolo_stub import detect_proximity
from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

_CLOSING_THREAT_CLASSES = {"person", "vehicle", "drone"}


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    det = detect_proximity(raw["imagery"])
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
