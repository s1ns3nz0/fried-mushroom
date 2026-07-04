"""02. UAV Sensor Layer — 원시 센서 envelope 스키마.

레이어 간 통신은 JSON-직렬화 가능한 dict 로만 (CLAUDE.md). 여기서는 IDE 힌트용
TypedDict 만 제공하고 런타임 검증은 없다 (ADR-004). 카테고리별 하위 필드는 dict 로
두고, 각 필드명은 03 Sensor Abstraction Layer 의 "02 → 03 매핑" 표와 A-1 문서의
채널 payload 스펙에서 역추적한 것이다 (step2 지시서).
"""

from typing import TypedDict


class RawSensorEnvelope(TypedDict):
    """한 사이클의 원시 센서 데이터 묶음.

    카테고리 8종(02 원문)에 더해 lidar 는 03 obstacle_proximity 가 요구하는 항목이라
    별도 인정(02 문서 각주: 하드웨어 확정 시 보완 필요).
    """

    sortie_id: str
    seq: int
    ts_ms: int
    imagery: dict            # EO/IR raw frame refs, gimbal_deg, (mock) 객체 라벨 hint
    navigation: dict         # gps, imu, baro, magnetometer, airspeed, waypoint_telemetry
    c2_link: dict            # rssi_dbm, noise_floor_dbm, freq_mhz, packet_loss_rate, latency_ms, checksum_fail_rate, seq_gap_count, encryption_mode, downgrade_detected
    ew: dict                 # gnss_confidence, gnss_position_jump_m, satellite_count, cn0_avg_db, rf_wideband_scan, rf_bearing_deg
    health: dict             # battery(voltage_v, current_a, pct, temp_c), motor_rpm[], motor_temp_c, imu_vibration, failsafe_state
    acoustic: dict           # mic_waveform_ref, peak_db, rise_time_ms, bandwidth_hz, bearing_deg
    environment: dict        # wind_ms, wind_dir_deg, temp_c, alt_agl_m, dem_ref
    mission_status: dict     # current_waypoint, mission_current, flight_mode, ground_speed_mps, distance_to_target_m, distance_to_base_m
    lidar: dict              # distance_m, closure_rate_mps (03 obstacle_proximity 가 소비)


# RawSensorEnvelope 의 필수 최상위 키 (테스트/검증용).
REQUIRED_KEYS: tuple[str, ...] = (
    "sortie_id",
    "seq",
    "ts_ms",
    "imagery",
    "navigation",
    "c2_link",
    "ew",
    "health",
    "acoustic",
    "environment",
    "mission_status",
    "lidar",
)
