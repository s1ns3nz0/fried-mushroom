"""infra/sim 세계 진화 — 폐루프 결정론 조향 World.tick(dt, command).

command = run_cycle 의 flight_plan(dict). world 가 이를 받아 실제 기체 상태
(pos/heading/alt/speed/phase)를 갱신한다 → 회피 결정이 화면 궤적에 반영(폐루프).

순수 결정론(난수 없음). 온보드 파이프라인 무관 — lat/lon/alt geometry 만 다룬다.
"""

from __future__ import annotations

import math

# 페이즈: 이동/조우/회피/복귀/도착.
_ARRIVE_RADIUS_M = 30.0
_ALT_RATE_M_PER_S = 5.0  # 물리적 승강률 상한.
_SPEED_MODE_MPS = {"SLOW": 8.0, "CRUISE": 17.0, "DASH": 24.0}


def _bearing_deg(a: dict, b: dict) -> float:
    """a→b 방위(도, 북=0 시계방향). cos(lat) 보정."""
    lat0 = math.radians(a["lat"])
    north = (b["lat"] - a["lat"]) * 111_320.0
    east = (b["lon"] - a["lon"]) * 111_320.0 * math.cos(lat0)
    return math.degrees(math.atan2(east, north)) % 360.0


def _advance(pos: dict, heading_deg: float, dist_m: float) -> dict:
    """pos 에서 heading 방향으로 dist_m 이동한 새 좌표."""
    rad = math.radians(heading_deg)
    dnorth, deast = dist_m * math.cos(rad), dist_m * math.sin(rad)
    dlat = dnorth / 111_320.0
    dlon = deast / (111_320.0 * math.cos(math.radians(pos["lat"])))
    return {"lat": pos["lat"] + dlat, "lon": pos["lon"] + dlon, "alt_m": pos["alt_m"]}


def _dist_m(a: dict, b: dict) -> float:
    lat0 = math.radians(a["lat"])
    north = (b["lat"] - a["lat"]) * 111_320.0
    east = (b["lon"] - a["lon"]) * 111_320.0 * math.cos(lat0)
    return math.hypot(north, east)


class World:
    """폐루프 시뮬 세계. route 를 따라가되 command(회피 등)로 조향된다."""

    def __init__(self, route: list[dict], enemies: list[dict] | None = None,
                 speed_mps: float = 17.0) -> None:
        if len(route) < 1:
            raise ValueError("route must have >= 1 waypoint")
        self._route = [dict(wp) for wp in route]
        self._enemies = enemies or []
        self._pos = dict(self._route[0])
        self._pos.setdefault("alt_m", 120.0)
        self._seg = 1  # 다음 목표 route 인덱스.
        self._speed = speed_mps
        self._heading = (_bearing_deg(self._route[0], self._route[1])
                         if len(self._route) > 1 else 0.0)
        self._phase = "TRANSIT"

    def state(self) -> dict:
        return {
            "pos": dict(self._pos),
            "heading_deg": round(self._heading, 3),
            "speed_mps": self._speed,
            "phase": self._phase,
        }

    def _target(self) -> dict | None:
        return self._route[self._seg] if self._seg < len(self._route) else None

    def tick(self, dt: float, command: dict) -> dict:
        """dt(초) 동안 command 를 반영해 세계를 전진시킨다. 갱신된 state 반환."""
        action = command.get("flight_action", "MAINTAIN")
        self._speed = _SPEED_MODE_MPS.get(command.get("speed_mode", "CRUISE"), self._speed)

        # 고도: altitude_delta_m 를 승강률 상한 내에서 점진 적용.
        alt_delta = command.get("altitude_delta_m", 0) or 0
        if alt_delta:
            step = max(-_ALT_RATE_M_PER_S * dt, min(_ALT_RATE_M_PER_S * dt, float(alt_delta)))
            self._pos["alt_m"] += step

        # 헤딩 결정: 회피(REROUTE/RTL, target_bearing) → 지시 방위, 아니면 route 추종.
        target = self._target()
        if action in ("REROUTE", "ALTITUDE_CHANGE_REROUTE") and command.get("target_bearing_deg") is not None:
            self._heading = float(command["target_bearing_deg"]) % 360.0
            self._phase = "EVADE"
        elif action == "RTL":
            base = (self._route[0])  # 복귀 기준(시작점)으로 단순화.
            self._heading = _bearing_deg(self._pos, base)
            self._phase = "RTL"
        elif target is not None:
            self._heading = _bearing_deg(self._pos, target)
        # 도착 판정.
        if target is None:
            self._phase = "ARRIVED"
            return self.state()

        # 전진.
        self._pos = _advance(self._pos, self._heading, self._speed * dt)

        # route waypoint 도달 시 다음 구간으로.
        if _dist_m(self._pos, target) < _ARRIVE_RADIUS_M:
            self._seg += 1
            if self._seg >= len(self._route):
                self._phase = "ARRIVED"

        # 적 조우 페이즈 (EVADE 가 아니면).
        if self._phase not in ("EVADE", "RTL", "ARRIVED"):
            if any(_dist_m(self._pos, e["pos"]) < e["detect_radius_m"] for e in self._enemies):
                self._phase = "ENCOUNTER"
            else:
                self._phase = "TRANSIT"
        return self.state()
