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

## 미정 (확장)

- **멀티인스턴스/멀티프로세스**: 현재 단일 프로세스 인메모리 큐만 지원. 수평 확장 시
  broadcast를 Redis pub/sub 등 외부 브로커로 옮겨야 함 — **미정**.
- **재밍(EW) 대응**: C2 링크 저하·단절 시 실시간 스트림 유실 처리 정책 — **미정**
  (무손실이 필요한 데이터는 raw_log 계층으로 커버).
- **인증·backpressure**: 미구현 — **미정**.
