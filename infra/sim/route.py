"""infra/sim 경로 생성기 — METT+TC corridor + 적 탐지반경 회피 (2-pass).

폐루프 시뮬(#151)의 사전 경로. 적(위치·탐지반경)을 **경로 생성 전에 확정**(2-pass)해
직선 corridor 가 적 detect_radius 를 침범하면 우회 웨이포인트를 삽입한다.

온보드 파이프라인(src/onboard) 무관·무수정. 순수 geometry(표준 라이브러리만).
`build_normal_envelope`/`RawSensorEnvelope` 등은 envelope.py 소관 — 여기선 lat/lon 만.
"""

from __future__ import annotations

import math

_EARTH_R_M = 6_371_000.0
# 우회 시 detect_radius 위에 더 두는 안전 여유(m).
AVOID_MARGIN_M = 60.0


def haversine_m(a: dict, b: dict) -> float:
    """두 {lat, lon} 사이 대권거리(m)."""
    lat1, lon1 = math.radians(a["lat"]), math.radians(a["lon"])
    lat2, lon2 = math.radians(b["lat"]), math.radians(b["lon"])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * _EARTH_R_M * math.asin(min(1.0, math.sqrt(h)))


def _meters_to_deg(lat_deg: float, dnorth_m: float, deast_m: float) -> tuple[float, float]:
    """국소 평면 근사: 북/동 방향 오프셋(m) → (dlat, dlon) 도. cos(lat) 경도 보정."""
    dlat = dnorth_m / 111_320.0
    dlon = deast_m / (111_320.0 * math.cos(math.radians(lat_deg)))
    return dlat, dlon


def _segment_clearance(p1: dict, p2: dict, enemy: dict) -> float:
    """선분 p1→p2 와 적 위치의 최소거리(m). 국소 평면 근사(짧은 구간 가정)."""
    e = enemy["pos"]
    lat0 = p1["lat"]
    # p1 기준 국소 미터 좌표.
    def to_m(p):
        north = (p["lat"] - lat0) * 111_320.0
        east = (p["lon"] - p1["lon"]) * 111_320.0 * math.cos(math.radians(lat0))
        return north, east
    ax, ay = to_m(p1)
    bx, by = to_m(p2)
    ex, ey = to_m(e)
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return math.hypot(ex - ax, ey - ay)
    t = max(0.0, min(1.0, ((ex - ax) * dx + (ey - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(ex - cx, ey - cy)


def _avoid_waypoint(p1: dict, p2: dict, enemy: dict) -> dict:
    """적을 감싸 도는 우회점 — 적에서 경로 수직방향으로 offset 이동.

    단일 offset(radius+margin)은 두 leg(p1→우회점, 우회점→p2)가 여전히 원을 관통할 수
    있으므로(긴 구간·중점 적), **두 leg 의 clearance 가 모두 radius 이상이 될 때까지
    offset 을 결정론적으로 키운다**(수렴). radius 가 구간 절반보다 크면(끝점이 원 안)
    기하학상 불가 — 그 경우 도달 가능한 최대 offset(best-effort)을 쓴다.
    """
    e = enemy["pos"]
    lat0 = e["lat"]
    north = (p2["lat"] - p1["lat"]) * 111_320.0
    east = (p2["lon"] - p1["lon"]) * 111_320.0 * math.cos(math.radians(lat0))
    norm = math.hypot(north, east) or 1.0
    # 수직 단위벡터 (좌현: (-east, north)). 결정론 위해 항상 좌현 우회.
    perp_n, perp_e = -east / norm, north / norm
    radius = enemy["detect_radius_m"]

    def _wp(offset: float) -> dict:
        dlat, dlon = _meters_to_deg(lat0, perp_n * offset, perp_e * offset)
        return {"lat": round(e["lat"] + dlat, 7), "lon": round(e["lon"] + dlon, 7),
                "alt_m": p1.get("alt_m", 120)}

    offset = radius + AVOID_MARGIN_M
    wp = _wp(offset)
    # 두 leg 가 모두 clear 될 때까지 offset 을 1.5배씩 키움(결정론 수렴, 상한).
    for _ in range(40):
        if (_segment_clearance(p1, wp, enemy) >= radius
                and _segment_clearance(wp, p2, enemy) >= radius):
            break
        offset *= 1.5
        wp = _wp(offset)
    return wp


def generate_route(mission_brief: dict, enemies: list[dict] | None = None) -> list[dict]:
    """corridor waypoints 기반 경로 + 적 탐지반경 회피 (2-pass).

    적이 없거나 경로에서 충분히 멀면 corridor 원본을 그대로 반환한다. 적 detect_radius
    를 침범하는 구간에는 좌현 우회점을 1개 삽입한다(결정론).
    """
    waypoints = [dict(wp) for wp in mission_brief.get("corridor", {}).get("waypoints", [])]
    if len(waypoints) < 2 or not enemies:
        return waypoints

    route = [waypoints[0]]
    for i in range(1, len(waypoints)):
        p1, p2 = route[-1], waypoints[i]

        def _feasible(e: dict) -> bool:
            # 끝점이 이미 탐지원 안이면 기하학상 회피 불가 → 우회하지 않는다(무한 offset 방지).
            r = e["detect_radius_m"]
            return haversine_m(p1, e["pos"]) >= r and haversine_m(p2, e["pos"]) >= r

        # 이 구간을 침범하고 회피 가능한 적(가장 가까운 것부터) 우회.
        threatening = [
            e for e in enemies
            if _segment_clearance(p1, p2, e) < e["detect_radius_m"] and _feasible(e)
        ]
        for enemy in sorted(threatening, key=lambda e: _segment_clearance(p1, p2, e)):
            route.append(_avoid_waypoint(p1, p2, enemy))
        route.append(p2)
    return route
