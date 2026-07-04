"""D4D 실시간 로그수집기(log_server.py) 계약 테스트.

infra/log/API.md 계약(POST /log, WS /logs, GET /health, backlog ring)을 검증한다.

주의: WS 클라이언트와 동시에 HTTP 요청을 보내는 테스트는 `with TestClient(app) as client:`
형태로 client를 컨텍스트 매니저로 열어야 한다 — 그래야 client가 여는 모든 세션이 하나의
포털(이벤트 루프)을 공유해, 서로 다른 이벤트 루프에 걸친 send/receive로 인한 교착을 피한다
(starlette TestClient의 알려진 함정).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi")

import log_server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(autouse=True)
def reset_hub() -> None:
    """각 테스트 전 module-global hub를 새 LogHub로 교체해 backlog 오염을 막는다."""
    log_server.hub = log_server.LogHub()


def _entry(**overrides: object) -> dict:
    base = {"correlation_id": "A001", "layer": "sensor", "log": "배터리 부족", "level": "warn"}
    base.update(overrides)
    return base


def test_post_log_minimal_ok() -> None:
    with TestClient(log_server.app) as client:
        resp = client.post("/log", json={"correlation_id": "A001", "layer": "sensor", "log": "배터리 부족"})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_post_log_missing_correlation_id_422() -> None:
    with TestClient(log_server.app) as client:
        resp = client.post("/log", json={"layer": "sensor", "log": "배터리 부족"})
        assert resp.status_code == 422


def test_post_log_ts_omitted_filled_with_epoch_ms_int() -> None:
    with TestClient(log_server.app) as client:
        before = int(time.time() * 1000)
        resp = client.post("/log", json=_entry())
        after = int(time.time() * 1000)
        assert resp.status_code == 200

        health = client.get("/health").json()
        assert health["backlog"] == 1
        backlogged = log_server.hub.backlog()[0]
        assert isinstance(backlogged["ts"], int)
        assert before <= backlogged["ts"] <= after


def test_post_log_level_omitted_defaults_info() -> None:
    with TestClient(log_server.app) as client:
        resp = client.post(
            "/log", json={"correlation_id": "A001", "layer": "sensor", "log": "배터리 부족"}
        )
        assert resp.status_code == 200
        backlogged = log_server.hub.backlog()[0]
        assert backlogged["level"] == "info"


def test_ws_logs_receives_backlog_in_order() -> None:
    with TestClient(log_server.app) as client:
        client.post("/log", json=_entry(correlation_id="A001", log="first"))
        client.post("/log", json=_entry(correlation_id="A002", log="second"))

        with client.websocket_connect("/logs") as ws:
            first = ws.receive_json()
            second = ws.receive_json()
            assert first["log"] == "first"
            assert second["log"] == "second"


def test_ws_logs_receives_live_push_while_connected() -> None:
    with TestClient(log_server.app) as client:
        with client.websocket_connect("/logs") as ws:
            client.post("/log", json=_entry(correlation_id="A003", log="live"))
            received = ws.receive_json()
            assert received["log"] == "live"
            assert received["correlation_id"] == "A003"


def test_health_returns_status_and_backlog_count() -> None:
    with TestClient(log_server.app) as client:
        client.post("/log", json=_entry())
        client.post("/log", json=_entry())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "backlog": 2}


def test_backlog_ring_buffer_caps_at_backlog_size() -> None:
    with TestClient(log_server.app) as client:
        total = log_server.BACKLOG_SIZE + 5
        for i in range(total):
            client.post("/log", json=_entry(correlation_id=f"A{i:04d}", log=f"entry-{i}"))

        health = client.get("/health").json()
        assert health["backlog"] == log_server.BACKLOG_SIZE

        with client.websocket_connect("/logs") as ws:
            received = [ws.receive_json() for _ in range(log_server.BACKLOG_SIZE)]
            assert len(received) == log_server.BACKLOG_SIZE
            # 링버퍼는 가장 오래된 5개를 밀어냈으므로 첫 수신 항목은 entry-5 여야 한다.
            assert received[0]["log"] == "entry-5"
            assert received[-1]["log"] == f"entry-{total - 1}"
