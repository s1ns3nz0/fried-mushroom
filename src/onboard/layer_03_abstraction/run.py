"""03 Sensor Abstraction Layer 오케스트레이터.

9개 결정론 채널을 실행해 AbstractionOutput 을 반환한다. proximity_object,
terrain_class, acoustic_event 의 YAMNet 2차는 step4 에서 추가된다. 이 모듈은 채널을
직접 계산하지 않고 각 채널 모듈의 run() 만 호출한다. raw 는 mutate 하지 않는다.
"""

from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.layer_03_abstraction import (
    acoustic_event,
    encryption_status,
    link_integrity,
    link_status,
    mission_phase,
    obstacle_proximity,
    operational_margin,
    position_consistency,
    rf_spectrum,
)
from onboard.shared.schemas import AbstractionOutput

SCHEMA_VERSION = "1.0"

# A-1 채널 순서 (AI 필수 채널 proximity_object/terrain_class 는 step4 에서 삽입).
_CHANNELS = (
    ("position_consistency", position_consistency),
    ("link_status", link_status),
    ("rf_spectrum", rf_spectrum),
    ("link_integrity", link_integrity),
    ("encryption_status", encryption_status),
    ("mission_phase", mission_phase),
    ("obstacle_proximity", obstacle_proximity),
    ("operational_margin", operational_margin),
    ("acoustic_event", acoustic_event),
)


def run(
    raw: RawSensorEnvelope,
    previous_qualities: dict[str, float] | None = None,
) -> AbstractionOutput:
    """9개 결정론 채널을 실행해 AbstractionOutput 반환."""
    prev = previous_qualities or {}
    channels = [
        module.run(raw, prev.get(name)) for name, module in _CHANNELS
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": f"{raw['sortie_id']}-{raw['seq']}",
        "ts": raw["ts_ms"],
        "channels": channels,
    }
