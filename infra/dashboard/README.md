# dashboard

D4D 온보드 AI **관측 대시보드** — FastAPI + WebSocket + Vanilla JS Canvas.

## 역할

uav(온보드)의 상태·판단 결과를 실시간으로 **시각화**한다.

- 좌상 **지도**: 지형 + 경로 + 드론 위치 + 위협 (placeholder — uav tick WS 연동 대기)
- 우상 **고도**: 지형 표고 + 드론 고도 프로파일 (placeholder)
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

## WS 메시지 타입 (`/ws`, Phase 2 자리표시)

uav 소스에서 수신 → 모든 뷰어로 브로드캐스트 (tick/signal/decision 등, 미구현 스텁).

| type | 시점 | 내용 |
|---|---|---|
| `init` | 임무 시작 1회 | terrain DEM·corridor·초기 적 위치 |
| `tick` | 매 tick | platform_state(pos/alt/battery/gps/comms/attitude/speed) |
| `signal` | 매 사이클 | C2 채널 envelope(channel/state/quality/seq/payload) |
| `decision_log` | 판단마다 | C3 decisions(type 6종/score/reason/trigger/mettc_snapshot) |
| `replan` | 재계획 시 | 새 corridor/경로 |

계약: `docs/architecture/01-contracts.md` (C2 채널 / C3 decisions),
상태: `docs/architecture/uav/05-state-store.md` (platform_state / signals).

## 실행

```bash
pip install -r requirements.txt
uvicorn main:app --reload
# http://localhost:8000
```

## 현재 상태

스켈레톤 — 서버/엔드포인트/핸들러 골격 + 최소 UI. 실제 렌더·수신 로직은 TODO.
