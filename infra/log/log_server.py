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
import itertools
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# GCS 탭용 온보드 파이프라인 연동 — repo src/ 와 이 디렉터리(pipeline_feeder)를
# import 경로에 추가한다.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _extra in (_REPO_ROOT / "src", Path(__file__).resolve().parent):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

EXAMPLES_DIR = _REPO_ROOT / "examples"

# import 실패 시에도 로그 스트림(/log, /logs, /health)은 기동 — /gcs/* 만 503 반환.
try:
    from onboard.run import run_cycle
    from pipeline_feeder import cycle_to_log_entries

    _PIPELINE_IMPORT_ERROR: str | None = None
except Exception as _exc:  # noqa: BLE001
    run_cycle = None  # type: ignore[assignment]
    cycle_to_log_entries = None  # type: ignore[assignment]
    _PIPELINE_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"

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

# CORS — 정적 대시보드(S3 등 타 오리진)가 /gcs/* 를 직접 호출하도록 허용.
# dev 는 전체 오리진 허용. 운영(prod)에서는 대시보드 오리진으로 제한할 것.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

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


# ── GCS(관측소) 탭 — mission_brief 조립·파이프라인 실행 엔드포인트 ──
# (대시보드 정적화를 위해 infra/dashboard/main.py 에서 이전됨.)

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
async def gcs_run(body: dict[str, Any]) -> dict[str, Any]:
    """{"raw", "mission_brief"} 로 온보드 run_cycle 1사이클 실행 후
    결과 로그를 인프로세스 hub 에 직접 publish (HTTP self-post 없음)."""
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
    for entry in entries:
        await hub.publish({**entry, "ts": int(time.time() * 1000)})
    return {"result": result, "log_published": True, "correlation_id": correlation_id}


# debt: 단일 프로세스 인메모리 큐(멀티프로세스/멀티인스턴스 broadcast 미지원).
#       수평 확장 시 Redis pub/sub 등 외부 브로커로 업그레이드. 재밍 대응도 미정.

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8500)
