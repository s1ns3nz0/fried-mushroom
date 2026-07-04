"""D4D 대시보드 — FastAPI + WebSocket 서버 (스켈레톤).

역할: uav(온보드)에서 흘러오는 상태·판단 로그를 WebSocket으로 수신해
브라우저 클라이언트에 브로드캐스트하고, 정적 UI(Canvas)를 서빙한다.

**대시보드는 판단하지 않는다** — 표시(관측)만 담당. 판단 주체는 uav 위험 평가 계층.
→ 계약: docs/architecture/01-contracts.md (C2 채널 / C3 decisions)
→ 상태: docs/architecture/uav/05-state-store.md (platform_state / signals)

WS 메시지 타입 (수신 → 브로드캐스트):
- init         : 임무 시작 1회 — terrain DEM·corridor·초기 적 위치 (terrain_db 스냅샷)
- tick         : 매 tick — platform_state(pos/alt/battery/gps/comms/attitude/speed)
- signal       : 매 사이클 — C2 의미 채널 envelope(channel/state/quality/seq/payload)
- decision_log : C3 decisions(type 6종/score/reason/trigger/mettc_snapshot/tick)
- replan       : 경로 재계획 이벤트(reroute) — 새 corridor/경로

TODO(Phase 2): 인증, uav 소스 연결(업스트림 WS 또는 log 수집기 연동), 상태 버퍼링.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"

# 브라우저가 직접 연결할 로그수집기 WS /logs 기본 URL (설정값/기본).
# 환경변수 DASHBOARD_LOG_WS_URL 로 재정의 가능.
LOG_WS_URL = os.environ.get("DASHBOARD_LOG_WS_URL", "ws://localhost:8500/logs")

# 대시보드가 수신·중계하는 WS 메시지 타입 (계약 참조).
MESSAGE_TYPES = ("init", "tick", "signal", "decision_log", "replan")

app = FastAPI(title="D4D Dashboard", version="0.1.0")


class ConnectionManager:
    """연결된 브라우저 클라이언트를 관리하고 메시지를 브로드캐스트한다.

    uav 소스(업스트림)에서 받은 상태·판단 메시지를 모든 대시보드 뷰어에
    그대로 전달하는 팬아웃 허브. 판단·가공 없음(관측 전용).
    """

    def __init__(self) -> None:
        # TODO: 활성 WebSocket 연결 집합 보관.
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        """새 클라이언트 핸드셰이크 수락 후 등록."""
        # TODO: await ws.accept() 후 self.active에 추가.
        raise NotImplementedError

    def disconnect(self, ws: WebSocket) -> None:
        """연결 종료된 클라이언트 제거."""
        # TODO: self.active에서 제거.
        raise NotImplementedError

    async def broadcast(self, message: dict[str, Any]) -> None:
        """message(JSON)를 모든 활성 클라이언트로 팬아웃."""
        # TODO: self.active 순회하며 ws.send_json(message).
        raise NotImplementedError


manager = ConnectionManager()


def dispatch(message: dict[str, Any]) -> None:
    """수신 메시지를 type별 핸들러로 분기(스텁).

    message["type"] ∈ MESSAGE_TYPES. 대시보드는 검증·정규화만 하고
    브로드캐스트한다(판단 없음).
    """
    msg_type = message.get("type")
    if msg_type == "init":
        # TODO: terrain DEM·corridor 캐시(신규 뷰어 접속 시 초기 스냅샷 재전송용).
        raise NotImplementedError
    elif msg_type == "tick":
        # TODO: platform_state 최신값 갱신.
        raise NotImplementedError
    elif msg_type == "signal":
        # TODO: C2 채널 스냅샷 갱신(channel별 최신 state/quality).
        raise NotImplementedError
    elif msg_type == "decision_log":
        # TODO: C3 decisions 로그 append.
        raise NotImplementedError
    elif msg_type == "replan":
        # TODO: 재계획 경로 갱신.
        raise NotImplementedError
    else:
        # TODO: 알 수 없는 타입 로깅/드롭.
        raise NotImplementedError


@app.get("/")
async def index() -> FileResponse:
    """대시보드 UI(정적 index.html) 서빙."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/config")
async def config() -> dict[str, Any]:
    """프론트 런타임 설정. 로그수집기 WS /logs 기본 URL을 노출한다.

    대시보드는 로그수집기 WS에 **브라우저에서 직접** 연결하므로
    서버는 URL만 알려주고 프록시하지 않는다(관측 전용).
    """
    return {"log_ws_url": LOG_WS_URL}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    """대시보드 WS 엔드포인트.

    수신한 uav 상태·판단 메시지를 dispatch → 모든 뷰어로 broadcast.
    """
    await manager.connect(ws)
    try:
        while True:
            # TODO: message = await ws.receive_json(); dispatch(message);
            #       await manager.broadcast(message)
            raise NotImplementedError
    except WebSocketDisconnect:
        manager.disconnect(ws)


# 정적 자산(app.js, style.css) 마운트.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
