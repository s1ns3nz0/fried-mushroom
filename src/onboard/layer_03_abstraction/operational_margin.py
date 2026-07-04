"""operational_margin — 🔵 결정론적 worst-case 집계 (위협채널 아님).

배터리/기상/기계/통신마진/시간마진 5개 하위상태 중 최악을 overall 로 채택한다.
failsafe_state 는 이산 안전상태라 worst-case 집계에서 분리해 그대로 노출(A-1).
임계값은 D4D 문서에 확정치가 없어 내부 상수로 둔다 (MVP placeholder).
"""

from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

_ORDER = {"sufficient": 0, "limited": 1, "critical": 2}
_MARGIN_STATE_TO_CHANNEL_STATE = {
    "sufficient": "normal",
    "limited": "degraded",
    "critical": "anomaly",
}


def _band(value: float, limited_at: float, critical_at: float, higher_is_worse: bool) -> str:
    """value 를 sufficient/limited/critical 로 분류."""
    if higher_is_worse:
        if value >= critical_at:
            return "critical"
        if value >= limited_at:
            return "limited"
    else:
        if value <= critical_at:
            return "critical"
        if value <= limited_at:
            return "limited"
    return "sufficient"


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    health = raw["health"]
    env = raw["environment"]
    c2 = raw["c2_link"]
    battery_pct = health["battery"]["pct"]

    substates = {
        "battery": _band(battery_pct, 40, 20, higher_is_worse=False),
        "weather": max(
            _band(env["wind_ms"], 10, 15, higher_is_worse=True),
            _band(env["temp_c"], 0, -10, higher_is_worse=False),
            key=lambda s: _ORDER[s],
        ),
        "mechanical": max(
            _band(health["motor_temp_c"], 70, 90, higher_is_worse=True),
            _band(health["imu_vibration"], 0.3, 0.5, higher_is_worse=True),
            key=lambda s: _ORDER[s],
        ),
        "link": _band(c2["packet_loss_rate"], 0.03, 0.10, higher_is_worse=True),
        "time": "sufficient",  # 임무경과/일몰 데이터 없음 — MVP placeholder
    }

    worst_factor = max(substates, key=lambda k: _ORDER[substates[k]])
    overall = substates[worst_factor]

    payload = {
        "battery_pct": battery_pct,
        "battery_state": substates["battery"],
        "weather_state": substates["weather"],
        "mechanical_state": substates["mechanical"],
        "link_margin_state": substates["link"],
        "time_margin_state": substates["time"],
        "overall": overall,
        "worst_factor": worst_factor,
        "failsafe_state": health["failsafe_state"],
        "diagnostics": {
            "motor_rpm": health["motor_rpm"],
            "motor_temp_c": health["motor_temp_c"],
            "vibration_level": health["imu_vibration"],
            "ambient_temp_c": env["temp_c"],
        },
    }
    state = _MARGIN_STATE_TO_CHANNEL_STATE[overall]
    return make_output("operational_margin", state, 1.0, payload, previous_quality)
