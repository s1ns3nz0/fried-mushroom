"""encryption_status — 🔵 결정론. 프로토콜 암호화 모드 필드 판독."""

from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    c2 = raw["c2_link"]
    mode = c2["encryption_mode"]
    downgrade_detected = c2["downgrade_detected"]

    # NONE(암호화 해제) 또는 강제 다운그레이드 이력 → anomaly (A-1).
    state = "anomaly" if downgrade_detected or mode == "NONE" else "normal"
    # quality = 판독기 건전성(A-1/#28): 프로토콜 필드 판독이라 이상 여부와 무관하게 높다.
    # 위협 크기를 quality 에 섞으면 04 Q_MIN 게이트가 실제 이상신호를 필터한다.
    quality = 0.99

    payload = {"mode": mode, "downgrade_detected": downgrade_detected}
    return make_output("encryption_status", state, quality, payload, previous_quality)
