# examples/ — 시나리오 fixture

D4D 파이프라인 종단 테스트용 **골든 시나리오 6종**의 입력·기대출력 fixture.
ADR-005 마스터 시나리오(REMOTE T1/T2 + PHYSICAL T3/T4 + NAV T7) + 타격 컨텍스트(strike) 완성본.

## 파일 구조

각 시나리오마다 입력 2개(`raw`, `mission_brief`) + 기대출력 1개(`expected`).
`strike` 는 별도 raw 없이 `raw_t3` 를 타격 브리핑과 조합한다(아래 표 참조).

| 파일 | 스키마 | 상태 | 담당 |
|------|--------|------|------|
| `mission_brief_{시나리오}.json` | `MissionBrief` (src/onboard/shared/schemas.py) | ✅ 제공됨 | Lead |
| `raw_{t1,t2,t3,t4,t7}.json` | `RawSensorEnvelope` (src/onboard/layer_02_sensor/schema.py, nested) | ✅ 확정 (build_scenario_envelope 산출) | 김수지 |
| `expected_{시나리오}.json` | `run_cycle()` 종단 반환 dict | ✅ (#37, CLI 산출) | Lead |

## 시나리오 (6종)

| ID | 위협 | 카테고리 | mission_context | posture | armament | spare | 종단 결과(expected) |
|----|------|----------|-----------------|---------|----------|-------|---------------------|
| `t1` | T1 (GPS 스푸핑) | REMOTE | 정찰 | W3 / D3 / I3 | 없음 | ✅ | primary=**T1**, RAC=Medium. position_consistency 잔차>5m(gps↔imu 불일치). |
| `t2` | T2 (사이버/C2 하이재킹) | REMOTE | 호송 | W3 / D3 / **I2** | 없음 | ✅ | primary=**T2**, RAC=High. 암호 다운그레이드 + 링크 무결성 이상. INFOCON 기반 posture_shift. |
| `t3` | T3 (근접 소화기) | PHYSICAL | 정찰 | W3 / D3 / I4 | 없음 | ✅ | primary=**T3**, RAC=Serious. LOITER_ROI 중 무장 인원 조우(`C-1` 8절 GIREOGI-0704-01). |
| `t4` | T4 (물리 포획) | PHYSICAL | 호송 | W3 / D3 / I3 | 없음 | ❌ | primary=**T4**, RAC=Serious. 다중채널 AND 매칭. spare 없음 → severity 1단계 격상. |
| `t7` | T7 (지형충돌/CFIT) | NAVIGATION | 수송 | W4 / D4 / I4 | 없음 | ✅ | primary=**T7**, RAC=Medium. 착륙 접근 중 지형 근접(적대행위 아님). |
| `strike` | T3 (raw_t3 재사용) | PHYSICAL | **타격** | W2 / D2 / I3 | **leaflet(expendable)** | ✅ | primary=**T3**, RAC=High. 타격 컨텍스트 + 무장 → payload override = `["DATA_WIPE", "WEAPON_DROP"]`. |

시나리오→입력 페어링(`tests/integration/test_e2e_golden.py`):

| 시나리오 | raw | mission_brief |
|---|---|---|
| t1 / t2 / t3 / t4 / t7 | `raw_{ID}.json` | `mission_brief_{ID}.json` |
| strike | `raw_t3.json` | `mission_brief_strike.json` |

## raw 스키마 (확정)

`raw_{t1,t2,t3,t4,t7}.json` 은 layer 02 정본 스키마 **`RawSensorEnvelope`**(카테고리 중첩: `navigation`/`c2_link`/`ew`/`health`/`imagery`/`acoustic`/`environment`/`mission_status`/`lidar` + `sortie_id`/`seq`/`ts_ms`)를 따른다. 이슈 #14 로 flat draft 대신 이 nested 스키마가 정본으로 확정됐다.

- 생성: `src/onboard/layer_02_sensor/mock_source.py` 의 `build_scenario_envelope(scenario_id, seq, ts_ms)` 결정론 산출. 손편집하지 말고 재생성한다.
- 각 시나리오가 유발하는 04 판정 신호(요약):
  - **t1**: `navigation.imu.est_lat` 오프셋 → 03 `position_consistency.gps_imu_residual_m > 5.0`
  - **t2**: `c2_link` downgrade + checksum/seq → 03 `encryption_status`/`link_integrity` anomaly (#28 로 quality=판독기 건전성 정정 후 종단 T2 탐지)
  - **t3**: `imagery.object_label.weapon_shape=True` + `acoustic` 총성 임계 → `proximity_object`/`acoustic_event`
  - **t4**: `imagery.object_label`(person+closing) + 선언-행동 mismatch + `c2_link.rssi<-95` → T4 3채널 AND
  - **t7**: `lidar.distance_m / closure_rate_mps < 3.0` → `obstacle_proximity`
- smoke 회귀: `tests/integration/test_raw_fixtures.py` (nested 스키마 로드·직렬화·필수키·시나리오 구분 값 잠금).

정확한 채널 payload·값은 `docs/D4D/C-1. Threat Modeling Spec.md` 8·9 절, `docs/D4D/03. Sensor Abstraction Layer.md`, `docs/D4D/A-1. 추상 결과 세부 내용.md` 참조.

## `expected_{시나리오}.json` — 생성 규칙

**절대 손으로 편집 금지** (step9.md 금지사항). CLI 산출 정본이며 `tests/integration/test_e2e_golden.py` 가 `run_cycle()` 출력과 완전 일치를 검증한다.

```bash
# 재생성 (스펙 변경 시)
python3 -m onboard examples/raw_t3.json examples/mission_brief_t3.json > examples/expected_t3.json
# strike 는 raw_t3 + 타격 브리핑
python3 -m onboard examples/raw_t3.json examples/mission_brief_strike.json > examples/expected_strike.json
```

값이 이상하면 상위 layer 로 돌아가 로직을 고친다(golden 을 값에 맞추지 않는다).

## mission_brief 필드 참고

- `mission_context` : `"정찰"|"타격"|"호송"|"수송"` — 05 BASE_RATE 조회 키
- `posture.watchcon/defcon` : 물리·EW 위협 (T1/T3/T4/T5/T7) posture_shift 기준
- `posture.infocon` : 사이버 위협 (T2) posture_shift 기준
- `drone_profile.armament` : 빈 배열이면 06 payload_action = `["DATA_WIPE"]` (armament 없음 규칙). 무장 보유 + High RAC 이면 `WEAPON_DROP` 추가(strike).
- `drone_profile.spare_asset_available` : `False` 이면 05 severity 1단계 격상
- `drone_profile.battery_pct` : 05 continuous_S margin_penalty (< 30% 시 +0.10)
- `weights` : 07 flight planning 우선순위 조합 (stealth/survival/info_value/timeliness)
