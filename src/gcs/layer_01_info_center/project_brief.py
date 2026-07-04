"""project_brief — 🔵 결정론 투영. {drone_profile, mettc} → 온보드 6필드 MissionBrief.

B-1 §5.3 매핑 고정: M.uav_mission.purpose → mission_context, corridor.axis →
waypoints(alt = alt_min~max 중앙값), friendly.bases → corridor.bases,
drone_profile 직행(spare 키는 온보드 계약 spare_asset_available). 온보드 02-07
계약은 이 투영본만 소비 — 상태모델 확장이 온보드에 새지 않는다.
"""

from __future__ import annotations

# alt 밴드 부재 시 기본 순항 고도 (기존 examples 관행값).
_DEFAULT_ALT_M = 120.0


def project_onboard_brief(state: dict, sortie_id: str) -> dict:
    """{drone_profile, mettc} → MissionBrief(6필드)."""
    mettc = state["mettc"]
    m = mettc["M"]
    corridor = mettc["T_terrain"]["corridor"]

    # 레거시 온보드 corridor 가 보존돼 있으면 그대로 통과 — waypoint alt_m/id, base alt_m
    # 을 합성하지 않고 원본 유지 (하위호환, codex P1).
    onboard = corridor.get("_onboard_corridor")
    if onboard and onboard.get("waypoints"):
        onboard_corridor: dict = {
            "waypoints": [dict(w) for w in onboard["waypoints"]],
            "bases": {k: dict(v) for k, v in (onboard.get("bases") or {}).items()},
        }
        if corridor.get("half_width") is not None:
            onboard_corridor["half_width"] = corridor["half_width"]
        return {
            "sortie_id": sortie_id,
            "mission_context": (m.get("uav_mission") or {}).get("purpose") or None,
            "posture": dict(m["posture"]),
            "drone_profile": dict(state["drone_profile"]),
            "corridor": onboard_corridor,
            "weights": dict(m["weights"]),
        }

    alt_min, alt_max = corridor.get("alt_min"), corridor.get("alt_max")
    alt = (alt_min + alt_max) / 2.0 if alt_min is not None and alt_max is not None else _DEFAULT_ALT_M

    waypoints = [
        {"id": f"wp{i + 1}", "lat": p[0], "lon": p[1], "alt_m": alt}
        for i, p in enumerate(corridor.get("axis") or [])
    ]

    bases: dict = {}
    for b in mettc["T_troops"]["friendly"].get("bases") or []:
        pos = b.get("pos") or [None, None]
        bases[b.get("type") or b.get("id")] = {
            "id": b.get("id"), "lat": pos[0], "lon": pos[1], "alt_m": None,
        }

    mission_context = (m.get("uav_mission") or {}).get("purpose") or None

    projected_corridor: dict = {"waypoints": waypoints, "bases": bases}
    if corridor.get("half_width") is not None:
        projected_corridor["half_width"] = corridor["half_width"]

    return {
        "sortie_id": sortie_id,
        "mission_context": mission_context,
        "posture": dict(m["posture"]),
        "drone_profile": dict(state["drone_profile"]),
        "corridor": projected_corridor,
        "weights": dict(m["weights"]),
    }
