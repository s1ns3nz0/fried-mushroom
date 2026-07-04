"""endurance — 🔵 파생 읽기전용. 에너지/내구 기반 RTL(bingo-fuel) 조기권고.

현재 위치·배터리·내구로 "지금 안전 예비를 남기고 홈 베이스까지 돌아갈 수 있는가"를 계산한다.
03 `operational_margin` 은 배터리 잔량을 밴딩(sufficient/limited/critical)만 할 뿐, **귀환
가능성**(홈까지의 거리 × 남은 에너지)은 보지 않는다 — UAV 안전의 핵심인 bingo-fuel 판단이
비어 있었다.

계산: 남은비행시간 = 내구 × 배터리%. RTL소요 = 홈거리 / 순항속도. 예비 = 내구 × reserve_frac.
여유(margin) = 남은비행시간 − 예비 − RTL소요. margin ≤ 0 이면 **지금 RTL 해야** 예비를 남기고
홈에 도달한다(bingo 도달).

CRITICAL (SCC-1): advisory 만. 결정론 RTL 판정(06 Response)을 **대체하지 않고** 병렬 에너지
안전지표로만 제공한다. 입력을 변이하지 않으며 `EARTH_RADIUS_M`(읽기전용)만 참조한다.
"""

from __future__ import annotations

import math
from typing import Any

from onboard.shared.constants import EARTH_RADIUS_M

# 순항속도 기본값(m/s) — 실측 전 팀 설계값(sim NORMAL 과 동일 스케일). advisory 라 상수 불변 대상 아님.
_DEFAULT_CRUISE_MPS = 17.0
# 홈 도달 시 남겨야 할 내구 예비 비율(배터리 리저브).
_DEFAULT_RESERVE_FRAC = 0.15
# 홈 베이스 선택 우선순위.
_BASE_PRIORITY = ("home", "emergency", "alternate")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _pick_home(bases: Any) -> dict | None:
    """베이스에서 귀환 목적지 선택 (home > emergency > alternate > 첫 항목)."""
    if isinstance(bases, dict):
        for key in _BASE_PRIORITY:
            b = bases.get(key)
            if isinstance(b, dict) and b.get("lat") is not None and b.get("lon") is not None:
                return b
        for b in bases.values():
            if isinstance(b, dict) and b.get("lat") is not None and b.get("lon") is not None:
                return b
    elif isinstance(bases, list):
        by_type = {b.get("type"): b for b in bases if isinstance(b, dict)}
        for key in _BASE_PRIORITY:
            b = by_type.get(key)
            if b and b.get("lat") is not None:
                return b
        for b in bases:
            if isinstance(b, dict) and b.get("lat") is not None:
                return b
    return None


def _report(assessable, action, **kw):
    base = {
        "assessable": assessable, "recommended_action": action, "advisory_only": True,
        "rtl_required": kw.get("rtl_required", False),
        "margin_s": kw.get("margin_s"), "dist_home_m": kw.get("dist_home_m"),
        "rtl_time_s": kw.get("rtl_time_s"), "remaining_endurance_s": kw.get("remaining_endurance_s"),
        "reserve_s": kw.get("reserve_s"), "battery_pct": kw.get("battery_pct"),
        "home_base_id": kw.get("home_base_id"), "note": kw.get("note", ""),
    }
    return base


def assess_endurance(
    raw: dict[str, Any],
    mission_brief: dict[str, Any],
    *,
    cruise_speed_mps: float = _DEFAULT_CRUISE_MPS,
    reserve_frac: float = _DEFAULT_RESERVE_FRAC,
    endurance_rated_s: float | None = None,
) -> dict[str, Any]:
    """raw + mission_brief → 에너지 기반 RTL 권고(bingo-fuel). advisory.

    반환: {assessable, recommended_action(RTL|CONTINUE|UNKNOWN), rtl_required, margin_s,
           dist_home_m, rtl_time_s, remaining_endurance_s, reserve_s, battery_pct,
           home_base_id, note, advisory_only}
    """
    raw = raw or {}
    mission_brief = mission_brief or {}
    gps = (raw.get("navigation") or {}).get("gps") or {}
    lat, lon = gps.get("lat"), gps.get("lon")
    bases = (mission_brief.get("corridor") or {}).get("bases")
    home = _pick_home(bases)
    battery_pct = ((raw.get("health") or {}).get("battery") or {}).get("pct")

    if lat is None or lon is None or home is None:
        return _report(False, "UNKNOWN", battery_pct=battery_pct,
                       note="위치 또는 귀환 베이스 부재 — 에너지 RTL 판단 불가.")

    dist_home_m = _haversine_m(lat, lon, home["lat"], home["lon"])
    rtl_time_s = dist_home_m / cruise_speed_mps if cruise_speed_mps > 0 else float("inf")
    home_id = home.get("id")

    endurance = endurance_rated_s if endurance_rated_s is not None \
        else (mission_brief.get("drone_profile") or {}).get("endurance_rated_s")
    if endurance is None or battery_pct is None:
        return _report(False, "UNKNOWN", dist_home_m=dist_home_m, rtl_time_s=rtl_time_s,
                       battery_pct=battery_pct, home_base_id=home_id,
                       note=f"홈까지 {dist_home_m:.0f}m — 내구/배터리 정보 부재로 여유 계산 불가.")

    remaining_s = endurance * (battery_pct / 100.0)
    reserve_s = endurance * reserve_frac
    margin_s = remaining_s - reserve_s - rtl_time_s
    rtl_required = margin_s <= 0
    action = "RTL" if rtl_required else "CONTINUE"
    if rtl_required:
        note = (f"⚠ bingo 도달 — 홈 {dist_home_m:.0f}m(RTL {rtl_time_s:.0f}s), 잔여 {remaining_s:.0f}s, "
                f"예비 {reserve_s:.0f}s → 여유 {margin_s:.0f}s. 지금 RTL 권고.")
    else:
        note = (f"홈 {dist_home_m:.0f}m(RTL {rtl_time_s:.0f}s), 잔여 {remaining_s:.0f}s, "
                f"여유 {margin_s:.0f}s — 임무 지속 가능.")
    return _report(True, action, rtl_required=rtl_required, margin_s=round(margin_s, 1),
                   dist_home_m=round(dist_home_m, 1), rtl_time_s=round(rtl_time_s, 1),
                   remaining_endurance_s=round(remaining_s, 1), reserve_s=round(reserve_s, 1),
                   battery_pct=battery_pct, home_base_id=home_id, note=note)
