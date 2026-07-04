# vizsim

> **용도 분리:** 팀 `infra/sim` = 온보드 파이프라인/RAG 비행로그 정본,
> `infra/vizsim` = 관측 대시보드 정본(지형·뷰셰드·정규화좌표·레이어 debug).
> 공통 `src/onboard` run_cycle 무수정. 팀 sim 계약(#167/#195/#218) 무회귀.

D4D **신호발생기(가상 세계)** — layer 2(Sensor)의 상류에서 `RawSensorEnvelope`를
연속 생성해 온보드 파이프라인(`onboard.run.run_cycle`)에 tick마다 흘려보내고, 결과를
`infra/log/log_server.py`(로그수집기)로 push해 대시보드가 라이브로 관측할 수 있게 한다.

## 목적

실제 비행체·센서 없이도 mission brief 하나만으로 결정론적인 가상 임무를 재생한다.
드론이 경로를 따라 이동하며 매 tick `RawSensorEnvelope`를 합성하고, 이를 그대로
02 Sensor Layer 입력으로 온보드 파이프라인 전체(02..07)에 흘려 실제 판단(위협 모델링→
위험 평가→대응→비행계획)이 나오도록 한다.

## 아키텍처 파이프

```
route → path → events → world → envelope → runner
```

| 모듈 | 역할 |
|---|---|
| `terrain.py` | 결정론적 가우시안 heightmap(`app.js`의 PEAKS/heightAt 파이썬 포트) + 200×200 u16 격자 생성 |
| `route.py` | mission brief의 lat/lon corridor → 정규화 [0,1] 평면 경로로 변환, stealth/timeliness/watchcon 가중치로 경로·고도 편향 |
| `path.py` | 웨이포인트 리스트의 호길이(arc-length) 파라미터화 — 진행도 `s` → (x, y, alt, heading) |
| `events.py` | seed 기반 위협 이벤트(T1/T2/T3/T4/T7)를 진행도 `s` 위치에 사전 배치 |
| `world.py` | `World` — tick(dt)마다 `s`/고도/heading/속도/배터리를 결정론적으로 전진시키는 물리 상태 |
| `envelope.py` | `World` 스냅샷 + route bbox → `RawSensorEnvelope` 합성(활성 이벤트에 따라 센서 필드 오버라이드) |
| `runner.py` | CLI — 위 파이프를 tick 루프로 구동하며 온보드 파이프라인 실행 + 로그수집기로 `/init`·`/log`·`/tick` push |

`runner.py`가 보내는 `/init`·`/tick`은 로그수집기(`log_server.py`)의 `stream_hub`가
받아 대시보드가 구독하는 `WS /stream`으로 그대로 broadcast된다 — 계약 상세는
`infra/log/API.md` "실시간 텔레메트리 스트림" 절 참고.

## seed 재현성 규칙

- 이벤트(T1 재밍, T2 링크 저하, T3 매복, T4 포획, T7 장애물)는 **tick 진행 중이 아니라
  생성 시점에 한 번**, `random.Random(seed)`로 경로 진행도 `s`(전체 경로 길이에 대한
  arc-length)에 미리 배치된다(`events.generate_events`).
- 따라서 **같은 `seed`는 항상 같은 경로 위치에서 같은 사건**을 만든다 — `--rate`나
  `--speed`(배속)를 바꿔도 이벤트가 발생하는 `s` 값은 변하지 않는다. tick/시간 개념은
  이벤트 배치에 전혀 관여하지 않는다.
- `World.tick(dt)`도 난수를 쓰지 않는 순수 물리 전진이므로, 동일 `seed` + 동일 `dt` 시퀀스는
  바이트 단위로 동일한 결과를 재생한다(`runner.run_ticks` 참고 — 벽시계 시간이 아니라
  `dt` 누적으로 `ts_ms`를 만드는 이유).

## in-process 실행

네트워크·수집기 없이 `runner.run_ticks(seed, brief, n_ticks, dt)`를 직접 import해
n틱을 순수 함수 호출로 재생할 수 있다(테스트·배치 분석용). 온보드 파이프라인 실행
결과(`result`)와 tick 스냅샷(`snapshot`)이 리스트로 반환되며, 로그수집기 POST는
발생하지 않는다.

```python
from runner import run_ticks
records = run_ticks(seed=42, brief=brief_dict, n_ticks=100, dt=0.2)
```

## 실행 커맨드

```
# 로그수집기 기동 (별도 터미널)
cd infra/log && PYTHONPATH=../../src:. ../../.venv/bin/uvicorn log_server:app --host 0.0.0.0 --port 8500
# 신호발생기 실행
PYTHONPATH=src .venv/bin/python infra/vizsim/runner.py --seed 42 --brief examples/mission_brief_t3.json --rate 5
```

## #102(layer 07 지형경로) 어댑터 교체 지점

`terrain.py`(가우시안 heightmap)와 `route.py`(직선 보간 + 편향 미드포인트)는 현재
mock 지형·경로 생성기다. 실제 DEM/지형경로 계획(#102, layer 07 Flight Planning)이
들어오면 이 두 모듈의 **출력 스키마(`{"u16","w","h","hmin","hmax"}`, `{"waypoints":[...]}`)
는 유지한 채 내부 구현만 교체**하면 된다 — `world.py`/`envelope.py`/`runner.py`는
스키마에만 의존하고 생성 방식을 모른다.

## layer 2 무수정 원칙

`envelope.py`는 `onboard.layer_02_sensor.mock_source.build_normal_envelope`와
`onboard.layer_02_sensor.schema.REQUIRED_KEYS`를 그대로 재사용해 정상 baseline
envelope를 만들고, 이벤트별 오버라이드만 얹는다. **`src/onboard/` 레이어 코드는
sim이 절대 수정하지 않는다** — sim은 layer 2의 소비자일 뿐, mock_source가 만든
값을 가져다 쓰기만 한다. 이는 온보드 파이프라인이 실제 하드웨어 입력과 sim 입력을
구분하지 못하게(동일 스키마) 만들어, 신호발생기가 실제 파이프라인을 그대로 검증하는
용도로 쓰일 수 있게 한다.
