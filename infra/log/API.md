# 실시간 로그수집기 API (log_server.py)

레이어 로그 스트림 → 큐 → 대시보드 실시간 출력. **운영 관측용** 계약 규약.

> 이 문서의 계약(엔드포인트·JSON 포맷)은 **대시보드(`infra/dashboard/`)와 공유하는
> 고정 계약**이다. 변경 시 양측 합의 필요.

## 역할 — raw_log와 구분

`infra/log/`에는 성격이 다른 **두 로그 계층**이 공존한다.

| 계층 | 파일 | 성격 | 저장 | 시점 |
|---|---|---|---|---|
| **실시간 로그 스트림** | `log_server.py` | 운영 관측용 — 레이어 로그를 대시보드에 즉시 push | 인메모리(휘발성) | 비행 **중** 실시간 |
| **raw_log** | `collector.py` · `aggregate.py` · `store.py` | 비행후 RAG 학습용 — 무손실 원본 저장 → episode_index 집계 | 파일시스템 + SQLite | 착륙 **후** 일괄 |

이 문서는 **실시간 로그 스트림**만 다룬다. raw_log는 `README.md` 참고.

## 아키텍처

```
 ┌──────────┐   POST /log                ┌───────────────────────────┐   WS /logs
 │  sensor  │ ─ {correlation_id, log} ─▶ │      로그수집기            │ ─ broadcast ─▶ ┌───────────┐
 ├──────────┤                            │  (log_server.py)          │               │ 대시보드   │
 │abstraction│ ─────────────────────────▶│                           │ ◀─ 접속 시 ──  │(dashboard)│
 ├──────────┤                            │  backlog ring buffer(100) │   backlog 전송 └───────────┘
 │   risk   │ ─────────────────────────▶│  + WS 구독자 set          │
 ├──────────┤                            │                           │
 │ response │ ─────────────────────────▶│  ← 인메모리, 단일 인스턴스 │
 └──────────┘                            └───────────────────────────┘
```

- 각 레이어가 `correlation_id`와 함께 로그를 `POST /log`로 보낸다.
- 로그수집기는 backlog 링버퍼에 쌓고, 접속 중인 모든 WS 구독자에게 broadcast.
- 대시보드는 `WS /logs`로 접속 → 최근 backlog 수신 → 이후 실시간 push 수신.
- `correlation_id`로 하나의 이벤트(여러 레이어 로그)를 묶어 추적한다.

## 로그 포맷 (공유 JSON)

`POST /log` 요청 body = `WS /logs` broadcast 메시지 = **동일 포맷**.

