# infra/sim — 폐루프 시뮬레이션 소스 (sim 코어)

METT+TC(mission_brief) → 적 사전배치 → 회피경로 → `World.tick(command)` → envelope →
`run_cycle`(실 판정) → `flight_plan` 되먹임 폐루프. seed 이벤트(팝업 위협) 조우 시
궤적이 실제로 꺾인다(EVADE → 우회 → 달성). **온보드 파이프라인(`src/onboard`) 무수정**
— `run_cycle` / `build_normal_envelope` import 재사용만. 순수 결정론(난수 없음): 같은
seed = 동일 적·이벤트·궤적·판정(재현성).

## 모듈 계약 (4)

| 모듈 | 계약 |
|---|---|
| `route.py` | `generate_route(mission_brief, enemies=None) -> [{lat,lon,alt_m}]`. corridor + 적 `detect_radius` **선분(leg)-aware 회피**(2-pass): 침범 구간에 우회점 삽입 후 두 leg clearance ≥ radius 될 때까지 offset 결정론 수렴. 끝점이 원 안(회피 불가)이면 우회 스킵(무효좌표 방지). |
| `world.py` | `World.tick(dt, command) -> state`. `command`=`flight_plan`. `target_bearing_deg`+`replan_scope≠NONE` → 그 방위로 조향(EVADE, action명 무관). `speed_mode`→대지속도, `altitude_delta_m`→승강(율 상한). phase 는 **매 tick 재계산**(래치 없음). lat/lon 7자리·heading 6자리 반올림(포터블 결정론). |
| `envelope.py` | `world_to_envelope(sortie_id, seq, ts_ms, world_state, *, threat_object=None) -> RawSensorEnvelope`. `build_normal_envelope` baseline + 위치/헤딩/속도 주입(gps=imu est 로 T1 오탐 방지). `threat_object` → 근접위협 주입. |
| `runner.py` | `run_closed_loop(mission_brief, seed, ticks, dt) -> [{world, result}]` 폐루프 되먹임 + `previous_qualities`/`flight_plan_state` 스레딩. `build_scenario`/`build_tick_payload`. CLI `main()`(`--seed --brief --ticks --dt --rate --collector`). |

## `enemy_tracks` (E.tracks) 입력 스키마 — F3

`mission_brief.enemy_tracks` 가 있으면 `place_enemies` 가 seed 배치 대신 그 위치에 적을
놓는다(폼/C4I → route 회피 → 조우). **두 정본 형상을 모두 수용**:

| 출처 | 형상 |
|---|---|
| 관측소 폼 (`gcs.js`) | `{ id, kind, lat, lon, radius_m, confidence }` — 위치 top-level `lat`/`lon` |
| C4I / `assemble_mettc` (B-1 §5.1) | `{ track_id, kind, pos: [lat, lon], confidence, label, ... }` — 위치 `pos` 리스트(또는 `{lat,lon}`) |

- id = `id` ‖ `track_id`. 반경 = `radius_m` (없으면 기본 400m). `kind`/`confidence` 보존(표시용).
- 위치 해석 불가 항목은 스킵. **유효 변환이 0개면 조용히 0기로 두지 않고 seed 폴백**(적 없는 시뮬 방지).

## `POST /tick` payload 스키마 (정본)

runner 가 사이클마다 산출하는 관측 패널 전송 계약 (`build_tick_payload` 출력). 수집기
`/tick` → `WS /stream` → 대시보드 `app.js` 소비. **모킹 아님** — 파이프라인 실출력.

```jsonc
{
  "type": "tick",
  "seq": 0,                      // 단조증가(사이클 인덱스)
  "ts_ms": 0,                    // = int(seq * dt * 1000)
  "correlation_id": "SORTIE-0000", // sortie 단위(시뮬 재시작 시 신규)
  "world": {                     // sim 산출 — 지도/텔레메트리 패널
    "pos": { "lat": 37.5, "lon": 127.0, "alt_m": 120.0 },
    "heading_deg": 42.1,
    "speed_mps": 17.0,
    "phase": "TRANSIT",          // TRANSIT | ENCOUNTER | EVADE | RTL | ARRIVED
    "enemies": [ { "id": "E1", "pos": { "lat": 37.55, "lon": 127.05 }, "detect_radius_m": 400.0 } ]
  },
  "abstraction": { "schema_version": "...", "id": "...", "ts": 0, "channels": [ /* 03 실 11채널 */ ] },
  "threat":   { /* 04 run_cycle 실출력 */ },
  "risk":     { /* 05 실출력 */ },
  "response": { /* 06 실출력 */ },
  "flight_plan": { /* 07 실출력 (flight_action/target_bearing_deg/speed_mode/replan_scope/...) */ }
}
```

- **`world`** = sim 코어 산출(위 world.py). **`abstraction`/`threat`/`risk`/`response`/`flight_plan`** = `run_cycle` 실출력 **그대로**(계약: `docs/contracts/*`). `abstraction.channels[]` = `{channel,state,quality,quality_delta,payload}`(#106).
- **`speed_mode` enum** = 07 `flight_plan.speed_mode` = `CAUTIOUS | NORMAL | MAX` (`shared/constants.SPEED_MODE_ORDER`). world 속도표는 이 enum 을 키로 쓴다.

### fallback 계약 (app.js 패널별)

스트림/필드 부재 시 패널별 mock 으로 폴백(데모 모드 유지). 실 스트림 수신 시 자동 전환.

| 조건 | app.js 동작 |
|---|---|
| `/stream` 미연결 | 전 패널 mock(내부 시뮬), "시뮬" 라벨 |
| tick 수신, `world` 있음 | 지도/텔레메트리 실값. `world` 는 **필수 키**(없으면 그 tick 무시) |
| tick 수신, `abstraction` null/부재 | 신호 패널만 mock 폴백, 나머지는 실값 |
| tick 수신, `threat/risk/response` null/부재 | AI 결정 패널만 mock 폴백 |

## 실행

```bash
# 폐루프 dry-run (tick payload JSON Lines 를 stdout)
PYTHONPATH=src:infra/sim python -m runner --seed 42 --brief examples/mission_brief_t3.json --ticks 20
# 수집기로 스트림 (POST /tick)
PYTHONPATH=src:infra/sim python -m runner --seed 42 --brief examples/mission_brief_t3.json --collector http://localhost:8500/tick --rate 0.5
```

테스트: `tests/infra_sim/`(루트 CI `python -m pytest` 수집). 계약 회귀 = `test_tick_payload_contract.py`.
