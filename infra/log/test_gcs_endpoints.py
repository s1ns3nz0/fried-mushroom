"""로그수집기 GCS 엔드포인트(/gcs/*) 계약 테스트.

infra/dashboard/main.py 에서 이전된 파이프라인 실행 엔드포인트를 검증한다:
- GET  /gcs/scenarios      → examples/ 의 raw_*/mission_brief_* 쌍 목록
- GET  /gcs/scenario/{tag} → {raw, mission_brief} (태그 sanitize, 404)
- POST /gcs/run            → run_cycle 실행 + 결과 로그를 인프로세스 hub 에 직접 publish
"""

from __future__ import annotations

import log_server
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_hub() -> None:
    """각 테스트 전 module-global hub를 새 LogHub로 교체해 backlog 오염을 막는다."""
    log_server.hub = log_server.LogHub()


def test_gcs_scenarios_lists_tag_pairs() -> None:
    with TestClient(log_server.app) as client:
        resp = client.get("/gcs/scenarios")
        assert resp.status_code == 200
        items = resp.json()
        tags = [it["tag"] for it in items]
        # raw_*/mission_brief_* 쌍이 모두 있는 태그만 나열된다.
        assert "t3" in tags
        # mission_brief_strike.json 은 raw 짝이 없으므로 제외.
        assert "strike" not in tags
        for it in items:
            assert set(it) == {"tag", "sortie_id", "mission_context"}


def test_gcs_scenario_t3_returns_raw_and_brief() -> None:
    with TestClient(log_server.app) as client:
        resp = client.get("/gcs/scenario/t3")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body["raw"], dict)
        assert isinstance(body["mission_brief"], dict)
        assert body["mission_brief"].get("sortie_id")


def test_gcs_scenario_missing_tag_404() -> None:
    with TestClient(log_server.app) as client:
        assert client.get("/gcs/scenario/nope999").status_code == 404


def test_gcs_scenario_bad_tag_sanitized_404() -> None:
    with TestClient(log_server.app) as client:
        assert client.get("/gcs/scenario/..%2F..%2Fetc").status_code == 404


def test_gcs_run_publishes_entries_to_hub() -> None:
    with TestClient(log_server.app) as client:
        scenario = client.get("/gcs/scenario/t3").json()
        before = client.get("/health").json()["backlog"]

        resp = client.post("/gcs/run", json=scenario)
        assert resp.status_code == 200
        body = resp.json()
        assert body["log_published"] is True
        assert "result" in body
        assert body["correlation_id"].startswith(
            str(scenario["mission_brief"].get("sortie_id", "SORTIE"))
        )

        # 엔트리가 인프로세스 hub backlog 에 직접 쌓였는지(HTTP self-post 없음) 확인.
        after = client.get("/health").json()["backlog"]
        assert after > before
        backlog = log_server.hub.backlog()
        assert all(e["correlation_id"] == body["correlation_id"] for e in backlog)
        assert all(isinstance(e["ts"], int) for e in backlog)


def test_gcs_run_bad_body_400() -> None:
    with TestClient(log_server.app) as client:
        resp = client.post("/gcs/run", json={"raw": "not-a-dict"})
        assert resp.status_code == 400
