"""mettc_assemble — 🔵 결정론. set_mission + C4I → B-1 정본 {drone_profile, mettc} 조립.

B-1 §1 골격(M/E/T_terrain/T_troops/T_time/C) + §5.1 초기값 규약을 따른다.
온보드-소유(obs/내부시계) 필드는 비행 전 시점 초기값/None. E.tracks 는 C4I 트랙에
source:"c4i" 태깅. 필수 입력 누락은 명시적 에러(임무 저작 시맨틱).
"""

from __future__ import annotations

_REQUIRED = ("sortie_id", "mission_context", "posture", "drone_profile", "weights")

_DENSITY_ORDER = {"low": 0, "medium": 1, "high": 2}


def _corridor_from_inputs(set_mission: dict) -> dict:
    """corridor_spec(B-1 형) 우선, 없으면 레거시 corridor.waypoints → axis 역변환."""
    spec = set_mission.get("corridor_spec")
    if spec:
        return {
            "type": spec.get("type", "polyline_buffer"),
            "axis": [list(p) for p in spec.get("axis") or []],
            "half_width": spec.get("half_width"),
            "alt_min": spec.get("alt_min"),
            "alt_max": spec.get("alt_max"),
        }
    legacy = set_mission.get("corridor") or {}
    axis = [[wp["lat"], wp["lon"]] for wp in legacy.get("waypoints") or []]
    # 레거시 온보드 corridor(waypoints alt_m/id, bases alt_m)를 그대로 보존한다.
    # 투영(project_brief)이 이 원본을 우선 사용해 라운드트립 데이터 손실을 막는다(codex P1).
    return {"type": "polyline_buffer", "axis": axis,
            "half_width": None, "alt_min": None, "alt_max": None,
            "_onboard_corridor": {"waypoints": [dict(w) for w in legacy.get("waypoints") or []],
                                  "bases": {k: dict(v) for k, v in (legacy.get("bases") or {}).items()}}}


def _bases_from_inputs(set_mission: dict) -> list[dict]:
    """bases 목록: 신형 bases[] 우선, 레거시 corridor.bases(dict) 변환 수용."""
    if set_mission.get("bases"):
        return [dict(b) for b in set_mission["bases"]]
    legacy = (set_mission.get("corridor") or {}).get("bases") or {}
    out = []
    for key, b in legacy.items():
        if isinstance(b, dict):
            out.append({"id": b.get("id", key), "pos": [b.get("lat"), b.get("lon")],
                        "type": key, "available": True})
    return out


def assemble_mettc(set_mission: dict, c4i: dict, signals: list[dict]) -> dict:
    """{drone_profile, mettc} 조립. c4i 는 normalize_c4i 골격."""
    missing = [f for f in _REQUIRED if f not in set_mission]
    if missing:
        raise ValueError(f"set_mission 필수 필드 누락: {missing}")
    if not set_mission.get("corridor_spec") and not set_mission.get("corridor"):
        raise ValueError("corridor_spec 또는 corridor 중 하나는 필수")

    profile = dict(set_mission["drone_profile"])
    corridor = _corridor_from_inputs(set_mission)
    bases = _bases_from_inputs(set_mission)

    # E.tracks — C4I 트랙 + 출처 태깅 + 지상 시점 초기 필드 (B-1 §5.1/§5.2).
    tracks = []
    for t in c4i.get("enemy_tracks") or []:
        tracks.append({**t, "source": "c4i", "history": [], "last_seen_tick": None})

    # T_troops 초기값 — home base(없으면 axis 첫 점) 위치, 등록 배터리.
    home = next((b for b in bases if b.get("type") == "home"), None)
    pos2 = (home or {}).get("pos") or (corridor["axis"][0] if corridor["axis"] else [None, None])
    battery_pct = profile.get("battery_pct")

    civil_draft = c4i.get("civil_density_draft") or []
    sensitivity = "low"
    for area in civil_draft:
        d = area.get("density", "low")
        if _DENSITY_ORDER.get(d, 0) > _DENSITY_ORDER[sensitivity]:
            sensitivity = d

    mettc = {
        "M": {
            "posture": dict(set_mission["posture"]),
            "higher_intent": set_mission.get("higher_intent"),
            "unit_mission": set_mission.get("unit_mission"),
            "uav_mission": dict(set_mission.get("uav_mission")
                                or {"name": set_mission["sortie_id"],
                                    "purpose": set_mission["mission_context"],
                                    "type": None, "goal": None}),
            "weights": dict(set_mission["weights"]),
        },
        "E": {"tracks": tracks},
        "T_terrain": {
            "terrain_ref": "onboard_dem",  # stub — 실 DEM 후순위
            "H": None, "W": None, "hmin": None, "hmax": None,
            "corridor": corridor,
            "weather": None,  # findings:vlm (온보드)
        },
        "T_troops": {
            "pos": [pos2[0], pos2[1], None],
            "battery": (battery_pct / 100.0) if battery_pct is not None else None,
            "gps_quality": None, "comms_q": None, "sensors_ok": None,
            "armament_state": {"remaining": len(profile.get("armament") or []),
                               "jettisonable": any(a.get("expendable") for a in profile.get("armament") or [])},
            "friendly": {"bases": bases, "assets": []},
        },
        "T_time": {
            "elapsed_s": 0,
            "eta_goal_s": None,
            "endurance_s": profile.get("endurance_rated_s"),
        },
        "C": {
            "no_fly_zones": list(set_mission.get("no_fly_zones") or []),
            "civil_areas": [dict(a) for a in civil_draft],
            "civil_sensitivity_estimate": sensitivity,
        },
    }
    return {"drone_profile": profile, "mettc": mettc}
