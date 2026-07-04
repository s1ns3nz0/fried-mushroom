"""02. UAV Sensor Layer — 결정론적 mock 소스.

원시 센서 데이터를 손으로 세팅한 고정값으로 생성한다. 실제 데이터셋 다운로드는
MVP 스코프 밖(step2 금지사항). 난수를 쓰지 않으므로 같은 (seq, ts_ms) 로 몇 번을
호출해도 결과가 동일하다 — 골든 fixture 회귀 테스트를 위한 결정론 보장.

이 레이어는 원시 데이터 생성만 한다. state/quality 판정, 잔차/충돌예상시간 계산 등은
03 Sensor Abstraction Layer 이후의 몫(step2 금지사항). 다만 시나리오 값은 04
Threat Modeling 의 SIGNAL_TO_THREAT / T4 다중조건 임계값을 실제로 통과하도록 심는다.
"""

import copy

from onboard.layer_02_sensor.schema import RawSensorEnvelope

SCHEMA_SCENARIOS: tuple[str, ...] = ("t1", "t2", "t3", "t4", "t5", "t6", "t7")

# imagery 에 심는 mock 객체 라벨 hint. 03 proximity_object(AI 채널) stub 이 그대로 읽어
# class/weapon_shape/closing 을 산출한다 (step2: mock 라벨 필드를 심어둔다).
_NORMAL_OBJECT_LABEL = {
    "class": "none",
    "weapon_shape": False,
    "closing": False,
    "closure_rate_mps": 0.0,
    "bearing_deg": None,
    "degraded_reason": None,
}


def build_normal_envelope(sortie_id: str, seq: int, ts_ms: int) -> RawSensorEnvelope:
    """모든 채널이 normal 상태가 되도록 안전한 기본값을 반환한다."""
    return {
        "sortie_id": sortie_id,
        "seq": seq,
        "ts_ms": ts_ms,
        "imagery": {
            "eo_frame_ref": "buf://eo/normal",
            "ir_frame_ref": "buf://ir/normal",
            "gimbal_deg": {"az": 0.0, "el": -30.0},
            # 03 proximity_object / terrain_class stub 이 소비하는 mock 라벨 hint
            "object_label": copy.deepcopy(_NORMAL_OBJECT_LABEL),
            "terrain_label": {"dominant_class": "open_field", "camera_mismatch": False},
        },
        "navigation": {
            "gps": {"lat": 37.5, "lon": 127.0, "alt_m": 150.0, "hdop": 0.8, "vdop": 1.2},
            # IMU 관성항법 추정치 — 정상시 GPS 와 근접(잔차 작음).
            "imu": {
                "est_lat": 37.5,
                "est_lon": 127.0,
                "accel_ms2": [0.0, 0.0, 9.81],
                "gyro_dps": [0.0, 0.0, 0.0],
                "heading_deg": 90.0,
                "est_speed_mps": 18.0,
            },
            "baro": {"pressure_pa": 99500.0, "alt_m": 150.2},
            "magnetometer": {"heading_deg": 90.0, "mag_field": [0.21, 0.01, 0.42]},
            "airspeed": {"airspeed_mps": 18.5},
            "waypoint_telemetry": {"current_wp": 3, "total_wp": 8},
        },
        "c2_link": {
            "rssi_dbm": -60,
            "noise_floor_dbm": -95,
            "freq_mhz": 915.0,
            "packet_loss_rate": 0.001,
            "latency_ms": 40,
            "checksum_fail_rate": 0.0,
            "seq_gap_count": 0,
            "encryption_mode": "AES256",
            "downgrade_detected": False,
        },
        "ew": {
            "gnss_confidence": 0.98,
            "gnss_position_jump_m": 0.0,
            "satellite_count": 12,
            "cn0_avg_db": 44.0,
            "rf_wideband_scan": {"wideband_anomaly": False},
            "rf_bearing_deg": None,
        },
        "health": {
            "battery": {"voltage_v": 25.0, "current_a": 30.0, "pct": 78, "temp_c": 35},
            "motor_rpm": [8200, 8150, 8190, 8175],
            "motor_temp_c": 42.0,
            "imu_vibration": 0.12,
            "failsafe_state": "ready",
        },
        "acoustic": {
            "mic_waveform_ref": "buf://mic/normal",
            "peak_db": 55.0,
            "rise_time_ms": 40.0,
            "bandwidth_hz": 2000.0,
            "bearing_deg": None,
        },
        "environment": {
            "wind_ms": 3.0,
            "wind_dir_deg": 270.0,
            "temp_c": 15.0,
            "alt_agl_m": 150.0,
            "dem_ref": "buf://dem/normal",
        },
        "mission_status": {
            "current_waypoint": 3,
            "mission_current": 3,
            "flight_mode": "AUTO",  # → 03 mission_phase declared=WAYPOINT
            "ground_speed_mps": 18.0,
            "distance_to_target_m": 1200.0,
            "distance_to_base_m": 2400.0,
        },
        "lidar": {"distance_m": None, "closure_rate_mps": None},
    }


