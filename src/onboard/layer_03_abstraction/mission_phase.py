"""mission_phase — 🔵 결정론적 룰테이블.

declared(오토파일럿 flight_mode) 와 behavioral(행동패턴 역산)을 대조해 일치 여부를
판정한다. 목표/귀환 거리는 이 채널에서 계산하지 않음 (03 범위 밖, A-1).
"""

from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

# flight_mode(오토파일럿) → declared 임무단계.
_FLIGHT_MODE_TO_DECLARED = {
    "TAKEOFF": "TAKEOFF",
    "AUTO": "WAYPOINT",
    "MISSION": "WAYPOINT",
    "WAYPOINT": "WAYPOINT",
    "LOITER": "LOITER_ROI",
    "GUIDED": "LOITER_ROI",
    "RTL": "RTL",
    "LAND": "LAND",
}

_LOITER_SPEED_MAX_MPS = 2.0   # 이 속도 미만이면 체공(loiter) 행동으로 간주
_LAND_ALT_AGL_MAX_M = 30.0    # 이 고도 미만이면 착륙 접근 행동으로 간주
_CONFIDENCE_MATCH = 0.9
_CONFIDENCE_MISMATCH = 0.5


def _infer_behavioral(ground_speed_mps: float, alt_agl_m: float) -> str:
    if ground_speed_mps < _LOITER_SPEED_MAX_MPS:
        return "LOITER_ROI"
    if alt_agl_m < _LAND_ALT_AGL_MAX_M:
        return "LAND"
    return "WAYPOINT"


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    ms = raw["mission_status"]
    declared = _FLIGHT_MODE_TO_DECLARED.get(ms["flight_mode"], "WAYPOINT")
    behavioral = _infer_behavioral(ms["ground_speed_mps"], raw["environment"]["alt_agl_m"])

    match = declared == behavioral
    mission_phase_confidence = _CONFIDENCE_MATCH if match else _CONFIDENCE_MISMATCH
    state = "normal" if match else "anomaly"
    quality = 0.9

    payload = {
        "declared": declared,
        "behavioral": behavioral,
        "match": match,
        "mission_phase_confidence": mission_phase_confidence,
    }
    return make_output("mission_phase", state, quality, payload, previous_quality)
