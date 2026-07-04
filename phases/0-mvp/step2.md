# Step 2: layer-02-mock-sensor

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/CLAUDE.md`
- `/docs/ARCHITECTURE.md`
- `/docs/ADR.md` (ADR-005)
- `/src/onboard/shared/schemas.py` (Step 1 산출물, `MissionBrief` 참고)
- `/src/onboard/shared/constants.py` (Step 1 산출물)

D4D 원문 문서 (레포 내 `/docs/D4D/`):

- `/docs/D4D/02. UAV Sensor Layer.md` — 8개 원시 데이터 카테고리, 각 카테고리 필드
- `/docs/D4D/03. Sensor Abstraction Layer.md` — "02 → 03 매핑" 표. 03이 어떤 원시 필드를 요구하는지 역추적할 것.
- `/docs/D4D/A-1. 추상 결과 세부 내용.md` — 채널 payload 필드 최종 확정본. 이 문서에 있는 원시 필드명을 mock에 그대로 반영해 이후 step 03이 접근할 때 이름 매치가 되도록 한다.
- `/docs/D4D/04. Threat Modeling.md` — 시나리오 T3/T4/T7의 예상 매칭 결과. mock 데이터가 이 매칭을 실제로 유발하도록 값을 조정한다.

## 작업

원시 센서 데이터를 생성하는 mock 소스와 3개 골든 시나리오 fixture를 만든다. 03 채널이 접근할 필드명을 확정하는 자리이기도 하다.

### 1) `src/onboard/layer_02_sensor/schema.py`

원시 센서 envelope TypedDict. 카테고리별 dict로 nesting.

```python
from typing import TypedDict

class RawSensorEnvelope(TypedDict):
    sortie_id: str
    seq: int
    ts_ms: int
    imagery: dict            # EO/IR raw frame refs, gimbal_deg
    navigation: dict         # gps, imu, baro, magnetometer, airspeed, waypoint_telemetry
    c2_link: dict            # rssi_dbm, noise_floor_dbm, freq_mhz, packet_loss_rate, latency_ms, checksum_fail_rate, seq_gap_count, encryption_mode, downgrade_detected
    ew: dict                 # gnss_confidence, gnss_position_jump_m, satellite_count, cn0_avg_db, rf_wideband_scan, rf_bearing_deg
    health: dict             # battery(voltage_v, current_a, pct, temp_c), motor_rpm[], motor_temp_c, imu_vibration, failsafe_state
    acoustic: dict           # mic_waveform_ref, peak_db, rise_time_ms, bandwidth_hz, bearing_deg
    environment: dict        # wind_ms, wind_dir_deg, temp_c, alt_agl_m, dem_ref
    mission_status: dict     # current_waypoint, mission_current, flight_mode, ground_speed_mps, distance_to_target_m, distance_to_base_m
    lidar: dict              # distance_m, closure_rate_mps (하드웨어 미확정 필드 — 03의 obstacle_proximity가 소비)
```

카테고리와 하위 필드는 `02. UAV Sensor Layer.md`와 `03. Sensor Abstraction Layer.md`의 "02 → 03 매핑" 표 교집합에서 필요한 것만 담는다. 문서에 없는 새 카테고리를 만들지 마라.

### 2) `src/onboard/layer_02_sensor/mock_source.py`

```python
def build_normal_envelope(sortie_id: str, seq: int, ts_ms: int) -> RawSensorEnvelope:
    """모든 채널이 normal 상태가 되도록 안전한 기본값을 반환."""

def build_scenario_envelope(scenario_id: str, seq: int, ts_ms: int) -> RawSensorEnvelope:
    """scenario_id ∈ {"t3", "t4", "t7"} — 각 시나리오에 맞는 이상 값을 주입한다."""