def build_scenario_envelope(scenario_id: str, seq: int, ts_ms: int) -> RawSensorEnvelope:
    """scenario_id ∈ {"t3", "t4", "t7"} — 각 시나리오의 이상 값을 주입한다.

    normal baseline 에서 시작해 해당 시나리오가 04 SIGNAL_TO_THREAT / T4 조건을
    통과하는 데 필요한 필드만 덮어쓴다.
    """
    if scenario_id not in SCHEMA_SCENARIOS:
        raise ValueError(
            f"unknown scenario_id={scenario_id!r}, expected one of {SCHEMA_SCENARIOS}"
        )

    env = build_normal_envelope(f"scenario-{scenario_id}", seq, ts_ms)

    if scenario_id == "t1":
        # GPS 스푸핑(T1): GPS 보고 위치가 IMU 관성 추정과 크게 어긋남
        # → 03 position_consistency gps_imu_residual_m > 5.0 (anomaly).
        # rf 광대역 이상은 rf_spectrum T1 보조 신호(SIGNAL_TO_THREAT).
        env["navigation"]["gps"].update(
            {"lat": 37.5006, "lon": 127.0006, "hdop": 1.9, "vdop": 2.4}
        )  # imu est_lat/lon=37.5/127.0 → 잔차 ≈ 90m
        env["ew"].update(
            {
                "gnss_confidence": 0.32,
                "gnss_position_jump_m": 88.0,
                "satellite_count": 5,
                "cn0_avg_db": 27.0,
                "rf_wideband_scan": {"wideband_anomaly": True},
                "rf_bearing_deg": 210.0,
            }
        )
        env["mission_status"]["flight_mode"] = "AUTO"

    elif scenario_id == "t2":
        # 사이버/C2 하이재킹(T2): 암호 다운그레이드(encryption_status anomaly)
        # + 링크 무결성 손상(link_integrity: checksum_fail_rate>0.05 OR seq_gap_count>0).
        env["c2_link"].update(
            {
                "encryption_mode": "NONE",
                "downgrade_detected": True,
                "checksum_fail_rate": 0.12,
                "seq_gap_count": 3,
                "packet_loss_rate": 0.08,
                "latency_ms": 260,
            }
        )
        env["mission_status"]["flight_mode"] = "AUTO"

    elif scenario_id == "t3":
        # 근접 소화기: 사람+무기 형태(proximity_object T3) + 총성(acoustic_event T3),
        # declared_phase=LOITER_ROI 유도.
        env["imagery"]["object_label"] = {
            "class": "person",
            "weapon_shape": True,
            "closing": True,
            "closure_rate_mps": 3.2,
            "bearing_deg": 142.3,
            "degraded_reason": None,
        }
        # 총성 결정론 기준: peak_db > 90 AND rise_time_ms < 3.
        env["acoustic"].update(
            {
                "mic_waveform_ref": "buf://mic/gunshot",
                "peak_db": 118.0,
                "rise_time_ms": 1.5,
                "bandwidth_hz": 6000.0,
                "bearing_deg": 139.8,
            }
        )
        env["mission_status"]["flight_mode"] = "LOITER"  # → declared=LOITER_ROI
        env["mission_status"]["ground_speed_mps"] = 0.5
        env["navigation"]["imu"]["est_speed_mps"] = 0.5

    elif scenario_id == "t4":
        # 물리 포획(T4 3조건 동시): person+closing / 선언-행동 mismatch / link anomaly.
        env["imagery"]["object_label"] = {
            "class": "person",
            "weapon_shape": False,
            "closing": True,
            "closure_rate_mps": 2.5,
            "bearing_deg": 95.0,
            "degraded_reason": None,
        }
        # declared=WAYPOINT(AUTO, cruise 기대) 이지만 실제 행동은 loiter → mission_phase match=False.
        env["mission_status"]["flight_mode"] = "AUTO"  # declared=WAYPOINT
        env["mission_status"]["ground_speed_mps"] = 1.5  # cruise 아님(행동 불일치)
        env["navigation"]["imu"].update({"est_speed_mps": 1.5, "gyro_dps": [0.0, 0.0, 25.0]})
        # link_status state=anomaly 유발: rssi_dbm < -95.
        env["c2_link"].update({"rssi_dbm": -98, "packet_loss_rate": 0.25, "latency_ms": 320})

    elif scenario_id == "t7":
        # 지형충돌/CFIT: obstacle_proximity 충돌예상시간 = 15.0/8.0 = 1.875s < 3.0s.
        env["lidar"] = {"distance_m": 15.0, "closure_rate_mps": 8.0}
        env["mission_status"]["flight_mode"] = "LAND"  # → declared=LAND
        env["mission_status"]["ground_speed_mps"] = 4.0
        env["environment"]["alt_agl_m"] = 20.0
        env["navigation"]["gps"]["alt_m"] = 40.0
        env["navigation"]["imu"]["est_speed_mps"] = 4.0

    elif scenario_id == "t5":
        # 레이저/광학 교란(T5): 카메라 세그멘테이션 확신도 급락(1.0→0.65) →
        # 03 terrain_class quality 하락 → 사이클 간 quality_delta < -0.3 → T5 신호.
        env["imagery"]["terrain_label"] = {
            "dominant_class": "open_field",
            "camera_confidence": 0.65,
        }

    elif scenario_id == "t6":
        # 배경 환경노출도(T6) + camera_verified 경로: GIS 는 forest(은폐 양호)로 알고
        # 있으나 카메라 세그멘테이션이 open_field(벌목 등 최근 지형변화) 감지 → 불일치.
        # 03 terrain_class: source=camera_verified, dominant_class=open_field(카메라 우선),
        # exposure_score=0.8 → 04 background_exposure_score 로 흐른다. 위협 채널은 정상.
        env["environment"]["mock_gis_class"] = "forest"
        env["imagery"]["terrain_label"] = {
            "dominant_class": "open_field",
            "camera_mismatch": True,
        }

    return env
