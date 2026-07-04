# examples/ — 시나리오 fixture

D4D 파이프라인 종단 테스트용 골든 시나리오 3종의 입력 fixture.

## 파일 구조

각 시나리오 `t{3,4,7}` 마다 3개 파일이 필요하다.

| 파일 | 스키마 | 상태 | 담당 |
|------|--------|------|------|
| `mission_brief_t{N}.json` | `MissionBrief` (src/onboard/shared/schemas.py) | ✅ 제공됨 | Lead |
| `raw_t{N}.json` | 원시 센서 dict (layer 02 output) | ⏳ layer 02 dev 가 정의 | 김수지 |
| `expected_t{N}.json` | `run_cycle()` 종단 반환 dict | ⏳ step9 CLI 실행 결과 | Lead |

## 시나리오

| ID | 위협 | mission_context | posture | armament | spare | 의미 |
|----|------|-----------------|---------|----------|-------|------|
| `t3` | T3 (근접 소화기) | 정찰 | WATCHCON=3, DEFCON=3, INFOCON=4 | 없음 | ✅ | `docs/D4D/C-1` 8절 GIREOGI-0704-01 소티. LOITER_ROI 중 무장 인원 조우. |
| `t4` | T4 (물리 포획) | 호송 | WATCHCON=3, DEFCON=3, INFOCON=3 | 없음 | ❌ | 다중채널 조합 매칭. spare_asset 없음 → severity 1단계 격상. |
| `t7` | T7 (지형충돌/CFIT) | 수송 | WATCHCON=4, DEFCON=4, INFOCON=4 | 없음 | ✅ | 착륙 접근 중 지형 근접. NAVIGATION 위협 (적대행위 아님). |

## `raw_t{N}.json` 이 필요로 하는 값 (구현 참고)

layer 02 개발자(김수지) 가 `raw_*.json` 을 정의할 때, layer 03 채널이 아래 payload 를 산출할 수 있도록 raw 스키마를 설계해야 한다.

**t3 (근접 소화기 T3 매칭 조건)**
- `proximity_object`: `state=anomaly`, `payload.weapon_shape=True`, `quality≈0.90`
- `acoustic_event`: `payload.event_type="gunshot"`, `quality≈0.92`
- `position_consistency`: `state=normal`, `payload.gps_imu_residual_m≈0.8`
- `mission_phase`: `declared="LOITER_ROI"`, `mission_phase_confidence≈0.9`
- `terrain_class`: `payload.exposure_score≈0.4`

**t4 (물리 포획 T4 3채널 AND)**
- `proximity_object`: `state=anomaly`, `payload.class="vehicle"`, `payload.closing=True`, `quality≈0.88`
- `mission_phase`: `declared="WAYPOINT"`, `payload.match=False`, `quality≈0.80`
- `link_status`: `state=anomaly`, `payload.rssi_dbm≈-95`, `quality≈0.70`

**t7 (지형충돌 T7)**
- `obstacle_proximity`: `payload.distance_m / payload.closure_rate_mps < 3.0` (충돌예상시간 3초 미만)
- `mission_phase`: `declared="LAND"` (LAND 국면에서 T7 배수 1.2 확인)

정확한 값은 `docs/D4D/C-1. Threat Modeling Spec.md` 8·9 절과 `docs/D4D/03. Sensor Abstraction Layer.md` 참조.

## `expected_t{N}.json` — 생성 규칙

**절대 손으로 편집 금지** (step9.md 금지사항).
step9 완료 후 CLI 로 생성:

```bash
python3 -m onboard examples/raw_t3.json examples/mission_brief_t3.json > examples/expected_t3.json
```

값이 이상하면 상위 layer 로 돌아가 로직을 고친다.

## mission_brief 필드 참고

- `mission_context` : `"정찰"|"타격"|"호송"|"수송"` — 05 BASE_RATE 조회 키
- `posture.watchcon/defcon` : 물리·EW 위협 (T1/T3/T4/T5/T7) posture_shift 기준
- `posture.infocon` : 사이버 위협 (T2) posture_shift 기준
- `drone_profile.armament` : 빈 배열이면 06 payload_action = `["DATA_WIPE"]` (armament 없음 규칙)
- `drone_profile.spare_asset_available` : `False` 이면 05 severity 1단계 격상
- `drone_profile.battery_pct` : 05 continuous_S margin_penalty (< 30% 시 +0.10)
- `weights` : 07 flight planning 우선순위 조합 (stealth/survival/info_value/timeliness)
