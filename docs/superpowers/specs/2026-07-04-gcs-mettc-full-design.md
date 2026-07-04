# GCS 1단계 심화 — 풀 METT+TC 조립 + 구조화 C4I 통합 (설계)

날짜: 2026-07-04 · 범위: `src/gcs/layer_01_info_center/` 확장 + B-1 문서 조립 규약 절

## 1. 목적

layer 01 MVP 슬라이스(flat 6필드 조립)를 B-1 정본 상태모델로 심화한다:
- **조립 정본 = `{drone_profile, mettc}`** (M / E / T_terrain / T_troops / T_time / C).
- 온보드 6필드 `MissionBrief` 는 **투영(projection) 어댑터**로 파생 — 02-07 계약 무변.
- C4I 입력을 구조화(E.tracks 등)하고 `01` 문서 **대조표 6종을 전부** 구현한다.

## 2. 입력 계약

### set_mission (운용자 + GCS 항로 — 기존 + 확장)
```
{ sortie_id, directive_text, mission_context, posture, drone_profile,
  corridor,            # 기존 waypoints/bases 형 (하위호환) 또는
  corridor_spec,       # B-1 형: {type:"polyline_buffer", axis:[[lat,lon],..], half_width, alt_min, alt_max}
  weights,
  higher_intent?, unit_mission?, uav_mission?{name,purpose,type,goal},
  c4i }
```

### c4i (구조화 — c4i_schema.py)
```
{ enemy_tracks: [{track_id, kind, pos:[lat,lon], radius?, velocity?, confidence, status?, label}],
  asset_management: {spare_asset_available: bool},
  civil_density_draft: [{id, center:[lat,lon], radius, density: "low|medium|high"}],
  posture_feed?: {watchcon, defcon, infocon},
  known_mission?: str,
  enemy_situation?: [str]   # 레거시 문자열 — track.label 로 승격 수용
}
```
- 하위호환: `enemy_situation` 문자열 배열이 오면 `{kind:"report", label:<str>, confidence:0.5}` 트랙으로 승격.

## 3. 모듈 분해

| 모듈 | 책임 |
|---|---|
| `c4i_schema.py` (신규) | C4I 입력 정규화·검증. `normalize_c4i(raw) -> C4I` — 레거시 승격 포함 |
| `nlp_extract.py` (확장) | 신호 룰 추가: `heavy_weapons`(대구경·박격포·대공 → severity 신호), `resupply`(재보급·소요 시간), `civil_area`(민가·민간·시가지), `mission_purpose`(정찰/타격/호송/수송 언급 추출). Signal 키 계약 유지 |
| `cross_check.py` (확장) | **대조표 6종**: ①적활동 신호↔enemy_tracks(label/kind 매칭 → 확신도↑+이유) ②무기·화력 신호↔enemy_tracks ③재보급/예비 신호↔drone_profile.spare (확신도 조정) ④민간 신호↔civil_density_draft (확신도 조정) ⑤임무목적(NLP)↔운용자 mission_context·C4I known_mission (경고만) ⑥drone_profile.spare↔asset_management (경고만). 반환 계약 (adjusted, warnings) 유지 |
| `mettc_assemble.py` (신규) | `assemble_mettc(set_mission, c4i, signals) -> {drone_profile, mettc}`. 초기값 규약(§4). E.tracks ← c4i.enemy_tracks 그대로 + `source:"c4i"` 태깅 |
| `project_brief.py` (신규) | `project_onboard_brief(state) -> MissionBrief(6필드)`. 매핑: `M.uav_mission.purpose→mission_context`, `M.posture→posture`, `M.weights→weights`, `T_terrain.corridor.axis→corridor.waypoints([{id,lat,lon,alt_m}])`, `T_troops.friendly.bases→corridor.bases`, `drone_profile` 직행(+spare_asset_available 키 정합) |
| `run.py` (확장) | `assemble_draft` → `{mettc_state, draft_brief, signal_cards, warnings}`. `finalize(draft, approved, ts_ms)` → `{mission_brief, mettc_state, approved_ts_ms}`. **하위호환**: corridor_spec 없으면 기존 corridor 를 axis 로 역변환해 조립 |

## 4. 온보드-소유 필드 초기값 규약 (B-1 §2 준수, 문서에 추가)

비행 전 조립 시점에 온보드(obs/내부시계) 소유 필드는 다음 초기값:
- `T_time = {elapsed_s: 0, eta_goal_s: null, endurance_s: drone_profile.endurance_rated_s ?? null}`
- `T_troops.pos = home base pos(없으면 axis[0]) + alt null`, `battery = drone_profile.battery_pct/100 ?? null`
- `T_troops.sensors_ok / gps_quality / comms_q = null` (미관측)
- `T_terrain.weather = null`, `terrain_ref = "onboard_dem"`(stub), H/W/hmin/hmax = null (DEM 후순위)
- `E.tracks[].history = []`, `last_seen_tick = null` (지상 시점 무 tick)
- `C.civil_areas ← civil_density_draft` 변환, `civil_sensitivity_estimate` = draft 최고 density (없으면 "low")

## 5. 데이터 흐름

```
set_mission + c4i
  → normalize_c4i → C4I
  → extract_signals(directive) [신규 룰 포함]
  → cross_check(signals, profile, mission_context, C4I) [6종]
  → assemble_mettc(...) → {drone_profile, mettc}
  → project_onboard_brief(...) → draft_brief(6필드)
  → assemble_draft = {mettc_state, draft_brief, signal_cards, warnings}
  → finalize(approved, ts_ms) → {mission_brief, mettc_state, approved_ts_ms}
       → 온보드 run_cycle(raw, mission_brief) (계약 무변)
```

## 6. 에러 처리

- 필수 누락(sortie_id/mission_context/posture/drone_profile/weights + corridor 계열 중 1) → ValueError.
- c4i 부재/부분 → 해당 대조만 스킵 (조립은 진행).
- corridor_spec 와 corridor 동시 제공 시 corridor_spec 우선.
- NLP 는 지시서 원문만 (추적성 불변). 전 로직 결정론(모델 없음).

## 7. 테스트 (TDD)

- `c4i_schema`: 정규화·레거시 승격·부분 입력.
- `nlp_extract`: 신규 4룰 (heavy_weapons/resupply/civil/purpose) + 기존 회귀.
- `cross_check`: 6종 각각 — 조정형은 확신도↑+reason, 경고형은 확신도 불변+warning. c4i 부재 스킵.
- `mettc_assemble`: B-1 구조 적합(6요소 키), 초기값 규약, E.tracks 태깅.
- `project_brief`: 6필드 정확 투영, axis→waypoints, spare 키 정합.
- **킬러 ①**: 조립본 구조가 B-1 §1 예시 JSON 골격과 적합(요소·필수 키 대조).
- **킬러 ②**: `finalize(...).mission_brief` → `run_cycle(raw_t3)` 종단 T3 탐지 (기존 통합 상위호환).
- 기존 gcs 테스트 전부 회귀 무변 (하위호환 검증).

## 8. 문서-우선

구현 전 `B-1` 에 **"5. 지상통제센터 AI 조립 규약(신규)"** 절 추가: 초기값 규약(§4)·투영 매핑(§3 project_brief)·C4I 정규화(§2). 코드가 문서를 따른다.

## 9. 범위 밖

실 NLP 모델, 승인 거부/재수집 플로우, 대시보드 METT+TC 뷰(/gcs/assemble 응답에 mettc_state 실어주기까지만 — UI 는 후속), 비행 중 E.tracks 갱신(온보드 몫), 실 DEM.
