# AbstractionOutput (+ ChannelOutput)

03(Sensor Abstraction Layer)이 원시 센서 데이터를 11개 의미론적 채널로 재구성한 사이클 단위 출력. 04(Threat Modeling)의 Step A~D 입력이다.

- **생산 레이어**: 03 Sensor Abstraction Layer
- **소비 레이어**: 04 Threat Modeling

## ChannelOutput — 채널 배열 원소

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `channel` | `str` | 필수 | 채널명(예: `position_consistency`, `proximity_object` 등 11종) |
| `state` | `Literal["normal", "degraded", "anomaly"]` | 필수 | `normal`(정상범위) / `degraded`(측정은 되나 신뢰도 낮음) / `anomaly`(값 자체가 위협 신호) |
| `quality` | `float` | 필수 | 0.0(신뢰불가)~1.0(완전신뢰). **판독기/모델 건전성**(센서 자체 신뢰도 또는 AI 모델 확신도)이며 **위협 크기와 분리**한다. 04의 채널 가중치 계산에 그대로 반영. 결정론적 프로토콜 판독 채널(`encryption_status`, `link_integrity`)은 이상(anomaly)이어도 판독 신뢰도가 떨어지는 게 아니므로 quality를 낮추지 않고, 이상 **증거**는 `state`/`payload`로만 전달한다(quality에 위협 강도를 인코딩하면 04 Q_MIN 게이트가 실제 이상신호를 필터해 T2가 종단 미탐지됨 — 이슈 #28). 계측기 자체가 손상돼 판독을 못 하는 경우(예: 무결성 샘플 부족·링크 두절)에만 degraded로 quality를 낮춘다. |
| `quality_delta` | `float` | 필수 | 전 사이클 대비 `quality` 변화량(`quality(t) - quality(t-1)`, 첫 사이클은 0.0). 04가 T5(레이저) 판정에 사용(-0.3 미만이면 매칭) |
| `payload` | `dict` | 필수 | 채널별 세부 필드. 채널마다 스키마가 달라 `schemas.py`는 dict로만 선언 — 채널별 payload 필드 상세는 [`A-1. 추상 결과 세부 내용`](../D4D/A-1.%20추상%20결과%20세부%20내용.md) 참고 |

## AbstractionOutput — 사이클 envelope

| 필드 | 타입 | 필수 | 의미 |
|---|---|---|---|
| `schema_version` | `str` | 필수 | 스키마 버전 고정값(`"1.0"`) |
| `id` | `str` | 필수 | `{sortie_id}-{순번}` 형태. 사이클마다 순번이 1씩 증가 |
| `ts` | `int` | 필수 | 이 사이클이 생성된 시각(epoch 밀리초) |
| `channels` | `list[ChannelOutput]` | 필수 | 11개 채널 결과 배열 |

## 예시 JSON

[`A-1. 추상 결과 세부 내용`](../D4D/A-1.%20추상%20결과%20세부%20내용.md)의 골든 예시(T3+저시정 시나리오)를 그대로 인용한다.

```json
{
  "schema_version": "1.0",
  "id": "GIREOGI-0704-01-4471",
  "ts": 1730620801200,
  "channels": [
    { "channel": "position_consistency", "state": "normal", "quality": 0.95, "quality_delta": 0.0,
      "payload": { "gps_imu_residual_m": 0.8, "baro_residual_m": 0.3, "airspeed_residual_ms": 0.4, "threshold_m": 5.0, "hdop": 0.9, "vdop": 1.2, "satellite_count": 11, "cn0_avg_db": 42.5 } },

    { "channel": "link_status", "state": "normal", "quality": 0.90, "quality_delta": 0.0,
      "payload": { "rssi_dbm": -62, "noise_floor_dbm": -95, "freq_mhz": 915.0, "packet_loss_rate": 0.01, "latency_ms": 45 } },

    { "channel": "rf_spectrum", "state": "normal", "quality": 0.80, "quality_delta": 0.0,
      "payload": { "wideband_anomaly": false, "bearing_deg": null } },

    { "channel": "link_integrity", "state": "normal", "quality": 0.99, "quality_delta": 0.0,
      "payload": { "checksum_fail_rate": 0.0, "seq_gap_count": 0 } },

    { "channel": "encryption_status", "state": "normal", "quality": 0.99, "quality_delta": 0.0,
      "payload": { "mode": "AES256", "downgrade_detected": false } },

    { "channel": "mission_phase", "state": "normal", "quality": 0.90, "quality_delta": 0.0,
      "payload": { "declared": "LOITER_ROI", "behavioral": "loiter_pattern", "match": true, "mission_phase_confidence": 0.9 } },

    { "channel": "terrain_class", "state": "degraded", "quality": 0.55, "quality_delta": -0.05,
      "payload": { "dominant_class": "open_field", "source": "camera_verified", "gis_last_updated": "2025-11", "camera_mismatch": true, "exposure_score": 0.72, "risk_map_ref": "buf://terrain_seg/4471", "optimal_terrain_bearing_deg": null, "lowest_exposure_bearing_deg": null } },

    { "channel": "proximity_object", "state": "anomaly", "quality": 0.55, "quality_delta": -0.05,
      "payload": { "class": "person", "weapon_shape": true, "bearing_deg": 142.3, "closing": true, "closure_rate_mps": 3.2, "degraded_reason": "low_visibility" } },

    { "channel": "acoustic_event", "state": "anomaly", "quality": 0.92, "quality_delta": 0.0,
      "payload": { "event_type": "gunshot", "detection_stage": "threshold_only", "peak_db": 118, "bearing_deg": 139.8 } },

    { "channel": "obstacle_proximity", "state": "normal", "quality": 0.85, "quality_delta": 0.0,
      "payload": { "distance_m": null, "closure_rate_mps": null } },

    { "channel": "operational_margin", "state": "degraded", "quality": 1.0, "quality_delta": 0.0,
      "payload": { "battery_pct": 65, "battery_state": "sufficient", "weather_state": "limited", "mechanical_state": "sufficient", "link_margin_state": "sufficient", "time_margin_state": "sufficient", "overall": "limited", "worst_factor": "weather", "failsafe_state": "ready", "diagnostics": { "motor_rpm": [8200, 8150, 8190, 8175], "motor_temp_c": 42.0, "vibration_level": 0.12, "ambient_temp_c": -3.5 } } }
  ]
}
```

## 관련 상수

이 계약 자체는 `constants.py` 상수를 직접 참조하지 않는다. 채널 payload 값이 04에서 위협으로 매핑되는 조건표는 [`constants.py`](../../src/onboard/shared/constants.py)의 `SIGNAL_TO_THREAT`, `T4_MULTI_CHANNEL_CONDITIONS`를 참고(04 계약 문서에서 다룸).

## 내비게이션

◀ [이전 MissionBrief](./01-mission-brief.md) | [다음 ▶ ThreatModelingOutput](./04-threat-modeling-output.md)

## 소스

- 스키마: [`src/onboard/shared/schemas.py`](../../src/onboard/shared/schemas.py) — `ChannelOutput`, `AbstractionOutput`
- 상세 스펙: [`docs/D4D/03. Sensor Abstraction Layer.md`](../D4D/03.%20Sensor%20Abstraction%20Layer.md), [`docs/D4D/A-1. 추상 결과 세부 내용.md`](../D4D/A-1.%20추상%20결과%20세부%20내용.md)
