# examples/ — 시나리오 fixture

D4D 파이프라인 종단 테스트용 골든 시나리오 6종의 입력 fixture (ADR-005 완성).
REMOTE 2종(t1 GPS 스푸핑 / t2 사이버) + PHYSICAL 2종(t3 소화기 / t4 포획) + NAV 1종(t7 CFIT) + strike(타격 컨텍스트 override).

## 파일 구조

각 시나리오 `t{1,2,3,4,7}` 마다 3개 파일(`raw_`·`mission_brief_`·`expected_`)이 필요하다.
`strike` 는 별도 raw 없이 `raw_t3.json` 을 재사용하고 `mission_brief_strike.json` + `expected_strike.json` 만 둔다.

| 파일 | 스키마 | 상태 | 담당 |
|------|--------|------|------|
| `mission_brief_t{N}.json` | `MissionBrief` (src/onboard/shared/schemas.py) | ✅ 제공됨 | Lead |
| `raw_t{N}.json` | 원시 센서 dict (layer 02 output) | ✅ 제공됨 | 김수지 |
| `expected_t{N}.json` | `run_cycle()` 종단 반환 dict | ✅ CLI 산출 (#37, 손편집 금지) | Lead |

## 시나리오

종단 결과(RAC·대응)는 `expected_t{N}.json` (CLI 산출 정본) 기준.

| ID | 위협 | mission_context | posture | armament | spare | 종단 대응 | 의미 |
|----|------|-----------------|---------|----------|-------|-----------|------|
| `t1` | T1 (GPS 스푸핑) | 정찰 | WATCHCON=3, DEFCON=3, INFOCON=3 | 없음 | ✅ | REMOTE / Medium → MAINTAIN | position_consistency 잔차 이상. 원격 항법 위협, 물리 회피 아님. |
| `t2` | T2 (C2 하이재킹) | 호송 | WATCHCON=3, DEFCON=3, INFOCON=2 | 없음 | ✅ | REMOTE / High → REROUTE | 사이버 위협 — INFOCON=2 로 posture_shift. link_status 이상. |
| `t3` | T3 (근접 소화기) | 정찰 | WATCHCON=3, DEFCON=3, INFOCON=4 | 없음 | ✅ | PHYSICAL / Serious → ALTITUDE_CHANGE | `docs/D4D/C-1` 8절 GIREOGI-0704-01 소티. LOITER_ROI 중 무장 인원 조우. |
| `t4` | T4 (물리 포획) | 호송 | WATCHCON=3, DEFCON=3, INFOCON=3 | 없음 | ❌ | PHYSICAL | 다중채널 조합 매칭. spare_asset 없음 → severity 1단계 격상. |
| `t7` | T7 (지형충돌/CFIT) | 수송 | WATCHCON=4, DEFCON=4, INFOCON=4 | 없음 | ✅ | NAVIGATION → 07 CFIT override(altitude_delta_m>0) | 착륙 접근 중 지형 근접. 적대행위 아님. RAC 무관 결정론 상승. |
| `strike` | T3 (raw_t3 재사용) | 타격 | WATCHCON=2, DEFCON=2, INFOCON=3 | leaflet(expendable) | ✅ | PHYSICAL / High → RTL + payload `[DATA_WIPE, WEAPON_DROP]` | 타격 컨텍스트 base_rate 로 High 격상 → payload override 경로 검증. |

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

## `raw_t{N}.json` 추적표

raw 센서 스키마는 정본 확정됨(#14, 센서-keyed 단일 envelope). 아래는 PHYSICAL/NAV 계열(t3/t4/t7)의
raw 필드 → layer 03 채널 payload 매핑 참고표. REMOTE 계열(t1/t2)은 position_consistency·link_status
채널 중심이라 별도이며, 실제 값은 각 `raw_t{1,2}.json` 및 `expected_*.json` 정본을 참조한다.

| raw 필드 | 값(t3/t4/t7) | → 기대 03 채널 payload |
|---|---|---|
| `mission_phase.declared` | `LOITER_ROI` / `WAYPOINT` / `LAND` | `mission_phase.declared` (국면 배수) |
| `mission_phase.confidence` | 0.9 / 0.8 / 0.95 | `mission_phase_confidence` |
| `acoustic.rms`, `peak_db`, `band` | 0.78·118·impulse (t3) | `acoustic_event.event_type="gunshot"`, `quality≈0.92` |
| `camera.objects[].weapon_shape` | `true` (t3) | `proximity_object.state=anomaly`, `payload.weapon_shape=true`, `quality≈0.90` |
| `camera.objects[].class`+`closing` | `vehicle`+`true` (t4) | `proximity_object.payload.class="vehicle"`, `closing=true`, `quality≈0.88` |
| `link.rssi_dbm`, `state` | -95·degraded (t4) | `link_status.state=anomaly`, `payload.rssi_dbm≈-95`, `quality≈0.70` |
| `obstacle.distance_m`/`closure_rate_mps` | 24/12 → TTC 2.0s (t7) | `obstacle_proximity` TTC < 3.0s |
| `terrain.exposure_score` | 0.4 (t3) | `terrain_class.payload.exposure_score≈0.4` |
| `gps`+`imu` | 정합 값 | `position_consistency` `gps_imu_residual_m`(03 계산) |
| `camera.objects[].bearing_deg` | 35/12/(t7 obstacle 5) | 04 `primary.context.bearing_deg` 우선순위 소스 |

> smoke 회귀: `tests/integration/test_raw_fixtures.py` — 로드·JSON 직렬화·시나리오 구분 값만 잠금(raw 스키마 assert 없음).

## `expected_t{N}.json` — 생성 규칙

**절대 손으로 편집 금지** (step9.md 금지사항). CLI 산출만이 정본.
스펙 변경으로 golden 을 갱신해야 할 때만 아래로 재생성 후 diff 리뷰:

```bash
# 단일
python3 -m onboard examples/raw_t3.json examples/mission_brief_t3.json > examples/expected_t3.json

# 전체 6종 (strike 는 raw_t3 재사용)
for s in t1 t2 t3 t4 t7; do
  python3 -m onboard examples/raw_$s.json examples/mission_brief_$s.json > examples/expected_$s.json
done
python3 -m onboard examples/raw_t3.json examples/mission_brief_strike.json > examples/expected_strike.json
```

회귀 잠금: `tests/integration/test_e2e_golden.py` (6종, `run_cycle` == golden).

값이 이상하면 상위 layer 로 돌아가 로직을 고친다.

## GCS 종단 배선 — `set_mission_*.json`

`set_mission_{recon,strike,t3}.json` 은 지상통제센터 AI(layer 01) 입력 fixture
(지시서 원문 + C4I + 운용자 등록값). GCS CLI 가 승인 게이트를 거쳐 온보드
MissionBrief 를 산출하므로, 손편집 브리핑 없이 지시서→비행지시 전 구간이 이어진다:

```bash
# 지시서 → GCS 01 (운용자 승인) → mission_brief → 온보드 파이프라인
python3 -m gcs examples/set_mission_t3.json --approve --out /tmp/brief_t3.json
python3 -m onboard examples/raw_t3.json /tmp/brief_t3.json
```

`set_mission_t3.json` 의 GCS 산출 브리핑은 `mission_brief_t3.json` 골든과 완전 일치한다
(회귀 잠금: `tests/integration/test_gcs_to_onboard.py`). `--approve` 없이 실행하면
`pending_approval` 페이로드(신호 카드 + 경고)만 출력한다 — AI 는 후보만, 최종 결정은 사람.

## mission_brief 필드 참고

- `mission_context` : `"정찰"|"타격"|"호송"|"수송"` — 05 BASE_RATE 조회 키
- `posture.watchcon/defcon` : 물리·EW 위협 (T1/T3/T4/T5/T7) posture_shift 기준
- `posture.infocon` : 사이버 위협 (T2) posture_shift 기준
- `drone_profile.armament` : 빈 배열이면 06 payload_action = `["DATA_WIPE"]` (armament 없음 규칙)
- `drone_profile.spare_asset_available` : `False` 이면 05 severity 1단계 격상
- `drone_profile.battery_pct` : 05 continuous_S margin_penalty (< 30% 시 +0.10)
- `weights` : 07 flight planning 우선순위 조합 (stealth/survival/info_value/timeliness)
