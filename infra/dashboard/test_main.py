"""D4D 대시보드 서버(main.py) 계약 테스트 — TDD.

ConnectionManager / dispatch / WS /ws 엔드포인트의 관측 전용(판단 없음) 동작을 검증한다.

주의: 여러 WS 클라이언트를 동시에 열어 브로드캐스트를 검증하는 테스트는
`with TestClient(app) as client:` 형태로 client를 컨텍스트 매니저로 열어야 한다.
그래야 client가 연 모든 websocket_connect() 세션이 하나의 포털(이벤트 루프)을
공유한다 — client를 열지 않으면 각 websocket_connect() 호출마다 별도 스레드/
이벤트 루프가 생겨, 서로 다른 루프에 걸친 send/receive가 교착될 수 있다
(starlette TestClient의 알려진 함정).
"""

from __future__ import annotations

import main
from fastapi.testclient import TestClient


def _reset_state() -> None:
    """모듈 전역 상태 캐시를 각 테스트 전 초기화한다(테스트 간 오염 방지)."""
    main.state["init"] = None
    main.state["tick"] = None
    main.state["signals"] = {}
    main.state["decisions"].clear()
    main.state["replan"] = None


def test_index_returns_html() -> None:
    with TestClient(main.app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]


def test_config_returns_log_ws_url() -> None:
    with TestClient(main.app) as client:
        resp = client.get("/config")
        assert resp.status_code == 200
        body = resp.json()
        assert "log_ws_url" in body
        assert "ws://" in body["log_ws_url"]
        assert "/logs" in body["log_ws_url"]


def test_ws_fanout_between_two_clients() -> None:
    _reset_state()
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            tick_msg = {"type": "tick", "pos": [1, 2, 3]}
            a.send_json(tick_msg)
            received = b.receive_json()
            assert received == tick_msg


def test_snapshot_replay_to_new_viewer() -> None:
    _reset_state()
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws") as a:
            init_msg = {"type": "init", "terrain": "dem"}
            tick_msg = {"type": "tick", "pos": [1, 2, 3]}
            a.send_json(init_msg)
            a.send_json(tick_msg)

            with client.websocket_connect("/ws") as c:
                first = c.receive_json()
                second = c.receive_json()
                assert first == init_msg
                assert second == tick_msg


def test_signal_cached_per_channel_latest_wins() -> None:
    _reset_state()
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws") as a:
            sig1 = {"type": "signal", "channel": "gps", "quality": 0.5}
            sig2 = {"type": "signal", "channel": "gps", "quality": 0.9}
            a.send_json(sig1)
            a.receive_json()  # 본인에게도 broadcast 됨(단순 팬아웃)
            a.send_json(sig2)
            a.receive_json()

            with client.websocket_connect("/ws") as c:
                replayed = c.receive_json()
                assert replayed == sig2


def test_unknown_type_not_broadcast() -> None:
    _reset_state()
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            # 알 수 없는 타입은 dispatch에서 드롭되고 broadcast도 되지 않는다.
            a.send_json({"type": "unknown_bogus_type", "x": 1})
            # 알려진 타입을 하나 더 보내 b가 이를 먼저(유일하게) 받는지로 확인한다.
            known_msg = {"type": "tick", "pos": [9, 9, 9]}
            a.send_json(known_msg)
            received = b.receive_json()
            assert received == known_msg


def test_disconnect_then_broadcast_does_not_crash() -> None:
    _reset_state()
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws") as a:
            with client.websocket_connect("/ws") as b:
                pass  # b closes immediately
            # a는 여전히 연결되어 있고, b는 제거되었어야 한다 — 이후 broadcast가
            # 죽은 소켓 때문에 죽지 않아야 함.
            a.send_json({"type": "tick", "pos": [0, 0, 0]})
            received = a.receive_json()
            assert received == {"type": "tick", "pos": [0, 0, 0]}
