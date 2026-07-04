"""D4D 실시간 텔레메트리 스트림(POST /init, POST /tick, WS /stream) 계약 테스트.

로그 스트림(/log, /logs, hub)과 완전히 분리된 stream_hub 를 검증한다.

주의: WS 클라이언트와 동시에 HTTP 요청을 보내는 테스트는 `with TestClient(app) as client:`
형태로 client를 컨텍스트 매니저로 열어야 한다 — 그래야 client가 여는 모든 세션이 하나의
포털(이벤트 루프)을 공유해, 서로 다른 이벤트 루프에 걸친 send/receive로 인한 교착을 피한다
(starlette TestClient의 알려진 함정).
"""

from __future__ import annotations

import log_server
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_hub() -> None:
    """각 테스트 전 hub/stream_hub/latest_init 를 초기 상태로 되돌려 오염을 막는다."""
    log_server.hub = log_server.LogHub()
    log_server.stream_hub = log_server.LogHub()
    log_server.latest_init = None
    log_server.latest_control = {"speed": 1.0}


def test_post_init_then_ws_stream_first_message_is_init() -> None:
    with TestClient(log_server.app) as client:
        resp = client.post("/init", json={"battery": 100, "lat": 37.0})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        with client.websocket_connect("/stream") as ws:
            first = ws.receive_json()
            assert first["type"] == "init"
            assert first["battery"] == 100
            assert first["lat"] == 37.0


def test_post_tick_while_stream_connected_delivers_tick() -> None:
    with TestClient(log_server.app) as client:
        with client.websocket_connect("/stream") as ws:
            resp = client.post("/tick", json={"battery": 99, "lat": 37.001})
            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}

            received = ws.receive_json()
            assert received["type"] == "tick"
            assert received["battery"] == 99
            assert received["lat"] == 37.001


def test_new_stream_connection_after_many_ticks_still_gets_init_first() -> None:
    with TestClient(log_server.app) as client:
        client.post("/init", json={"battery": 100})

        for i in range(100):
            client.post("/tick", json={"seq": i})

        with client.websocket_connect("/stream") as ws:
            first = ws.receive_json()
            assert first["type"] == "init"
            assert first["battery"] == 100


def test_post_log_does_not_appear_on_stream() -> None:
    with TestClient(log_server.app) as client:
        client.post("/init", json={"battery": 100})

        with client.websocket_connect("/stream") as ws:
            first = ws.receive_json()
            assert first["type"] == "init"
            # backlog replay(subscribe) 도 같은 init 항목 1건을 재전송한다.
            backlog_replay = ws.receive_json()
            assert backlog_replay["type"] == "init"

            client.post("/log", json={"correlation_id": "A001", "layer": "sensor", "log": "누출"})
            client.post("/tick", json={"seq": 1})

            received = ws.receive_json()
            assert received["type"] == "tick"
            assert received["seq"] == 1


def test_post_control_merges_then_get_control_returns_it() -> None:
    with TestClient(log_server.app) as client:
        resp = client.post("/control", json={"speed": 8})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "control": {"speed": 8}}

        resp = client.get("/control")
        assert resp.status_code == 200
        assert resp.json()["speed"] == 8


def test_post_control_reset_merges_and_preserves_speed() -> None:
    with TestClient(log_server.app) as client:
        client.post("/control", json={"reset": 1})

        resp = client.get("/control")
        assert resp.status_code == 200
        data = resp.json()
        assert data["reset"] == 1
        assert data["speed"] == 1.0