```

시나리오 요구사항 (04 Threat Modeling의 SIGNAL_TO_THREAT 조건을 통과해야 함):

- **t3 (근접 소화기)**: `imagery.raw_frame` 자리에 "person + weapon" 라벨 hint (03의 proximity_object stub이 이걸 읽어 `weapon_shape=True`로 산출하도록 mock 라벨 필드를 심어둔다), `acoustic.peak_db > 90`, `acoustic.rise_time_ms < 3` (총성 감지 결정론적 기준). `declared_phase = "LOITER_ROI"` 유도.
- **t4 (물리 포획, 다중채널 T4 3조건)**: `imagery` mock 라벨에 "person, closing=True", `mission_status.flight_mode`와 `imu` 값이 서로 불일치 (선언 vs 행동 mismatch), `c2_link.rssi_dbm < -95` (link_status state=anomaly). `declared_phase = "WAYPOINT"`.
- **t7 (지형충돌)**: `lidar.distance_m = 15.0`, `lidar.closure_rate_mps = 8.0` → time-to-collision = 1.875s < 3.0s. `declared_phase = "LAND"`.

정상 baseline 값 예시 (참고, 완전 고정 필요 없음):

```python
navigation.gps = {"lat": 37.5, "lon": 127.0, "alt_m": 150.0, "hdop": 0.8, "vdop": 1.2}
c2_link = {"rssi_dbm": -60, "noise_floor_dbm": -95, "packet_loss_rate": 0.001, "latency_ms": 40, "checksum_fail_rate": 0.0, "seq_gap_count": 0, "encryption_mode": "AES256", "downgrade_detected": False}
health.battery = {"voltage_v": 25.0, "current_a": 30.0, "pct": 78, "temp_c": 35}
```

### 3) 골든 fixture

`examples/raw_t3.json`, `examples/raw_t4.json`, `examples/raw_t7.json` — 위 `build_scenario_envelope`가 `seq=0, ts_ms=1730620801200`으로 만들어낸 결과를 그대로 저장. 사람이 손댈 필요는 없고 mock_source 실행 결과의 JSON dump.

동일한 seq/ts로 두 번 호출해도 결과가 동일해야 한다 (deterministic mock — `random.seed`가 필요하면 함수 시작에서 고정하되 시나리오별로 다르게 시드).

### 4) `mission_brief` 골든

`examples/mission_brief_t3.json`, `_t4.json`, `_t7.json`을 만들어 `MissionBrief` 스키마를 채운다.

- t3: `mission_context="정찰"`, `posture.watchcon=3, defcon=3`, `drone_profile.spare_asset_available=False`, `drone_profile.armament=[]` (무장 없음), `weights={stealth:0.4, survival:0.2, info_value:0.3, timeliness:0.1}`
- t4: `mission_context="호송"`, `posture.watchcon=2, defcon=2`, `drone_profile.spare_asset_available=True`, `armament=[]`
- t7: `mission_context="타격"`, `posture.watchcon=3, defcon=3`, `drone_profile.spare_asset_available=True`, `armament=[{expendable: True, type: "leaflet"}]` (WEAPON_DROP 조건부 실행 테스트용)

### 5) 테스트

`tests/layer_02_sensor/test_mock_source.py`:

- 세 시나리오 envelope이 `RawSensorEnvelope` TypedDict의 필수 키를 모두 채운다
- t3 envelope: `acoustic.peak_db > 90 and acoustic.rise_time_ms < 3`
- t4 envelope: `c2_link.rssi_dbm < -95`
- t7 envelope: `lidar.distance_m / lidar.closure_rate_mps < 3.0`
- `build_normal_envelope("s", 0, 0)`을 두 번 호출한 결과가 동일 (deterministic)
- `examples/raw_t3.json`이 `build_scenario_envelope("t3", 0, 1730620801200)` 결과와 정확히 일치

`tests/layer_02_sensor/test_mission_brief.py`:

- 세 브리핑 파일이 유효한 JSON이며 `mission_context`가 `MISSION_CONTEXTS` 상수 안에 있다
- t7 브리핑의 `drone_profile.armament[0].expendable is True`

## Acceptance Criteria

```bash
python3 -m pytest tests/layer_02_sensor/ -v
```

- 모든 테스트 PASSED
- `examples/raw_t3.json`, `examples/raw_t4.json`, `examples/raw_t7.json`, `examples/mission_brief_t3.json`, `_t4.json`, `_t7.json` 존재

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트:
   - 카테고리 8종이 `02. UAV Sensor Layer.md`와 일치하는가? (lidar는 03이 요구하는 항목으로 별도 인정)
   - t3/t4/t7 시나리오가 04 SIGNAL_TO_THREAT의 임계값을 실제로 통과하도록 값이 세팅됐는가?
3. 결과에 따라 `phases/0-mvp/index.json`의 step 2를 업데이트한다.

## 금지사항

- 실제 데이터셋(AI Hub, HIT-UAV 등)을 다운로드하려 시도하지 마라. 이유: MVP 스코프 밖 (PRD 참조). 값은 손으로 세팅한 mock.
- 03의 채널 처리 로직을 여기 넣지 마라. 이유: step 3의 몫. 이 step은 원시 데이터 생성만.
- `random` 시드 없이 난수를 쓰지 마라. 이유: fixture 재생성 시 골든이 매번 바뀌면 회귀 테스트가 불가능.
- 임의의 새로운 카테고리(예: "gps_spoofing_flag")를 추가하지 마라. 이유: 02 원문에 있는 원시 필드만 다루고, 판정은 03 이후 계층의 몫.
