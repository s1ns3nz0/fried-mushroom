"""corridor — 🔵 파생 읽기전용. 코리더 이탈 감시(공간 항법 무결성).

현재 위치가 계획된 비행 코리더(웨이포인트 폴리라인)에서 얼마나 벗어났는지 **cross-track
거리**로 계산해 과도 이탈을 경보한다. 과도 이탈은 GPS 표류/스푸핑, 강풍 표류, 무단 이탈,
또는 회피 기동의 결과일 수 있어 운용자가 알아야 하는 항법 무결성 신호다.

계산: 각 코리더 세그먼트(wp[i]→wp[i+1])에 대한 점-선분 최소거리(국소 평면 근사)를 구해
전체 최소를 이탈량으로 삼는다. 임계는 corridor.half_width(있으면) 또는 인자 max_deviation_m.

CRITICAL (SCC-1): advisory 만. 결정론 판정을 대체하지 않고(07 이 실제 재계획을 결정) 병렬
무결성 지표로 제공한다. 입력을 변이하지 않으며 `EARTH_RADIUS_M`(읽기전용)만 참조한다.
"""

from __future__ import annotations

import math
from typing import Any

from onboard.shared.constants import EARTH_RADIUS_M

# corridor.half_width 도 max_deviation_m 도 없을 때의 기본 이탈 임계(m). advisory 임계라 상수 불변 대상 아님.
_DEFAULT_MAX_DEVIATION_M = 150.0


def _to_local_m(lat: float, lon: float, ref_lat: float, ref_lon: float) -> tuple[float, float]:
    """기준점(ref) 중심 국소 평면(equirectangular) 미터 좌표. 소거리(㎞급)에 충분."""
    x = math.radians(lon - ref_lon) * math.cos(math.radians(ref_lat)) * EARTH_RADIUS_M
    y = math.radians(lat - ref_lat) * EARTH_RADIUS_M
    return x, y


def _point_seg_dist_m(px, py, ax, ay, bx, by) -> float:
    """평면 점(p)-선분(a→b) 최소거리(m)."""
    abx, aby = bx - ax, by - ay
    seg2 = abx * abx + aby * aby
    if seg2 == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * abx + (py - ay) * aby) / seg2
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * abx, ay + t * aby
    return math.hypot(px - cx, py - cy)


def assess_corridor_deviation(
    raw: dict[str, Any],
    mission_brief: dict[str, Any],
    *,
    max_deviation_m: float | None = None,
) -> dict[str, Any]:
    """raw + mission_brief → 코리더 cross-track 이탈 감시. advisory.

    반환: {assessable, deviation_m, within_corridor, threshold_m, nearest_segment_index,
           note, advisory_only}
    """
    raw = raw or {}
    mission_brief = mission_brief or {}
    gps = (raw.get("navigation") or {}).get("gps") or {}
    lat, lon = gps.get("lat"), gps.get("lon")
    corridor = mission_brief.get("corridor") or {}
    wps = [w for w in (corridor.get("waypoints") or [])
           if w.get("lat") is not None and w.get("lon") is not None]

    # 임계 출처를 명시한다 — project_onboard_brief 투영본은 half_width 를 실어 보내지 않아
    # (waypoints/bases 만) 미션 설정 반폭이 유실될 수 있다. default 사용 시 소비자가 알도록
    # threshold_source 를 노출한다(silent fallback 방지). half_width 투영 반영은 별도 이슈.
    if max_deviation_m is not None:
        threshold, threshold_source = max_deviation_m, "explicit"
    elif corridor.get("half_width") is not None:
        threshold, threshold_source = corridor["half_width"], "half_width"
    else:
        threshold, threshold_source = _DEFAULT_MAX_DEVIATION_M, "default"

    if lat is None or lon is None or not wps:
        return {
            "assessable": False, "deviation_m": None, "within_corridor": None,
            "threshold_m": threshold, "threshold_source": threshold_source,
            "nearest_segment_index": None, "advisory_only": True,
            "note": "위치 또는 코리더 웨이포인트 부재 — 이탈 판단 불가.",
        }

    px, py = 0.0, 0.0  # 기준점 = 현재 위치
    pts = [_to_local_m(w["lat"], w["lon"], lat, lon) for w in wps]

    if len(pts) == 1:
        deviation = math.hypot(pts[0][0], pts[0][1])
        seg_idx = 0
    else:
        best, seg_idx = float("inf"), 0
        for i in range(len(pts) - 1):
            ax, ay = pts[i]
            bx, by = pts[i + 1]
            d = _point_seg_dist_m(px, py, ax, ay, bx, by)
            if d < best:
                best, seg_idx = d, i
        deviation = best

    within = deviation <= threshold
    if within:
        note = f"코리더 이탈 {deviation:.0f}m ≤ 임계 {threshold:.0f}m — 정상 경로."
    else:
        note = (f"⚠ 코리더 이탈 {deviation:.0f}m > 임계 {threshold:.0f}m (세그먼트 {seg_idx}) — "
                f"표류/스푸핑/무단이탈 점검 요망.")
    return {
        "assessable": True,
        "deviation_m": round(deviation, 1),
        "within_corridor": within,
        "threshold_m": threshold,
        "threshold_source": threshold_source,
        "nearest_segment_index": seg_idx,
        "advisory_only": True,
        "note": note,
    }
