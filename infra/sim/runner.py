"""infra/sim 폐루프 러너 — build_scenario + flight_plan 되먹임 + tick payload.

METT+TC(mission_brief) → 적 사전배치 → 회피경로 → World.tick(command) → envelope →
run_cycle(실 판정) → flight_plan 을 다음 tick command 로 **되먹임**(폐루프). seed 이벤트
(팝업 위협)가 발화하면 run_cycle 이 회피(REROUTE 등)를 산출하고 world 궤적이 꺾인다.

seed 기반 결정론(난수 없음) — 같은 seed = 동일 적·이벤트·궤적·판정(재현성). tick당
주사위 금지: 이벤트는 seq 에 사전 배치한다. **src/onboard 무수정** — run_cycle import.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parents[1] / "src"
for _p in (str(_HERE), str(_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from onboard.run import (  # noqa: E402
    extract_flight_plan_state,
    extract_qualities,
    run_cycle,
)

from envelope import world_to_envelope  # noqa: E402
from route import generate_route  # noqa: E402
from world import World  # noqa: E402

_MAINTAIN = {
    "flight_action": "MAINTAIN", "target_bearing_deg": None,
    "altitude_delta_m": 0, "replan_scope": "NONE", "speed_mode": "CRUISE",
}
# 팝업 위협(근접 소화기 T3): 궤적 회피를 유발하는 결정론 이벤트 오브젝트.
_POPUP_THREAT = {
    "class": "person", "weapon_shape": True, "closing": True,
    "closure_rate_mps": 3.2, "bearing_deg": 90.0, "degraded_reason": None,
}
_ENEMY_DETECT_RADIUS_M = 400.0
_EVENT_WINDOW = 3  # 팝업 위협 지속 tick 수(회피 안정화용).


def place_enemies(mission_brief: dict, seed: int) -> list[dict]:
    """seed 결정론: 경로 진행도 s(≈0.4~0.6)에 적 1기 사전 배치."""
    wps = mission_brief.get("corridor", {}).get("waypoints", [])
    if len(wps) < 2:
        return []
    a, b = wps[0], wps[-1]
    frac = 0.4 + (seed % 5) * 0.05  # 결정론
    return [{
        "id": "E1",
        "pos": {"lat": a["lat"] + frac * (b["lat"] - a["lat"]),
                "lon": a["lon"] + frac * (b["lon"] - a["lon"])},
        "detect_radius_m": _ENEMY_DETECT_RADIUS_M,
    }]


def build_scenario(mission_brief: dict, seed: int) -> dict:
    """seed → 적(사전배치) + 회피경로 + world + 이벤트(팝업 위협 seq 사전배치)."""
    enemies = place_enemies(mission_brief, seed)
    route = generate_route(mission_brief, enemies=enemies)
    world = World(route=route, enemies=enemies)
    start_seq = 4 + (seed % 4)  # 결정론적 조우 시점
    events = [{"from_seq": start_seq, "to_seq": start_seq + _EVENT_WINDOW,
               "threat_object": dict(_POPUP_THREAT)}]
    return {"enemies": enemies, "route": route, "world": world, "events": events}


def _active_threat_object(events: list[dict], seq: int) -> dict | None:
    for ev in events:
        if ev["from_seq"] <= seq <= ev["to_seq"]:
            return ev["threat_object"]
    return None


def run_closed_loop(mission_brief: dict, seed: int, ticks: int, dt: float = 1.0) -> list[dict]:
    """폐루프 실행 → tick당 {world, result} 프레임 리스트.

    직전 사이클 flight_plan 을 다음 tick 의 world command 로 되먹이고,
    previous_qualities/flight_plan_state 를 사이클 간 스레딩한다(#136).
    """
    scen = build_scenario(mission_brief, seed)
    world = scen["world"]
    events = scen["events"]
    command = dict(_MAINTAIN)
    prev_q = None
    prev_fp = None
    frames: list[dict] = []
    for seq in range(ticks):
        state = world.tick(dt, command)  # 직전 flight_plan 반영(폐루프)
        threat_object = _active_threat_object(events, seq)
        env = world_to_envelope(
            mission_brief.get("sortie_id", "SIM"), seq, seq * 1000, state,
            threat_object=threat_object,
        )
        result = run_cycle(
            env, mission_brief,
            previous_qualities=prev_q, previous_flight_plan_state=prev_fp,
        )
        command = result["flight_plan"]  # 되먹임
        prev_q = extract_qualities(result)
        prev_fp = extract_flight_plan_state(result)
        frames.append({"world": state, "result": result})
    return frames


def build_tick_payload(seq: int, ts_ms: int, correlation_id: str,
                       world_state: dict, result: dict, enemies: list[dict]) -> dict:
    """폐루프 프레임 → 대시보드 `/tick` payload (#151 제안 스키마).

    world(지도/텔레메트리) + 실 파이프라인 출력(신호/결정 패널). 모킹 아님.
    인터페이스 합의(@hobeen-kim) 시 필드 조정.
    """
    return {
        "type": "tick",
        "seq": seq,
        "ts_ms": ts_ms,
        "correlation_id": correlation_id,
        "world": {
            "pos": dict(world_state["pos"]),
            "heading_deg": world_state["heading_deg"],
            "speed_mps": world_state["speed_mps"],
            "phase": world_state["phase"],
            "enemies": [dict(e) for e in enemies],
        },
        "abstraction": result["abstraction"],
        "threat": result["threat"],
        "risk": result["risk"],
        "response": result["response"],
        "flight_plan": result["flight_plan"],
    }
