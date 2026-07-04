"""실시간 로그수집기 — 레이어 로그 스트림 → 큐 → 대시보드 (운영 관측용).

각 레이어(sensor/abstraction/risk_assessment/response/...)가 correlation_id와
함께 로그를 POST /log로 보내면, 인메모리 링버퍼(backlog)에 쌓고 접속 중인
모든 WS /logs 구독자에게 실시간 broadcast한다. 대시보드가 이를 받아 화면에 출력한다.

```
레이어 → POST /log {correlation_id, layer, log, level, ts} → [backlog ring + subscribers]
                                                            → WS /logs broadcast → 대시보드
```

collector.py(raw_log)와의 역할 구분:
- 이 파일(log_server): **실시간 로그 스트림(운영 관측용)** — 비행 중 레이어 로그를
  correlation_id로 묶어 대시보드에 즉시 push. 인메모리, 휘발성, 무손실 보장 안 함.
- collector.py(raw_log)  : **비행후 RAG 학습용** — 착륙 후 무손실 원본을 파일 저장,
  episode_index로 집계. 실시간 아님(C2 링크 끊김 시 손상 방지).

correlation_id로 하나의 이벤트(여러 레이어 로그)를 묶어 추적한다.
→ 계약 규약: infra/log/API.md
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Literal, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

# 레이어 로그 스트림에서 다루는 레이어 값 목록(대시보드와 공유). "..."는 확장 여지.
LAYERS = ("sensor", "abstraction", "risk_assessment", "response")
# 로그 레벨(옵션, 기본 info).
LEVELS = ("info", "warn", "error")
# 접속 시 전송하는 backlog 크기(최근 N개).
BACKLOG_SIZE = 100


class LogEntry(BaseModel):
    """레이어 → 로그수집기 로그 1건 (POST /log 요청 = WS /logs 메시지 포맷)."""

    correlation_id: str = Field(..., description="이벤트 추적 id(uuid). 여러 레이어 로그를 묶는다.")
    layer: str = Field(..., description="발신 레이어(sensor|abstraction|risk_assessment|response|...).")
    log: str = Field(..., description="로그 메시지(예: '배터리 부족').")
    level: Literal["info", "warn", "error"] = Field("info", description="로그 레벨(옵션, 기본 info).")
    ts: Optional[int] = Field(None, description="epoch ms(옵션). 없으면 서버가 채운다.")


class LogHub:
    """인메모리 로그 허브 — backlog 링버퍼 + WS 구독자 set.

    단일 인스턴스(단일 프로세스) 가정. broadcast·구독자 관리를 담당한다.
    """

    def __init__(self, backlog_size: int = BACKLOG_SIZE) -> None:
        self._backlog: deque[dict[str, Any]] = deque(maxlen=backlog_size)
        self._subscribers: set[WebSocket] = set()

    async def publish(self, entry: dict[str, Any]) -> None:
        """로그 1건을 backlog에 넣고 모든 구독자에 broadcast."""
        self._backlog.append(entry)
        # broadcast 중 죽은 소켓은 수거. iterate 중 변경 방지 위해 사본 순회.
        dead: list[WebSocket] = []
        for ws in list(self._subscribers):
            try:
                await ws.send_json(entry)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._subscribers.discard(ws)

    async def subscribe(self, ws: WebSocket) -> None:
        """WS 연결 등록 + 접속 시 최근 backlog 전송."""
        self._subscribers.add(ws)
        for entry in list(self._backlog):
            await ws.send_json(entry)

    def unsubscribe(self, ws: WebSocket) -> None:
        """WS 연결 해제 처리."""
        self._subscribers.discard(ws)

    def backlog(self) -> list[dict[str, Any]]:
        """현재 backlog 스냅샷(디버그/헬스용)."""
        return list(self._backlog)


app = FastAPI(title="D4D 실시간 로그수집기", version="0.1.0")
hub = LogHub()


@app.post("/log")
async def post_log(entry: LogEntry) -> dict[str, str]:
    """레이어 → 로그수집기: 로그 1건 수신 → 큐 적재 + 구독자 broadcast."""
    record = entry.model_dump()
    if record["ts"] is None:
        record["ts"] = int(time.time() * 1000)  # 서버 수신 시각(epoch ms).
    await hub.publish(record)
    return {"status": "ok"}


@app.websocket("/logs")
async def ws_logs(ws: WebSocket) -> None:
    """로그수집기 → 대시보드: 접속 시 backlog 전송 후 실시간 push."""
    await ws.accept()
    await hub.subscribe(ws)
    try:
        while True:
            # 대시보드는 수신 전용. 연결 유지를 위해 수신 대기(클라 메시지는 무시).
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(ws)


@app.get("/health")
async def health() -> dict[str, Any]:
    """헬스체크 + 현재 backlog 크기."""
    return {"status": "ok", "backlog": len(hub.backlog())}


# debt: 단일 프로세스 인메모리 큐(멀티프로세스/멀티인스턴스 broadcast 미지원).
#       수평 확장 시 Redis pub/sub 등 외부 브로커로 업그레이드. 재밍 대응도 미정.

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8500)
