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
# 07 flight_plan.speed_mode enum(CAUTIOUS/NORMAL/MAX, shared/constants.SPEED_MODE_ORDER)
# → 대지속도(m/s). 07 지시 속도가 폐루프에 실제 반영되도록 키를 07 enum 으로 맞춘다.
_SPEED_MODE_MPS = {"CAUTIOUS": 10.0, "NORMAL": 17.0, "MAX": 24.0}
_DEFAULT_SPEED_MODE = "NORMAL"


def _bearing_deg(a: dict, b: dict) -> float:
    """a→b 방위(도, 북=0 시계방향). cos(lat) 보정."""
    lat0 = math.radians(a["lat"])
    north = (b["lat"] - a["lat"]) * 111_320.0
    east = (b["lon"] - a["lon"]) * 111_320.0 * math.cos(lat0)
    return math.degrees(math.atan2(east, north)) % 360.0


def _advance(pos: dict, heading_deg: float, dist_m: float) -> dict:
    """pos 에서 heading 방향으로 dist_m 이동한 새 좌표.

    lat/lon 은 7자리(≈1cm)로 반올림한다 — cos/sin 의 마지막 ULP 가 libm(파이썬/플랫폼)
    마다 달라 envelope→run_cycle 판정이 버전 간 갈리는 것을 막는다(포터블 결정론).
    """
    rad = math.radians(heading_deg)
    dnorth, deast = dist_m * math.cos(rad), dist_m * math.sin(rad)
    dlat = dnorth / 111_320.0
    dlon = deast / (111_320.0 * math.cos(math.radians(pos["lat"])))
    return {
        "lat": round(pos["lat"] + dlat, 7),
        "lon": round(pos["lon"] + dlon, 7),
        "alt_m": round(pos["alt_m"], 3),
    }


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
        """dt(초) 동안 command 를 반영해 세계를 전진시킨다. 갱신된 state 반환.

        phase 는 **매 tick 현재 command 기준으로 재계산**한다(래치 금지) — EVADE 후
        MAINTAIN 이 오면 즉시 TRANSIT/ENCOUNTER 로 복귀한다.
        """
        action = command.get("flight_action", "MAINTAIN")
        self._speed = _SPEED_MODE_MPS.get(
            command.get("speed_mode") or _DEFAULT_SPEED_MODE, self._speed)

        # 고도: altitude_delta_m 를 승강률 상한 내에서 점진 적용.
        alt_delta = command.get("altitude_delta_m", 0) or 0
        if alt_delta:
            step = max(-_ALT_RATE_M_PER_S * dt, min(_ALT_RATE_M_PER_S * dt, float(alt_delta)))
            self._pos["alt_m"] = round(self._pos["alt_m"] + step, 3)

        # 헤딩·회피의도 결정: 회피(replan≠NONE + target_bearing) → 그 방위, RTL → 기지,
        # 아니면 route 추종. action 명 무관하게 target_bearing 이 있으면 그 회피방위로 꺾는다.
        target = self._target()
        evade_intent: str | None = None  # 이 tick 의 command 가 지시하는 특수 phase.
        if command.get("target_bearing_deg") is not None and command.get("replan_scope", "NONE") != "NONE":
            self._heading = float(command["target_bearing_deg"]) % 360.0
            evade_intent = "EVADE"
        elif action == "RTL":
            self._heading = _bearing_deg(self._pos, self._route[0])
            evade_intent = "RTL"
        elif target is not None:
            self._heading = _bearing_deg(self._pos, target)
        self._heading = round(self._heading % 360.0, 6)  # 포터블 반올림(atan2 ULP 차단).

        # 도착 판정(경로 끝).
        if target is None:
            self._phase = "ARRIVED"
            return self.state()

        # 전진.
        self._pos = _advance(self._pos, self._heading, self._speed * dt)
        if _dist_m(self._pos, target) < _ARRIVE_RADIUS_M:
            self._seg += 1

        # phase 재계산(래치 없음): 경로 끝→ARRIVED, command 회피의도→EVADE/RTL,
        # 아니면 적 근접 여부로 ENCOUNTER/TRANSIT.
        if self._seg >= len(self._route):
            self._phase = "ARRIVED"
        elif evade_intent is not None:
            self._phase = evade_intent
        else:
            if any(_dist_m(self._pos, e["pos"]) < e["detect_radius_m"] for e in self._enemies):
                self._phase = "ENCOUNTER"
            else:
                self._phase = "TRANSIT"
        return self.state()