```json
{
  "correlation_id": "A001",
  "layer": "sensor",
  "log": "배터리 부족",
  "level": "warn",
  "ts": 1751600000000
}
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `correlation_id` | string(uuid) | ✅ | 이벤트 추적 id. 여러 레이어 로그를 하나의 이벤트로 묶음(예: `"A001"`). |
| `layer` | string | ✅ | 발신 레이어. `sensor` \| `abstraction` \| `risk_assessment` \| `response` \| `...` |
| `log` | string | ✅ | 로그 메시지(예: `"배터리 부족"`). |
| `level` | string | ❌ | `info` \| `warn` \| `error`. 없으면 `info`. |
| `ts` | int(epoch ms) | ❌ | 발생 시각. 없으면 **서버 수신 시각**으로 채움. |

### correlation_id 규칙

- uuid 형식 권장. 하나의 이벤트(예: "배터리 부족 감지 → 위험평가 → 대응")를 관통하는 로그들은
  **같은 correlation_id**를 공유 → 대시보드에서 이벤트 단위로 추적·그룹핑.

### layer 값 목록

`sensor`, `abstraction`, `risk_assessment`, `response` (+ 확장 여지 `...`).

### level 값

`info`(기본), `warn`, `error`.

## AI 결정 로그 항목 계약 — 04 탐지 / 05 평가 (#105 · #104)

`pipeline_feeder.cycle_to_log_entries`(및 인프로세스 `/gcs/run`)가 `run_cycle` 결과의
`threat`(04)/`risk`(05) 출력을 아래 **고정 라인 포맷**으로 변환해 `POST /log`로 스트림한다.
대시보드 AI 결정 로그의 탐지/평가 행은 이 라인을 그대로 소비한다. 실데이터 소스는
`python -m onboard ... --log run.jsonl` 의 `layer=threat|risk` 라인(`output` = 레이어 출력 dict)과 동일 계약이다.
포맷 변경 시 양측 합의 필요 — 계약 테스트: `infra/log/test_pipeline_feeder.py`.

### `layer=threat` — 04 탐지 행

| 케이스 | log 포맷 | level |
|---|---|---|
| primary 존재 | `04 위협 · primary={threat_event} conf={confidence:.2f} killchain={kill_chain_stage} cands={candidates 수}` | `warn` |
| 후보 없음 (`primary=None`) | `04 위협 · 후보 없음` | `info` |

예: `04 위협 · primary=T3 conf=0.92 killchain=후기 cands=1`

### `layer=risk` — 05 평가 행 (rank-1 후보 = `priority_rank` 최솟값)

| 케이스 | log 포맷 | level |
|---|---|---|
| candidates 존재 | `05 위험 · RAC={rac} L={l_class_final} S={severity_label_final} urgency={compound_urgency_score:.2f} rank={priority_rank}` | `rac ∈ {High, Serious}` → `error`, 그 외 `warn` |
| 위협 없음 (`candidates=[]`) | `05 위험 · 위협 없음 ambient={ambient_rac}` (05 계약상 항상 `Low`) | `info` |

예: `05 위험 · RAC=Serious L=B S=Critical urgency=0.22 rank=1`

필드 의미는 [`docs/contracts/04-threat-modeling-output.md`](../../docs/contracts/04-threat-modeling-output.md) ·
[`docs/contracts/05-risk-assessment-output.md`](../../docs/contracts/05-risk-assessment-output.md) 참조.

## 엔드포인트

### `POST /log` — 레이어 → 로그수집기

레이어가 로그 1건을 전송한다.

- **요청 body**: 위 로그 포맷(JSON). `correlation_id`/`layer`/`log` 필수.
- **응답**: `200` `{"status": "ok"}`
- 동작: 검증 → backlog 링버퍼 적재 → 모든 WS 구독자에 broadcast. `ts` 없으면 서버가 채움.

```bash
curl -X POST http://localhost:8500/log \
  -H 'Content-Type: application/json' \
  -d '{"correlation_id":"A001","layer":"sensor","log":"배터리 부족","level":"warn"}'
# → {"status":"ok"}
```

### `WS /logs` — 로그수집기 → 대시보드

대시보드가 실시간 로그를 구독한다.

- **접속 시**: 최근 backlog(최대 100개)를 로그 포맷 JSON으로 순차 전송.
- **이후**: 큐에 들어오는 새 로그를 실시간 broadcast(동일 포맷).
- **클라이언트 → 서버 메시지**: 수신 전용이므로 무시(연결 유지 용도).
- 연결 해제 시 구독자 목록에서 자동 제거.

### `GET /health`

- **응답**: `200` `{"status": "ok", "backlog": <현재 backlog 크기>}`

## 예시 시나리오

1. `sensor` 레이어가 배터리 부족을 감지 →
   `POST /log {"correlation_id":"A001","layer":"sensor","log":"배터리 부족","level":"warn"}`
2. 로그수집기가 backlog에 적재 + 구독 중인 대시보드에 broadcast.
3. 대시보드가 `WS /logs`로 해당 JSON 수신 → 화면에 `[A001][sensor][warn] 배터리 부족` 출력.
4. 이후 같은 이벤트의 후속 로그(예: `risk_assessment`가 같은 `A001`로 위험도 로그)도
   같은 correlation_id로 묶여 대시보드에서 하나의 이벤트로 추적된다.

## 실시간 텔레메트리 스트림 (신호발생기 → 대시보드)

신호발생기(`infra/sim/runner.py`)가 보내는 시나리오 초기 스냅샷·틱 텔레메트리를
대시보드 라이브 모드에 실시간 push하는 계약. **레이어 로그 스트림(`/log`·`/logs`,
`hub`)과는 완전히 분리된 별도 허브(`stream_hub`)를 사용한다** — `/log`로 들어온
로그는 `/stream`에 나타나지 않고, 그 반대도 마찬가지다.

```
 ┌────────────┐  POST /init {시나리오 스냅샷}   ┌──────────────────────────┐  WS /stream
 │ 신호발생기  │ ─────────────────────────────▶ │  log_server.py           │ ─ broadcast ─▶ ┌───────────┐
 │ (sim)      │  POST /tick {틱 텔레메트리}     │  stream_hub (hub와 분리) │               │ 대시보드   │
 └────────────┘ ─────────────────────────────▶ │  + latest_init 보관      │ ◀─ 접속 시 ──  │ 라이브 모드│
                                                └──────────────────────────┘  init 최우선  └───────────┘
