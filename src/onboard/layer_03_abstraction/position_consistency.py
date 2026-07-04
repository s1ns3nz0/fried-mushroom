"""position_consistency — 🔵 결정론.

GPS 위치를 IMU 관성항법 추정치·기압고도와 대조해 스푸핑 여부를 판정한다.
잔차 계산은 표준 라이브러리 근사(haversine)만 사용 (외부 라이브러리 금지, step3).
"""

import math

from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

THRESHOLD_M = 5.0
_M_PER_DEG = 111_320.0  # 위도 1도 ≈ 111.32km (경도는 cos(lat) 보정)


def _haversine_approx_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """온보드 저정밀 근사: lat/lon 차이를 미터로 스케일링."""
    dlat_m = (lat1 - lat2) * _M_PER_DEG
    dlon_m = (lon1 - lon2) * _M_PER_DEG * math.cos(math.radians(lat1))
    return math.hypot(dlat_m, dlon_m)


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    nav = raw["navigation"]
    gps, imu, baro, airspeed = nav["gps"], nav["imu"], nav["baro"], nav["airspeed"]
    ew = raw["ew"]

    gps_imu_residual_m = _haversine_approx_m(
        gps["lat"], gps["lon"], imu["est_lat"], imu["est_lon"]
    )
    baro_residual_m = abs(gps["alt_m"] - baro["alt_m"])
    airspeed_residual_ms = abs(imu["est_speed_mps"] - airspeed["airspeed_mps"])

    hdop, vdop = gps["hdop"], gps["vdop"]
    satellite_count, cn0_avg_db = ew["satellite_count"], ew["cn0_avg_db"]

    if gps_imu_residual_m > THRESHOLD_M or baro_residual_m > THRESHOLD_M:
        state = "anomaly"
    elif satellite_count < 6 or hdop > 2.0:
        state = "degraded"
    else:
        state = "normal"

    # quality: HDOP·위성 수 기반 신뢰도 대리값 (MVP proxy).
    quality = 1.0 - hdop * 0.1 - max(0, 6 - satellite_count) * 0.05

    payload = {
        "gps_imu_residual_m": round(gps_imu_residual_m, 3),
        "baro_residual_m": round(baro_residual_m, 3),
        "airspeed_residual_ms": round(airspeed_residual_ms, 3),
        "threshold_m": THRESHOLD_M,
        "hdop": hdop,
        "vdop": vdop,
        "satellite_count": satellite_count,
        "cn0_avg_db": cn0_avg_db,
    }
    return make_output("position_consistency", state, quality, payload, previous_quality)
