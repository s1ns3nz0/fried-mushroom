"""infra/sim route.py — METT+TC corridor 경로 + 적 탐지반경 회피 (2-pass). TDD.

온보드 파이프라인 무관·무수정. 순수 geometry (표준 라이브러리). 루트 CI 수집.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "sim"))

from route import generate_route, haversine_m  # noqa: E402


_CORRIDOR = {
    "waypoints": [
        {"lat": 37.50, "lon": 127.00, "alt_m": 120},
        {"lat": 37.52, "lon": 127.02, "alt_m": 120},
    ],
    "bases": {"emergency": {"lat": 37.49, "lon": 127.0, "alt_m": 50}},
}


def _brief(**over):
    b = {"sortie_id": "SIM", "mission_context": "정찰",
         "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
         "drone_profile": {"battery_pct": 80},
         "corridor": _CORRIDOR, "weights": {"stealth": 0.4, "survival": 0.35}}
    b.update(over)
    return b


def _min_clearance(route, enemy):
    return min(haversine_m(wp, enemy["pos"]) for wp in route)


def test_no_enemies_follows_corridor():
    route = generate_route(_brief(), enemies=None)
    assert route[0]["lat"] == 37.50 and route[-1]["lat"] == 37.52
    assert all("lat" in wp and "lon" in wp for wp in route)


def test_route_avoids_enemy_detect_radius():
    # 직선 경로 중앙에 적 배치 → 경로 전 구간이 detect_radius 밖으로 우회.
    enemy = {"id": "E1", "pos": {"lat": 37.51, "lon": 127.01}, "detect_radius_m": 400}
    route = generate_route(_brief(), enemies=[enemy])
    assert _min_clearance(route, enemy) >= enemy["detect_radius_m"]
    # 시작/끝은 유지.
    assert route[0]["lat"] == 37.50 and route[-1]["lat"] == 37.52


def test_route_is_deterministic():
    enemy = {"id": "E1", "pos": {"lat": 37.51, "lon": 127.01}, "detect_radius_m": 400}
    assert generate_route(_brief(), enemies=[enemy]) == generate_route(_brief(), enemies=[enemy])


def test_far_enemy_does_not_perturb():
    enemy = {"id": "E1", "pos": {"lat": 40.0, "lon": 130.0}, "detect_radius_m": 400}
    assert generate_route(_brief(), enemies=[enemy]) == generate_route(_brief(), enemies=None)
