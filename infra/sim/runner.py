"""infra/sim 폐루프 러너 — build_scenario + flight_plan 되먹임 + tick payload.

METT+TC(mission_brief) → 적 사전배치 → 회피경로 → World.tick(command) → envelope →
run_cycle(실 판정) → flight_plan 을 다음 tick command 로 **되먹임**(폐루프). seed 이벤트
(팝업 위협)가 발화하면 run_cycle 이 회피(REROUTE 등)를 산출하고 world 궤적이 꺾인다.

seed 기반 결정론(난수 없음) — 같은 seed = 동일 적·이벤트·궤적·판정(재현성). tick당
주사위 금지: 이벤트는 seq 에 사전 배치한다. **src/onboard 무수정** — run_cycle import.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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


def _track_pos(track: dict) -> tuple[float, float] | None:
    """E.tracks 위치 추출 — 두 정본 형상을 모두 수용:
    - 관측소 폼: top-level `lat`/`lon`
    - C4I/assemble_mettc: `pos: [lat, lon]` (또는 `pos: {lat, lon}`)
    해석 불가하면 None."""
    if track.get("lat") is not None and track.get("lon") is not None:
        return track["lat"], track["lon"]
    pos = track.get("pos")
    if isinstance(pos, (list, tuple)) and len(pos) >= 2 and pos[0] is not None and pos[1] is not None:
        return pos[0], pos[1]
    if isinstance(pos, dict) and pos.get("lat") is not None and pos.get("lon") is not None:
        return pos["lat"], pos["lon"]
    return None


def _track_to_enemy(track: dict, latlon: tuple[float, float]) -> dict:
    """E.tracks 항목 → sim 적 계약. id 는 `id` 또는 C4I `track_id`. 반경은 폼 `radius_m`
    또는 C4I/B-1 정본 `radius`(둘 다 없으면 기본)."""
    lat, lon = latlon
    return {
        "id": track.get("id") or track.get("track_id") or "E?",
        "pos": {"lat": lat, "lon": lon},
        "detect_radius_m": float(track.get("radius_m") or track.get("radius") or _ENEMY_DETECT_RADIUS_M),
        "kind": track.get("kind"),            # 표시/위협유형(선택)
        "confidence": track.get("confidence"),
    }


def place_enemies(mission_brief: dict, seed: int) -> list[dict]:
    """적 배치 — 관측소 폼/C4I `enemy_tracks`(E.tracks, #151 F3)가 있으면 그 위치를 쓰고,
    없으면 seed 결정론 폴백(경로 진행도 s≈0.4~0.6 에 적 1기).

    E.tracks 두 형상 수용: 폼 `{id,kind,lat,lon,radius_m,confidence}` /
    C4I `{track_id,kind,pos:[lat,lon],confidence,...}`. **실제 변환된 적이 하나도 없으면
    (형상 불일치 등) 조용히 0기로 두지 않고 seed 폴백**(codex #195 P2).
    """
    tracks = mission_brief.get("enemy_tracks")
    if isinstance(tracks, list) and tracks:
        enemies = [_track_to_enemy(t, ll) for t in tracks if isinstance(t, dict)
                   for ll in (_track_pos(t),) if ll is not None]
        if enemies:  # 유효 변환이 있을 때만 채택 — 전부 무효면 아래 seed 폴백.
            return enemies

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
        ts_ms = int(seq * dt * 1000)  # dt 반영 — top-level tick payload ts 와 일치.
        env = world_to_envelope(
            mission_brief.get("sortie_id", "SIM"), seq, ts_ms, state,
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


DEFAULT_COLLECTOR_TICK_URL = "http://localhost:8500/tick"


def _post_tick(collector_url: str, payload: dict) -> bool:
    """tick payload 를 수집기에 POST. httpx 는 지연 import(코어 테스트는 stdlib 만)."""
    import httpx  # noqa: E402  — CLI --collector 사용 시에만 필요

    try:
        resp = httpx.post(collector_url, json=payload, timeout=3.0)
        return 200 <= resp.status_code < 300
    except Exception as exc:  # 연결 실패는 보고 후 계속
        print(f"[runner] POST {collector_url} 실패: {exc}", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    """폐루프 CLI — seed 시나리오를 tick 단위로 실행해 tick payload 를 출력/전송한다."""
    parser = argparse.ArgumentParser(description="infra/sim 폐루프 러너 (#151)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--brief", required=True, help="mission_brief JSON 경로")
    parser.add_argument("--ticks", type=int, default=20)
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument("--rate", type=float, default=0.0, help="tick 간 실시간 지연(초)")
    parser.add_argument("--collector", default=None,
                        help=f"지정 시 tick 을 POST (기본 {DEFAULT_COLLECTOR_TICK_URL})")
    args = parser.parse_args(argv)

    brief_path = Path(args.brief)
    if not brief_path.exists():
        print(f"error: --brief 파일 없음: {args.brief}", file=sys.stderr)
        return 2
    mission_brief = json.loads(brief_path.read_text(encoding="utf-8"))

    scen = build_scenario(mission_brief, args.seed)
    frames = run_closed_loop(mission_brief, args.seed, args.ticks, dt=args.dt)
    sortie = mission_brief.get("sortie_id", "SIM")
    collector_url = (args.collector if args.collector not in (None, "")
                     else None)
    if args.collector == "":
        collector_url = DEFAULT_COLLECTOR_TICK_URL

    posted = 0
    for seq, f in enumerate(frames):
        payload = build_tick_payload(
            seq, int(seq * args.dt * 1000),
            f"{sortie}-{seq:04d}", f["world"], f["result"], scen["enemies"],
        )
        if collector_url:
            posted += 1 if _post_tick(collector_url, payload) else 0
        else:
            print(json.dumps(payload, ensure_ascii=False))
        if args.rate:
            time.sleep(args.rate)
    if collector_url:
        print(f"[runner] {posted}/{len(frames)} ticks posted → {collector_url}",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
