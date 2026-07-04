"""로그 수집기 — FastAPI 서버 엔트리 (스켈레톤).

collector.LogCollector를 감싸 HTTP POST /raw_log 로 uav의 raw_log 업로드를 수신한다.
uvicorn 실행 대상: `uvicorn main:app`(infra/log/Dockerfile 참고).

raw_log 저장 위치는 docker-compose.yml의 log-data 볼륨 마운트 경로와 맞춘다
(/var/log/fried-mushroom-uav).

→ 수신·저장 로직 본체: collector.py (아직 스켈레톤 — NotImplementedError).
"""

from __future__ import annotations

from fastapi import FastAPI, Request

from collector import LogCollector

app = FastAPI(title="D4D Log Collector", version="0.1.0")
collector = LogCollector(store_dir="/var/log/fried-mushroom-uav")


@app.post("/raw_log")
async def receive_raw_log(request: Request) -> dict[str, str]:
    """uav → raw_log 업로드 수신. collector.receive_post로 위임."""
    body = await request.body()
    path = collector.receive_post(body)
    return {"stored": str(path)}
