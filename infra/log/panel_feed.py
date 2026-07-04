"""파이프라인 실데이터 → 대시보드 관측 패널(tick/signal) 계약 어댑터.

대시보드(#80)의 **UAV 기체 텔레메트리 패널**(#107)과 **신호 패널**(#106)은 현재
클라이언트 mock 으로 구동된다. 이 모듈은 실 파이프라인 출력을 대시보드 `/ws`
계약(`infra/dashboard/main.py` dispatch: type=tick / type=signal)의 메시지로 변환한다.

- `envelope_to_tick`  : 02 RawSensorEnvelope → `tick`(platform_state 9블록) — #107
- `abstraction_to_signals` : 03 AbstractionOutput.channels[] → per-channel `signal` — #106

전부 **순수 함수**(표준 라이브러리만, IO 없음). 온보드 파이프라인·raw 는 mutate 하지
않는다. 전송(WS send_json)은 유즈사이트(피더) 책임.

자세(attitude) 소스 정의 — #107 수용 기준:
- yaw  : navigation.imu.heading_deg (실측 — IMU/마그네토미터 융합값)
- roll/pitch : navigation.imu.accel_ms2 중력벡터에서 유도(정지/등속 가정) —
  roll = atan2(ay, az), pitch = atan2(-ax, hypot(ay, az)). `source` 필드에 명시.
- 각속도 p/q/r : navigation.imu.gyro_dps (실측 자이로).
수직속도(vs)는 사이클 간 alt 미분이라 단일 사이클 어댑터 범위 밖 → 미포함(baro alt 제공).
"""

from __future__ import annotations

import math

# 03 신호 패널이 기대하는 11채널 순서(대시보드 CHANNEL_DEFS 정합).
SIGNAL_CHANNEL_ORDER = (
    "position_consistency",
    "link_status",
    "rf_spectrum",
    "link_integrity",
    "encryption_status",
    "mission_phase",
    "terrain_class",
    "proximity_object",
    "acoustic_event",
    "obstacle_proximity",
    "operational_margin",
)


def abstraction_to_signals(correlation_id: str, seq: int, abstraction: dict) -> list[dict]:
    """03 abstraction.channels[] → 채널당 `signal` WS 메시지 리스트 (#106).

    각 메시지: {type:"signal", correlation_id, seq, channel, state, quality,
    quality_delta, payload}. dispatch 는 channel 키로 최신값을 캐시한다
    (latest-wins). 실제 채널만 방출 — 스텁/누락 채널은 건너뛴다.
    """
    channels = abstraction.get("channels") or []
    messages = []
    for ch in channels:
        if not isinstance(ch, dict):
            continue
        name = ch.get("channel")
        if name is None:
            continue
        messages.append(
            {
                "type": "signal",
                "correlation_id": correlation_id,
                "seq": seq,
                "channel": name,
                "state": ch.get("state", "normal"),
                "quality": ch.get("quality"),
                "quality_delta": ch.get("quality_delta", 0.0),
                "payload": ch.get("payload", {}),
            }
        )
    return messages


def _attitude_from_accel(accel) -> tuple[float | None, float | None]:
    """가속도계 중력벡터 → (roll_deg, pitch_deg). 정지/등속 가정.

    accel = [ax, ay, az] (m/s^2, 기체좌표). 값이 불완전하면 (None, None).
    """
    if not isinstance(accel, (list, tuple)) or len(accel) < 3:
        return None, None
    ax, ay, az = accel[0], accel[1], accel[2]
    try:
        roll = math.degrees(math.atan2(ay, az))
        pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))
    except (TypeError, ValueError):
        return None, None
    return round(roll, 3), round(pitch, 3)


