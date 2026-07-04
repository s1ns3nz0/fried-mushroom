"""07. Flight Planning — terrain-aware 경로 생성 (실 DEM #341).

지형 표고(DEM)는 결정론 heightmap(terrain.py, vizsim/app.js PEAKS 포트). flat DEM=0
stub 를 대체해 **clearance_m = alt_m - terrain_elev_m**(코리더 bbox 정규화 프레임 기준)
으로 실 지형 여유고도를 산출한다. 봉우리 교차·저고도 구간은 clearance 가 급감/음수가
되어 지형충돌(CFIT) 위험이 실제 값으로 드러난다.

generate_route(flight_action, altitude_delta_m, replan_scope, cycle_context)
  → list[dict]  # [{lat, lon, alt_m, clearance_m, terrain_elev_m}, ...]

replan_scope 별 동작:
  NONE  → []  (MAINTAIN — 재계획 없음)
  LOCAL → corridor waypoints + delta 적용 (RTL은 역순 + base 추가)
  FULL  → corridor waypoints + delta 적용 (full 경로 재생성)

물리적 상승/하강률:
  연속 waypoint 간 고도차가 ROUTE_MAX_CLIMB_RATE_M_PER_WP 를 초과하면
  두 점 사이에 중간 waypoint 를 보간해 제약을 강제한다.
"""

from __future__ import annotations

import math

from ..shared.constants import (
    EARTH_RADIUS_M,
    ROUTE_EVASION_OFFSET_M,
    ROUTE_MAX_CLIMB_RATE_M_PER_WP,
    ROUTE_MIN_CLEARANCE_M,
)
from .terrain import compute_bbox, terrain_elev_m


def _waypoint(lat: float, lon: float, alt_m: float, bbox: dict) -> dict:
    """route waypoint dict — 실 지형표고 기준 clearance 부여.

    clearance_m = alt_m - terrain_elev_m. 봉우리 교차/저고도 시 음수 가능(CFIT 신호이므로
    clamp 하지 않는다). 6자리 반올림(이식성).
    """
    elev = terrain_elev_m(lat, lon, bbox)
    return {
        "lat": lat, "lon": lon, "alt_m": alt_m,
        "terrain_elev_m": elev,
        "clearance_m": round(alt_m - elev, 6),
    }


def generate_route(
    flight_action: str,
    altitude_delta_m: int,
    replan_scope: str,
    cycle_context: dict,
    target_bearing_deg: float | None = None,
) -> list[dict]:
    """terrain-aware + 회피 수평궤적이 반영된 경로 생성.

    cycle_context 키:
      corridor_waypoints: list[dict] — 코리더 waypoints ({lat, lon, alt_m, ...})
      corridor_bases: dict — 복귀 기지 ({emergency: {lat, lon, alt_m}, ...})

    target_bearing_deg: FULL scope(REROUTE/ALTITUDE_CHANGE_REROUTE)에서만 사용.
      None이면 offset 미적용. RTL/LOCAL scope는 무조건 미적용.
    """
    waypoints: list[dict] = cycle_context.get("corridor_waypoints") or []
    if not waypoints or replan_scope == "NONE":
        return []

    # 지형 프레임 bbox 는 **원 코리더** 기준(offset/RTL 무관하게 안정) — vizsim/대시보드와 일치.
    bbox = compute_bbox(waypoints)

    if flight_action == "RTL":
        return _rtl_route(waypoints, cycle_context.get("corridor_bases") or {}, bbox)

    if replan_scope == "FULL" and target_bearing_deg is not None:
        waypoints = _apply_bearing_offset(waypoints, target_bearing_deg)

    return _apply_delta(waypoints, altitude_delta_m, bbox)


def _apply_delta(waypoints: list[dict], delta_m: int, bbox: dict) -> list[dict]:
    """고도 delta 적용 + 연속 고도차 상한(ROUTE_MAX_CLIMB_RATE_M_PER_WP) 강제.

    초과 시 두 corridor waypoint 사이에 위경도를 선형 보간한 중간 waypoint 삽입.
    모든 waypoint 는 ROUTE_MIN_CLEARANCE_M 이상으로 clamp.
    """
    if not waypoints:
        return []

    # 목표 고도 산출 (min clearance clamp 포함)
    targets: list[tuple[float, float, float]] = [
        (
            float(wp["lat"]),
            float(wp["lon"]),
            max(ROUTE_MIN_CLEARANCE_M, float(wp.get("alt_m", ROUTE_MIN_CLEARANCE_M)) + delta_m),
        )
        for wp in waypoints
    ]

    route = [_waypoint(targets[0][0], targets[0][1], targets[0][2], bbox)]

    for i in range(1, len(targets)):
        lat1, lon1, alt1 = targets[i - 1]
        lat2, lon2, alt2 = targets[i]
        diff = alt2 - alt1

        if abs(diff) > ROUTE_MAX_CLIMB_RATE_M_PER_WP:
            # 중간 waypoint 보간 — 물리적 상승/하강률 강제 (지형표고도 그 지점 기준 샘플)
            n_steps = math.ceil(abs(diff) / ROUTE_MAX_CLIMB_RATE_M_PER_WP)
            for step in range(1, n_steps):
                t = step / n_steps
                route.append(_waypoint(
                    lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1),
                    alt1 + t * diff, bbox,
                ))

        route.append(_waypoint(lat2, lon2, alt2, bbox))

    return route


def _apply_bearing_offset(waypoints: list[dict], bearing_deg: float) -> list[dict]:
    """모든 waypoint를 bearing_deg 방향으로 ROUTE_EVASION_OFFSET_M 이동.

    cos(lat) 경도 보정 적용 (run.py._compute_terrain_bearings 역연산 패턴).
    alt_m/clearance_m은 보존 — 고도 처리는 이후 _apply_delta() 가 담당.
    """
    bearing_rad = math.radians(bearing_deg)
    d = ROUTE_EVASION_OFFSET_M
    result = []
    for wp in waypoints:
        lat = float(wp["lat"])
        lon = float(wp["lon"])
        d_lat = math.degrees(d * math.cos(bearing_rad) / EARTH_RADIUS_M)
        d_lon = math.degrees(d * math.sin(bearing_rad) / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
        result.append({**wp, "lat": lat + d_lat, "lon": lon + d_lon})
    return result


def _rtl_route(waypoints: list[dict], bases: dict, bbox: dict) -> list[dict]:
    """RTL: corridor 역순 + emergency base 를 최종 목적지로 추가.

    base 고도가 corridor 고도보다 낮을 때 급강하를 방지하기 위해
    base 를 corridor 목록에 포함시켜 _apply_delta 의 보간 적용. clearance 는 원 코리더
    bbox 프레임 기준(base 가 프레임 밖이면 그 지점 정규화값으로 표고 샘플).
    """
    reversed_wps = list(reversed(waypoints))
    base = bases.get("emergency")
    if base:
        reversed_wps = reversed_wps + [base]
    return _apply_delta(reversed_wps, 0, bbox)
