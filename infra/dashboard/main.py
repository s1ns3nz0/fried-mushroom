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

import itertools
import json
import os
import re
import sys
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"

# GCS 탭용 온보드 파이프라인 연동 — repo src/ 와 infra/log 를 import 경로에 추가.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _extra in (_REPO_ROOT / "src", _REPO_ROOT / "infra" / "log"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

EXAMPLES_DIR = _REPO_ROOT / "examples"

# /gcs/run 결과 로그를 전송할 로그수집기 URL (환경변수로 재정의 가능).
LOG_COLLECTOR_URL = os.environ.get("LOG_COLLECTOR_URL", "http://localhost:8500/log")

# import 실패 시에도 대시보드(관측 뷰)는 기동 — /gcs/run 만 503 반환.
try:
    from onboard.run import run_cycle
    from pipeline_feeder import cycle_to_log_entries, post_entries

    _PIPELINE_IMPORT_ERROR: str | None = None
except Exception as _exc:  # noqa: BLE001
    run_cycle = None  # type: ignore[assignment]
    cycle_to_log_entries = None  # type: ignore[assignment]
    post_entries = None  # type: ignore[assignment]
    _PIPELINE_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

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
        # 활성 WebSocket 연결 집합 보관.
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        """새 클라이언트 핸드셰이크 수락 후 등록."""
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        """연결 종료된 클라이언트 제거(멱등)."""
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """message(JSON)를 모든 활성 클라이언트로 팬아웃.

        전송 중 죽은 소켓은 수거. iterate 중 변경 방지 위해 사본 순회
        (infra/log/log_server.py LogHub.publish 패턴과 동일).
        """
        dead: list[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()

# 모듈 전역 상태 캐시 — 신규 뷰어 접속 시 최신 스냅샷을 재전송하기 위함.
state: dict[str, Any] = {
    "init": None,
    "tick": None,
    "signals": {},
    "decisions": deque(maxlen=100),
    "replan": None,
}


def dispatch(message: dict[str, Any]) -> bool:
    """수신 메시지를 type별로 상태 캐시에 반영한다(판단 없음, 관측 전용).

    message["type"] ∈ MESSAGE_TYPES. 알려진 타입이면 True, 알 수 없는
    타입(또는 타입 누락)이면 조용히 드롭하고 False를 반환한다.
    message 내용은 변형하지 않는다.
    """
    msg_type = message.get("type")
    if msg_type == "init":
        # terrain DEM·corridor 캐시(신규 뷰어 접속 시 초기 스냅샷 재전송용).
        state["init"] = message
    elif msg_type == "tick":
        # platform_state 최신값 갱신.
        state["tick"] = message
    elif msg_type == "signal":
        # C2 채널 스냅샷 갱신(channel별 최신 state/quality). payload 안에
        # channel이 있을 수도 있어 방어적으로 조회한다.
        channel = message.get("channel")
        if channel is None:
            payload = message.get("payload")
            if isinstance(payload, dict):
                channel = payload.get("channel")
        if channel is not None:
            state["signals"][channel] = message
    elif msg_type == "decision_log":
        # C3 decisions 로그 append(최대 100건 보관).
        state["decisions"].append(message)
    elif msg_type == "replan":
        # 재계획 경로 갱신.
        state["replan"] = message
    else:
        # 알 수 없는 타입 드롭(관측 전용 — 예외 없이 무시).
        return False
    return True


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
    # 신규 뷰어에게만 캐시된 스냅샷을 순서대로 재전송(init → tick → signal → replan).
    if state["init"] is not None:
        await ws.send_json(state["init"])
    if state["tick"] is not None:
        await ws.send_json(state["tick"])
    for signal_msg in state["signals"].values():
        await ws.send_json(signal_msg)
    if state["replan"] is not None:
        await ws.send_json(state["replan"])
    try:
        while True:
            message = await ws.receive_json()
            if dispatch(message):
                await manager.broadcast(message)
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ── GCS(관측소) 탭 — mission_brief 조립·파이프라인 실행 엔드포인트 ──

# 시나리오 태그 화이트리스트(영숫자/언더스코어) — 경로 조작 차단.
_TAG_RE = re.compile(r"^[A-Za-z0-9_]+$")

# /gcs/run 상관ID용 시퀀스 카운터(raw.seq 미제공 시 사용).
_run_seq = itertools.count(1)


def _load_example(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/gcs/scenarios")
def gcs_scenarios() -> list[dict[str, Any]]:
    """examples/ 에서 raw_{tag}.json + mission_brief_{tag}.json 쌍을 스캔."""
    scenarios: list[dict[str, Any]] = []
    for raw_path in sorted(EXAMPLES_DIR.glob("raw_*.json")):
        tag = raw_path.stem[len("raw_"):]
        brief_path = EXAMPLES_DIR / f"mission_brief_{tag}.json"
        if not brief_path.exists():
            continue
        try:
            brief = _load_example(brief_path)
        except Exception:  # noqa: BLE001
            continue
        scenarios.append(
            {
                "tag": tag,
                "sortie_id": brief.get("sortie_id"),
                "mission_context": brief.get("mission_context"),
            }
        )
    return scenarios


@app.get("/gcs/scenario/{tag}")
def gcs_scenario(tag: str) -> dict[str, Any]:
    """태그 1건의 raw 센서 입력 + mission_brief 반환."""
    if not _TAG_RE.match(tag):
        raise HTTPException(status_code=404, detail=f"잘못된 시나리오 태그: {tag!r}")
    raw_path = EXAMPLES_DIR / f"raw_{tag}.json"
    brief_path = EXAMPLES_DIR / f"mission_brief_{tag}.json"
    if not raw_path.exists() or not brief_path.exists():
        raise HTTPException(status_code=404, detail=f"시나리오 없음: {tag}")
    try:
        return {"raw": _load_example(raw_path), "mission_brief": _load_example(brief_path)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"시나리오 파일 손상: {exc}") from exc


@app.post("/gcs/run")
def gcs_run(body: dict[str, Any]) -> dict[str, Any]:
    """{"raw", "mission_brief"} 로 온보드 run_cycle 1사이클 실행 후
    결과 로그를 로그수집기로 best-effort 전송(pipeline_feeder 재사용)."""
    if run_cycle is None:
        raise HTTPException(
            status_code=503,
            detail=f"온보드 파이프라인 import 실패로 실행 불가: {_PIPELINE_IMPORT_ERROR}",
        )
    raw = body.get("raw")
    mission_brief = body.get("mission_brief")
    if not isinstance(raw, dict) or not isinstance(mission_brief, dict):
        raise HTTPException(
            status_code=400,
            detail='body 는 {"raw": {...}, "mission_brief": {...}} 형식이어야 함',
        )
    try:
        result = run_cycle(raw, mission_brief)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"run_cycle 실패: {exc}") from exc

    seq = raw.get("seq") or next(_run_seq)
    sortie_id = mission_brief.get("sortie_id", "SORTIE")
    correlation_id = f"{sortie_id}-{seq}"
    entries = cycle_to_log_entries(correlation_id, result)
    try:
        delivered = len(entries) > 0 and post_entries(entries, LOG_COLLECTOR_URL) == len(entries)
    except Exception:  # noqa: BLE001
        delivered = False
    return {"result": result, "log_delivered": delivered, "correlation_id": correlation_id}


# 정적 자산(app.js, style.css) 마운트.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
