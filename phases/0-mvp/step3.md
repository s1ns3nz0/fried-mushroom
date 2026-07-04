# Step 3: layer-03-deterministic-channels

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-003)
- `/src/onboard/shared/schemas.py` (Step 1 산출물, `ChannelOutput`, `AbstractionOutput`)
- `/src/onboard/shared/constants.py` (Step 1 산출물, `QUALITY_DELTA_DROP_THRESHOLD`, `TIME_TO_COLLISION_THRESHOLD_S`)
- `/src/onboard/layer_02_sensor/schema.py` (Step 2 산출물, `RawSensorEnvelope`)
- `/src/onboard/layer_02_sensor/mock_source.py` (Step 2 산출물, 어떤 원시 필드가 실제로 들어오는지 확인)
- `/examples/raw_t3.json`, `/examples/raw_t4.json`, `/examples/raw_t7.json` (Step 2 산출물, 이 데이터를 소비할 수 있어야 한다)

D4D 원문 문서 (레포 내 `/docs/D4D/`):

- `/docs/D4D/03. Sensor Abstraction Layer.md` — 각 채널별 입력·처리·출력 스펙, quality/state/quality_delta 정의, 구동 빈도(상시/트리거/저빈도) 이 step에서는 전부 상시 실행으로 처리한다.
- `/docs/D4D/A-1. 추상 결과 세부 내용.md` — payload 필드 최종 확정본

## 작업

03 Sensor Abstraction Layer의 결정론적 채널 9개를 구현한다. AI가 필수인 3채널(proximity_object, terrain_class 카메라 보조, acoustic_event 2차 YAMNet)은 다음 step에서 다룬다. `acoustic_event`의 1차 임계값 매칭만 이 step에서 다루고, 결과가 애매하면 `detection_stage="threshold_only"`로 두면 된다 (2차 판정은 step 4).

### 1) 채널별 모듈 스켈레톤

각 파일에 `def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput`을 노출한다. `previous_quality`가 있으면 `quality_delta = quality - previous_quality`로 계산, 없으면 0.0.

파일 목록 (전부 `src/onboard/layer_03_abstraction/` 하위):

- `position_consistency.py` — GPS lat/lon/alt와 IMU 관성항법 추정치의 잔차(빼셈). 임계값(`threshold_m`) 초과 시 `state="anomaly"`. `payload = {gps_imu_residual_m, baro_residual_m, airspeed_residual_ms, threshold_m, hdop, vdop, satellite_count, cn0_avg_db}`. GPS/IMU 두 위치 벡터 차이는 대충 haversine 근사 (온보드 정밀도 요구 낮음 — MVP에선 lat/lon 차이를 미터로 스케일링하는 상수 곱셈 근사도 허용). threshold_m=5.0 상수.
- `link_status.py` — `payload.rssi_dbm, noise_floor_dbm, freq_mhz, packet_loss_rate, latency_ms`. `state`는 `rssi_dbm - noise_floor_dbm`가 20 미만이거나 packet_loss_rate > 5% 이면 anomaly, 15~20 사이면 degraded, else normal.
- `link_integrity.py` — `payload.checksum_fail_rate, seq_gap_count`. `state`는 checksum_fail_rate > 0.05 or seq_gap_count > 0 이면 anomaly.
- `encryption_status.py` — `payload.mode, downgrade_detected`. `state=anomaly` if `downgrade_detected`.
- `rf_spectrum.py` — 광대역 스캔이 threshold 초과면 `wideband_anomaly=True`. `payload.wideband_anomaly, bearing_deg`. anomaly 여부는 raw ew.rf_wideband_scan의 max/median 비율 등 간단한 결정론적 판정 (구체 임계값은 D4D 문서에 없으니 함수 내부 상수로 두고 주석에 "MVP placeholder"로 명시).
- `mission_phase.py` — 입력: `mission_status.mission_current, flight_mode`(declared), `ground_speed_mps, imu, gimbal_deg`(behavioral). `payload.declared, behavioral, match, mission_phase_confidence`. behavioral 추론은 간단한 규칙 (예: `ground_speed_mps < 1 → LOITER_ROI`, `alt_agl_m < 30 and descending → LAND`). match=(declared==behavioral). confidence는 match=True면 0.9, False면 0.5.
- `obstacle_proximity.py` — `payload.distance_m, closure_rate_mps`. state=anomaly if `distance_m / closure_rate_mps < TIME_TO_COLLISION_THRESHOLD_S` (0으로 나눔 방지: closure_rate<=0이면 normal).
- `operational_margin.py` — 5개 하위상태 산출 후 worst-case 집계. `payload = {battery_pct, battery_state, weather_state, mechanical_state, link_margin_state, time_margin_state, overall, worst_factor, failsafe_state, diagnostics}`. 각 하위상태는 임계값 룰(예: battery_pct < 20% → critical, < 40% → warning). `overall`은 최악. failsafe_state는 raw health.failsafe_state 그대로 전달.
- `acoustic_event.py` (1차) — `payload.event_type, detection_stage, peak_db, bearing_deg`. 결정: `peak_db > 90` and `rise_time_ms < 3` → `event_type="gunshot"`, `detection_stage="threshold_only"`, `state="anomaly"`. 애매 케이스(peak_db 75~90 등)는 `event_type="ambiguous"`, `detection_stage="threshold_only"`, `state="degraded"`. step 4에서 YAMNet 2차 승격이 이 값을 덮어쓴다.

