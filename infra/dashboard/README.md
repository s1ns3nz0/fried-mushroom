# dashboard

D4D 온보드 AI **관측 대시보드** — FastAPI + WebSocket + Vanilla JS Canvas.

## 역할

uav(온보드)의 상태·판단 결과를 실시간으로 **시각화**한다.

- 좌상 **지도**: 지형 + 경로 + 드론 위치 + 위협 (라이브 — 로그수집기 `WS /stream` 연동,
  없으면 mock 폴백. 아래 "라이브 모드" 참고)
- 우상 **고도**: 지형 표고 + 드론 고도 프로파일 (라이브 — 지도와 동일 소스, mock 폴백)
- 좌하 **신호**: C2 11 의미 채널 state/quality (placeholder)
- 우하 **실시간 로그**: 로그수집기 `WS /logs` 스트림을 실시간 표시 (correlation_id 색 그룹핑, layer·level·correlation_id 필터, 개발용 mock 주입)

> **대시보드는 판단하지 않는다.** 판단 주체는 uav 위험 평가 계층(위협모델링→위험평가→판단기)이다.
> 대시보드는 그 결과를 표시(관측)만 한다. 가공·재판단 없음.

## 실시간 로그 스트림 (`WS /logs`)

브라우저가 로그수집기 `WS /logs`(기본 `ws://localhost:8500/logs`, `DASHBOARD_LOG_WS_URL` 로 재정의)에
**직접** 연결한다(대시보드 서버는 프록시하지 않음 — 관측 전용). 접속 시 backlog → 실시간 순 수신.

메시지 포맷:
```json
{ "correlation_id": "<uuid>", "layer": "sensor|abstraction|risk_assessment|response|...",
  "log": "<메시지>", "level": "info|warn|error", "ts": <epoch ms> }
```

- 각 항목: `[ts] [layer] correlation_id — log`, level별 색(info/warn/error).
- 같은 correlation_id 는 좌측 테두리·id 색으로 그룹핑.
- 필터: layer·level·correlation_id 검색. 자동스크롤(최신 아래).
- 수집기 없이 UI 확인용 **mock 주입/자동생성** 토글 제공.

## 라이브 모드 (`WS /stream`)

대시보드는 로그수집기(`infra/log/log_server.py`)의 `WS /stream`(로그 스트림 `/logs`와는
별도 소켓/허브, 기본 `ws://localhost:8500/stream` — `logWsUrl`에서 `/logs`→`/stream`
치환으로 유도)을 구독해 지도/고도 패널을 라이브 렌더한다.

- **`init` 수신**: 신호발생기(`infra/sim/runner.py`)가 보낸 지형(200×200 u16 표고 격자)과
  경로(정규화 [0,1] 평면 웨이포인트)를 받아 지도 지형 레이어를 재빌드하고 고도 프로파일
  정적 데이터를 만든다. 접속 시 최신 init이 backlog보다 먼저 오며, 재연결/백로그로 **동일
  init이 2회 도착할 수 있다** — 대시보드는 지형 격자 크기/범위가 같으면 rebuild를 스킵해
  idempotent하게 처리한다(`app.js` `applyStreamInit`).
- **`tick` 수신**: 드론 위치(x/y)·고도·headig·속도·배터리를 갱신해 지도 위 드론 마커를
  이동시키고, 고도 프로파일 trail에 (거리, 고도) 샘플을 누적한다(`applyStreamTick`).
- **라이브 vs mock 전환**: `WS /stream` 연결이 살아있고 `init`을 1회 이상 받으면
  `live.active = true`가 되어 지도/고도 패널이 라이브 데이터를 그린다. 스트림이 없거나
  연결이 끊기면 즉시 내장 mock 시나리오(출발지→목표 정상비행→T3 조우→RTL)로 폴백한다
  — 신호·기체 패널은 라이브 여부와 무관하게 계속 mock으로 구동된다.
- **모드 표시**: 지도 패널 헤더의 `#sim-mode-chip`이 현재 모드를 라벨링한다 —
  라이브 수신 중이면 "라이브"(accent 색), 아니면 "시뮬".
- **지형 결정론 공유**: 신호발생기의 `infra/sim/terrain.py`는 대시보드 `app.js`의
  `PEAKS`/`heightAt`/`elevM`/`buildTerrainGrid`를 그대로 파이썬으로 포트한 것이라, 동일
  좌표에서 항상 동일한 표고를 낸다 — 라이브 init으로 받은 지형과 mock 폴백 지형이
  시각적으로 이어진다.

## WS 메시지 타입 (`/ws`, Phase 2 자리표시)

uav 소스에서 수신 → 모든 뷰어로 브로드캐스트 (signal/decision/replan, 미구현 스텁).
`init`/`tick`은 위 "라이브 모드"에서 설명한 `WS /stream`으로 이미 구현되어 있다
(아래 표는 `signal`/`decision_log`/`replan` 등 나머지 미구현 항목만 유효).

| type | 시점 | 내용 |
|---|---|---|
| `signal` | 매 사이클 | C2 채널 envelope(channel/state/quality/seq/payload) |
| `decision_log` | 판단마다 | C3 decisions(type 6종/score/reason/trigger/mettc_snapshot) |
| `replan` | 재계획 시 | 새 corridor/경로 |

계약: `docs/architecture/01-contracts.md` (C2 채널 / C3 decisions),
상태: `docs/architecture/uav/05-state-store.md` (platform_state / signals).
텔레메트리(`init`/`tick`) 계약: `infra/log/API.md` "실시간 텔레메트리 스트림" 절.

## 실행

### 대시보드 단독

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# http://localhost:8000
```

### 전체 스택 (수집기 + 시뮬 피더 + 대시보드)

로그수집기(`infra/log/log_server.py`)·신호발생기(`infra/vizsim/runner.py`)·대시보드를
한 번에 띄우는 로컬 dev 런처가 있다:

```bash
./scripts/dev_stack.sh
# 대시보드: http://localhost:8080  (Ctrl-C 로 전체 종료)
```

주요 환경변수(모두 선택, 기본값은 `scripts/dev_stack.sh` 참고):

| 변수 | 기본값 | 의미 |
|---|---|---|
| `COLLECTOR_PORT` | `8500` | 로그수집기(`log_server.py`) 포트 |
| `DASH_PORT` | `8080` | 대시보드 포트 |
| `SEED` | `42` | 시뮬 시드 |
| `BRIEF` | `examples/mission_brief_t3.json` | 미션 브리핑 JSON 경로 |
| `RATE` | `2` | 사이클 속도(Hz) |
| `SPEED` | `1` | 시뮬 속도 배율 |
| `DIRECTIVE` | (없음) | GCS 지시서(set_mission) JSON 경로 — 지정 시 위협 편향 반영 |

`COLLECTOR_PORT` 를 바꾸면 수집기·시뮬 피더·대시보드가 모두 그 포트로 정합된다.
프론트(`static/app.js`)는 정적 `/config.json` 을 백엔드 `/config` 보다 먼저 조회하므로,
`dev_stack.sh` 는 실행 중 `static/config.json` 을 `COLLECTOR_PORT` 기준으로 런타임
재생성했다가 종료 시(Ctrl-C 포함) 원본으로 복원한다 — 저장소에 커밋된
`config.json` 의 기본값(8500)은 실행 후에도 그대로 유지된다:

```bash
COLLECTOR_PORT=8600 ./scripts/dev_stack.sh
```

## 현재 상태

스켈레톤 — 서버/엔드포인트/핸들러 골격 + 최소 UI. 실제 렌더·수신 로직은 TODO.