def envelope_to_tick(correlation_id: str, seq: int, raw: dict) -> dict:
    """02 RawSensorEnvelope → `tick`(platform_state 9블록) WS 메시지 (#107).

    텔레메트리 9행(자세/각속도/배터리/GPS·INS/기압/속도/ESC/링크/NAV)을 raw
    센서 실측값으로 채운다. raw 는 읽기만 한다.
    """
    nav = raw.get("navigation") or {}
    gps = nav.get("gps") or {}
    imu = nav.get("imu") or {}
    baro = nav.get("baro") or {}
    airspeed = nav.get("airspeed") or {}
    wp = nav.get("waypoint_telemetry") or {}
    ew = raw.get("ew") or {}
    health = raw.get("health") or {}
    battery = health.get("battery") or {}
    link = raw.get("c2_link") or {}
    mission = raw.get("mission_status") or {}

    roll, pitch = _attitude_from_accel(imu.get("accel_ms2"))
    gyro = imu.get("gyro_dps") or [None, None, None]
    p, q, r = (gyro + [None, None, None])[:3]

    platform_state = {
        # 1. 자세(ATT) — yaw 실측 + roll/pitch 가속도 유도(소스 명시).
        "attitude": {
            "roll_deg": roll,
            "pitch_deg": pitch,
            "yaw_deg": imu.get("heading_deg"),
            "source": "yaw=imu.heading_deg(meas); roll/pitch=accel_ms2-derived",
        },
        # 2. 각속도(GYRO) — 자이로 실측.
        "angular_rates": {"p_dps": p, "q_dps": q, "r_dps": r},
        # 3. 배터리(BATT).
        "battery": {
            "voltage_v": battery.get("voltage_v"),
            "current_a": battery.get("current_a"),
            "pct": battery.get("pct"),
            "temp_c": battery.get("temp_c"),
        },
        # 4. GPS/INS.
        "gps": {
            "lat": gps.get("lat"),
            "lon": gps.get("lon"),
            "alt_m": gps.get("alt_m"),
            "satellites": ew.get("satellite_count"),
            "hdop": gps.get("hdop"),
            "vdop": gps.get("vdop"),
            "fix_confidence": ew.get("gnss_confidence"),
        },
        # 5. 기압고도(BARO).
        "baro": {"alt_m": baro.get("alt_m"), "pressure_pa": baro.get("pressure_pa")},
        # 6. 속도(SPD).
        "speed": {
            "ground_mps": mission.get("ground_speed_mps"),
            "airspeed_mps": airspeed.get("airspeed_mps"),
        },
        # 7. 모터/ESC.
        "esc": {
            "motor_rpm": health.get("motor_rpm"),
            "motor_temp_c": health.get("motor_temp_c"),
            "vibration": health.get("imu_vibration"),
        },
        # 8. C2 링크(LINK).
        "link": {
            "rssi_dbm": link.get("rssi_dbm"),
            "noise_floor_dbm": link.get("noise_floor_dbm"),
            "latency_ms": link.get("latency_ms"),
            "packet_loss_rate": link.get("packet_loss_rate"),
        },
        # 9. NAV(컴퍼스/홈).
        "nav": {
            "heading_deg": imu.get("heading_deg"),
            "current_waypoint": wp.get("current_wp", mission.get("current_waypoint")),
            "total_wp": wp.get("total_wp"),
            "distance_to_target_m": mission.get("distance_to_target_m"),
            "distance_to_base_m": mission.get("distance_to_base_m"),
        },
    }
    return {
        "type": "tick",
        "correlation_id": correlation_id,
        "seq": seq,
        "platform_state": platform_state,
    }


def cycle_to_panel_messages(correlation_id: str, seq: int, raw: dict, result: dict) -> list[dict]:
    """한 사이클(raw + run_cycle result) → 관측 패널 WS 메시지 리스트.

    피더 유즈사이트용 통합 헬퍼: tick 1건(#107) + signal N건(#106, 03 abstraction
    채널당). 대시보드 `/ws` 에 순서대로 send_json 하면 된다. `cycle_to_log_entries`
    (시스템 로그)와 상호보완 — 그건 텍스트 로그, 이건 구조화 패널 데이터.
    """
    messages = [envelope_to_tick(correlation_id, seq, raw)]
    abstraction = result.get("abstraction")
    if isinstance(abstraction, dict):
        messages.extend(abstraction_to_signals(correlation_id, seq, abstraction))
    return messages
