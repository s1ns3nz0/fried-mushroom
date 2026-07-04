"""acoustic_event — 🔵 1차 임계값 매칭 (YAMNet 2차는 step4).

peak_db·rise_time_ms 로 총성을 1차 확정한다. 애매 케이스는 event_type="ambiguous",
detection_stage="threshold_only" 로 남겨 step4 의 YAMNet 2차 승격이 덮어쓰게 한다.
"""

from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

_GUNSHOT_PEAK_DB = 90.0
_GUNSHOT_RISE_MS = 3.0
_AMBIGUOUS_PEAK_DB = 75.0


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    acoustic = raw["acoustic"]
    peak_db = acoustic["peak_db"]
    rise_time_ms = acoustic["rise_time_ms"]

    if peak_db > _GUNSHOT_PEAK_DB and rise_time_ms < _GUNSHOT_RISE_MS:
        event_type, state, quality = "gunshot", "anomaly", 0.92
    elif peak_db >= _AMBIGUOUS_PEAK_DB:
        # 1차만으로 애매 — step4 YAMNet 2차 대상.
        event_type, state, quality = "ambiguous", "degraded", 0.6
    else:
        event_type, state, quality = "none", "normal", 0.9

    payload = {
        "event_type": event_type,
        "detection_stage": "threshold_only",
        "peak_db": peak_db,
        "bearing_deg": acoustic["bearing_deg"],
    }
    return make_output("acoustic_event", state, quality, payload, previous_quality)