```

### `POST /init` — 신호발생기 → 스트림

시나리오 시작 시 초기 스냅샷 1건을 전송한다.

- **요청 body**: 임의 JSON 객체(`dict`). 예: `{"battery": 100, "lat": 37.0, ...}`
- **응답**: `200` `{"status": "ok"}`
- 동작: body를 `latest_init`으로 보관 → `{"type": "init", **body}`를 stream_hub
  backlog 적재 + 모든 `/stream` 구독자에 broadcast.

### `POST /tick` — 신호발생기 → 스트림

주기 틱 텔레메트리 1건을 전송한다.

- **요청 body**: 임의 JSON 객체(`dict`). 예: `{"battery": 99, "lat": 37.001, ...}`
- **응답**: `200` `{"status": "ok"}`
- 동작: `{"type": "tick", **body}`를 stream_hub backlog 적재 + 구독자 broadcast.

#### 확장 페이로드 필드 (runner → log_server)

신호발생기(`infra/sim/runner.py`의 `build_tick_payload`)가 틱마다 보내는 텔레메트리 페이로드는 다음 두 필드를 추가로 포함한다:

##### `channels` (배열)
03 센서 추상화 레이어의 11채널 실 출력을 pass-through로 포함한다. 대시보드 신호 패널이 소비.

| 필드 | 타입 | 설명 |
|---|---|---|
| `channel` | string | 채널명 (예: `battery`, `link_quality`, `proximity_object`, ...) |
| `state` | float \| int \| bool \| null | 채널 값 |
| `quality` | float \| null | 신뢰도 (0.0~1.0) |
| `quality_delta` | float \| null | 이전 틱 대비 신뢰도 변화량 |
| `payload` | dict \| null | 채널별 추가 데이터 (예: 음향 classification) |

예시:
```json
{
  "channel": "battery",
  "state": 85.5,
  "quality": 0.98,
  "quality_delta": 0.01,
  "payload": null
}
```

##### `decision` (객체)
04~07 파이프라인 판정 실값을 포함한다. 대시보드 AI 결정 모델이 소비.

| 필드 | 타입 | 설명 |
|---|---|---|
| `threat` | object | 04 위협탐지 결과 |
| `threat.primary` | object \| null | primary 위협 (있으면: `threat_event`, `confidence`, `kill_chain_stage`; 없으면 null) |
| `risk` | object \| null | 05 위험평가 결과 (있으면: `rac`, `compound_urgency_score`; 없으면 null) |
| `response` | object | 06 대응 판정 |
| `response.flight_action` | string \| null | 비행 행동 (예: `Hold`, `RTB`, `Avoid`) |
| `response.comms_level` | string \| null | 통신 제한 수준 |
| `response.rac` | string \| null | 대응 권고 RAC (예: `Low`, `High`) |
| `response.threat_category` | string \| null | 분류된 위협 카테고리 |
| `flight_plan` | object | 07 비행계획 판정 |
| `flight_plan.flight_action` | string \| null | 계획된 비행 행동 |
| `flight_plan.target_bearing_deg` | float \| null | 목표 방위각 (도) |
| `flight_plan.altitude_delta_m` | float \| null | 고도 변화 (m) |
| `flight_plan.replan_scope` | string \| null | 재계획 범위 (예: `local`, `global`) |
| `flight_plan.speed_mode` | string \| null | 속도 모드 (예: `cruise`, `slow`) |

#### 예시 (두 필드 포함)

```json
{
  "seq": 42,
  "s": 0.125,
  "x": 0.234,
  "y": 0.567,
  "alt_m": 150.0,
  "flight_action": "Hold",
  "rac": "High",
  "channels": [
    {
      "channel": "battery",
      "state": 85.5,
      "quality": 0.98,
      "quality_delta": 0.01,
      "payload": null
    },
    {
      "channel": "link_quality",
      "state": 4,
      "quality": 0.92,
      "quality_delta": -0.05,
      "payload": null
    },
    {
      "channel": "proximity_object",
      "state": false,
      "quality": 0.88,
      "quality_delta": 0.0,
      "payload": {"nearest_distance_m": 245.6}
    }
  ],
  "decision": {
    "threat": {
      "primary": {
        "threat_event": "T3",
        "confidence": 0.92,
        "kill_chain_stage": "후기"
      }
    },
    "risk": {
      "rac": "Serious",
      "compound_urgency_score": 0.78
    },
    "response": {
      "flight_action": "Hold",
      "comms_level": "emergency",
      "rac": "Serious",
      "threat_category": "ambush"
    },
    "flight_plan": {
      "flight_action": "Avoid",
      "target_bearing_deg": 225.0,
      "altitude_delta_m": 50.0,
      "replan_scope": "local",
      "speed_mode": "slow"
    }
  }
}
```

#### 페이로드 소유권

- **소유자**: `runner` (`build_tick_payload` 함수). 페이로드 스키마 정의·생성 책임.
- **소비자**: 대시보드 `app.js`. `channels` → 신호 패널, `decision` → AI 결정 모델.
- **서버**: `log_server`는 free-form dict를 그대로 broadcast한다. 데이터 검증·변형 불가.
- **기존 필드 유지**: `seq`, `x`, `y`, `alt_m` 등 위치 필드와 top-level `flight_action`, `rac`은 하위호환성 위해 유지.

### `WS /stream` — 스트림 → 대시보드

대시보드 라이브 모드가 텔레메트리를 구독한다.

- **접속 시**: `latest_init`이 있으면 `{"type": "init", **latest_init}`을 **가장 먼저**
  전송 → 이후 stream_hub backlog(최대 100개) 순차 전송 → 실시간 push. 늦게 접속해도
  (틱이 많이 흘러 backlog에서 init이 밀려났어도) 항상 init을 먼저 받는다.
- **중복 init**: init이 backlog에 아직 남아 있으면 접속 직후 같은 init을 2번 받을 수
  있다(최우선 전송 1회 + backlog replay 1회). 대시보드가 멱등하게 처리한다.
- **메시지 구분**: 모든 메시지는 `type` 필드(`"init"` \| `"tick"`)로 구분.
- **클라이언트 → 서버 메시지**: 수신 전용이므로 무시(연결 유지 용도).
- 연결 해제 시 구독자 목록에서 자동 제거.

## 미정 (확장)

- **멀티인스턴스/멀티프로세스**: 현재 단일 프로세스 인메모리 큐만 지원. 수평 확장 시
  broadcast를 Redis pub/sub 등 외부 브로커로 옮겨야 함 — **미정**.
- **재밍(EW) 대응**: C2 링크 저하·단절 시 실시간 스트림 유실 처리 정책 — **미정**
  (무손실이 필요한 데이터는 raw_log 계층으로 커버).
- **인증·backpressure**: 미구현 — **미정**.
