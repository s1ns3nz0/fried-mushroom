"""infra/sim world.py — 폐루프 결정론 조향 tick(dt, command). TDD.

command = run_cycle flight_plan(dict). world 가 flight_action/target_bearing_deg/
altitude_delta_m/speed_mode 를 받아 실제 위치·헤딩·고도·페이즈를 갱신한다.
순수 결정론(난수 없음) — 같은 초기상태+command 시퀀스 = 동일 궤적.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "sim"))

from route import haversine_m  # noqa: E402
from world import World  # noqa: E402

_ROUTE = [
    {"lat": 37.50, "lon": 127.00, "alt_m": 120},
    {"lat": 37.52, "lon": 127.02, "alt_m": 120},
]
_MAINTAIN = {"flight_action": "MAINTAIN", "target_bearing_deg": None,
             "altitude_delta_m": 0, "replan_scope": "NONE", "speed_mode": "CRUISE"}


def _world(enemies=None):
    return World(route=_ROUTE, enemies=enemies or [], speed_mps=17.0)


def test_maintain_advances_along_route():
    w = _world()
    start = dict(w.state()["pos"])
    w.tick(1.0, _MAINTAIN)
    moved = haversine_m(start, w.state()["pos"])
    assert 15.0 <= moved <= 19.0  # ~17 m/s * 1s


def test_arrival_sets_phase_and_stops():
    w = _world()
    for _ in range(400):  # 충분히 오래 → 도착
        w.tick(1.0, _MAINTAIN)
    assert w.state()["phase"] == "ARRIVED"


def test_altitude_delta_applied():
    w = _world()
    a0 = w.state()["pos"]["alt_m"]
    w.tick(1.0, {**_MAINTAIN, "altitude_delta_m": 30})
    assert w.state()["pos"]["alt_m"] > a0  # 상승 반영(점진 or 즉시)


def test_reroute_bearing_bends_trajectory():
    # REROUTE + target_bearing 이면 경로 대신 그 방위로 조향 → 헤딩이 그쪽으로.
    w = _world()
    cmd = {**_MAINTAIN, "flight_action": "REROUTE", "target_bearing_deg": 270.0,
           "replan_scope": "LOCAL"}
    w.tick(1.0, cmd)
    hd = w.state()["heading_deg"]
    assert 200.0 <= hd <= 340.0  # 서편(270°) 쪽으로 꺾임


def test_enemy_proximity_sets_encounter_phase():
    enemy = {"id": "E1", "pos": {"lat": 37.50, "lon": 127.00}, "detect_radius_m": 300}
    w = _world(enemies=[enemy])  # 시작점이 적 반경 안
    w.tick(1.0, _MAINTAIN)
    assert w.state()["phase"] in ("ENCOUNTER", "EVADE")


def test_deterministic_same_commands_same_trajectory():
    def run():
        w = _world()
        traj = []
        for _ in range(10):
            w.tick(1.0, _MAINTAIN)
            traj.append((round(w.state()["pos"]["lat"], 8), round(w.state()["pos"]["lon"], 8)))
        return traj
    assert run() == run()


def test_evade_phase_not_latched_returns_after_maintain():
    # REROUTE→EVADE 후 MAINTAIN tick 이 오면 phase 가 EVADE 로 고착되지 않는다(래치 없음).
    w = _world()
    w.tick(1.0, {**_MAINTAIN, "flight_action": "REROUTE", "target_bearing_deg": 270.0, "replan_scope": "LOCAL"})
    assert w.state()["phase"] == "EVADE"
    w.tick(1.0, _MAINTAIN)  # 회피 해제
    assert w.state()["phase"] != "EVADE"


def test_speed_mode_uses_07_enum():
    # 07 enum(CAUTIOUS/NORMAL/MAX)이 실제 속도로 반영된다(구 SLOW/CRUISE/DASH fallback 아님).
    w = _world()
    w.tick(1.0, {**_MAINTAIN, "speed_mode": "MAX"})
    assert w.state()["speed_mps"] == 24.0
    w.tick(1.0, {**_MAINTAIN, "speed_mode": "CAUTIOUS"})
    assert w.state()["speed_mps"] == 10.0