각 채널의 `quality`는 raw 데이터의 신뢰도 대리값(예: link_status의 quality는 packet_loss_rate가 낮을수록 1에 가깝게). 저시정·저조도 등 이번 step 범위 밖 요인은 무시.

### 2) 오케스트레이터 `src/onboard/layer_03_abstraction/run.py`

```python
def run(raw: RawSensorEnvelope,
        previous_qualities: dict[str, float] | None = None) -> AbstractionOutput:
    """
    9개 결정론 채널을 실행해 AbstractionOutput 반환.
    proximity_object, terrain_class, acoustic 2차 YAMNet 채널은 다음 step에서 추가된다.
    """
```

`schema_version="1.0"`, `id=f"{raw['sortie_id']}-{raw['seq']}"`, `ts=raw['ts_ms']`. `channels`는 리스트로 채널당 하나씩 append.

`previous_qualities`는 채널명 → 이전 quality. 채널 처리 시 그 채널 이름으로 조회. 없으면 None → quality_delta=0.

### 3) 테스트

`tests/layer_03_abstraction/test_deterministic_channels.py`:

- 정상 envelope(`build_normal_envelope`)을 넣으면 9개 채널 모두 `state="normal"`
- `examples/raw_t3.json`을 넣으면 `acoustic_event`가 `event_type="gunshot"`, `state="anomaly"`
- `examples/raw_t4.json`을 넣으면 `link_status.state ∈ {"anomaly", "degraded"}`, `mission_phase.match=False`
- `examples/raw_t7.json`을 넣으면 `obstacle_proximity.state="anomaly"` and `distance_m/closure_rate_mps < 3.0`
- `previous_qualities={"proximity_object": 0.9}`으로 넘긴 뒤 이번 quality=0.5면 `quality_delta = -0.4` (아직 proximity_object 채널 없어서 이 테스트는 `acoustic_event`나 `link_status`로 대체)

`tests/layer_03_abstraction/test_envelope_shape.py`:

- 반환값 `AbstractionOutput` 최상위 키가 `{schema_version, id, ts, channels}`뿐이다 (추가 필드 없음)
- 각 channel dict가 `{channel, state, quality, quality_delta, payload}` 다섯 키를 가진다
- `id`가 `"{sortie_id}-{seq}"` 형식이다

## Acceptance Criteria

```bash
python3 -m pytest tests/layer_03_abstraction/ -v
```

- 모든 테스트 PASSED
- 9채널 반환 (proximity_object, terrain_class, acoustic YAMNet 2차는 없음)

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - 채널당 파일 1개로 분리했는가?
   - `run.py`가 채널을 직접 계산하지 않고 각 채널 모듈만 호출하는가?
   - AI 호출이 이 step에 없는가? (`ai_stubs/` import 금지)
3. 결과에 따라 `phases/0-mvp/index.json`의 step 3을 업데이트한다.

## 금지사항

- `ai_stubs/`에서 import 하지 마라. 이유: 이 step은 결정론 전용. AI stub은 다음 step.
- `proximity_object.py`, `terrain_class.py`, `acoustic_event.py`의 YAMNet 2차 로직을 만들지 마라. 이유: step 4의 몫.
- 채널 하나에서 다른 채널을 직접 import 하지 마라. 이유: 채널은 독립 처리. cross-channel 로직은 04 이후 계층에서만.
- `raw` dict의 원본을 mutate 하지 마라. 이유: 파이프라인 순수성 유지 (ARCHITECTURE.md "패턴").
- 실제 haversine 라이브러리를 도입하지 마라. 이유: 표준 라이브러리와 근사식으로 충분.
