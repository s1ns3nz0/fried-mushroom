"""obstacle_proximity — 🔵 결정론(레인지파인더). 충돌예상시간 판정."""

from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.constants import TIME_TO_COLLISION_THRESHOLD_S
from onboard.shared.schemas import ChannelOutput


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    lidar = raw["lidar"]
    distance_m = lidar["distance_m"]
    closure_rate_mps = lidar["closure_rate_mps"]

    # 0/음수 나눗셈 방지: 접근 중이 아니면 normal.
    if distance_m is None or closure_rate_mps is None or closure_rate_mps <= 0:
        state = "normal"
    else:
        ttc = distance_m / closure_rate_mps
        state = "anomaly" if ttc < TIME_TO_COLLISION_THRESHOLD_S else "normal"

    quality = 0.85  # 레인지파인더 신뢰도 대리값 (MVP proxy)

    payload = {"distance_m": distance_m, "closure_rate_mps": closure_rate_mps}
    return make_output("obstacle_proximity", state, quality, payload, previous_quality)
