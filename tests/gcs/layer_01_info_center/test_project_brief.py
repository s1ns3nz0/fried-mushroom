"""project_brief — mettc → 온보드 6필드 MissionBrief 투영 (TDD, B-1 §5.3)."""

from gcs.layer_01_info_center.c4i_schema import normalize_c4i
from gcs.layer_01_info_center.mettc_assemble import assemble_mettc
from gcs.layer_01_info_center.project_brief import project_onboard_brief

_BRIEF_KEYS = {"sortie_id", "mission_context", "posture", "drone_profile", "corridor", "weights"}


def _state():
    sm = {
        "sortie_id": "PRJ-01",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": True, "armament": [], "battery_pct": 65},
        "corridor_spec": {"type": "polyline_buffer", "axis": [[37.70, 127.20], [37.72, 127.22]],
                          "half_width": 20, "alt_min": 50, "alt_max": 300},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "uav_mission": {"name": "r", "purpose": "정찰", "type": "recon", "goal": None},
        "bases": [{"id": "home", "pos": [37.70, 127.20], "type": "home", "available": True}],
    }
    return assemble_mettc(sm, normalize_c4i({}), signals=[]), sm


def test_projects_exact_six_fields() -> None:
    state, sm = _state()
    brief = project_onboard_brief(state, sortie_id=sm["sortie_id"])
    assert set(brief) == _BRIEF_KEYS
    assert brief["mission_context"] == "정찰"  # uav_mission.purpose
    assert brief["posture"]["infocon"] == 4
    assert brief["weights"]["stealth"] == 0.4


def test_axis_to_waypoints_with_mid_altitude() -> None:
    state, sm = _state()
    brief = project_onboard_brief(state, sortie_id=sm["sortie_id"])
    wps = brief["corridor"]["waypoints"]
    assert len(wps) == 2
    assert wps[0]["lat"] == 37.70 and wps[0]["lon"] == 127.20
    assert wps[0]["alt_m"] == 175.0  # (50+300)/2
    assert wps[0]["id"] == "wp1" and wps[1]["id"] == "wp2"


def test_bases_projected() -> None:
    state, sm = _state()
    brief = project_onboard_brief(state, sortie_id=sm["sortie_id"])
    assert brief["corridor"]["bases"]["home"]["lat"] == 37.70


def test_spare_key_conformance() -> None:
    state, sm = _state()
    brief = project_onboard_brief(state, sortie_id=sm["sortie_id"])
    assert brief["drone_profile"]["spare_asset_available"] is True


def test_no_alt_band_default_altitude() -> None:
    state, sm = _state()
    state["mettc"]["T_terrain"]["corridor"]["alt_min"] = None
    state["mettc"]["T_terrain"]["corridor"]["alt_max"] = None
    brief = project_onboard_brief(state, sortie_id="X")
    assert brief["corridor"]["waypoints"][0]["alt_m"] is not None  # 기본 고도


def test_half_width_preserved_in_projected_corridor() -> None:
    """corridor_spec.half_width 가 투영 후 corridor.half_width 로 보존돼야 한다 (#363)."""
    state, sm = _state()
    brief = project_onboard_brief(state, sortie_id=sm["sortie_id"])
    assert brief["corridor"].get("half_width") == 20, (
        "corridor_spec.half_width=20 이 투영 후 corridor.half_width 로 전달돼야 함"
    )


def test_half_width_none_when_not_in_spec() -> None:
    """half_width 없는 corridor_spec 투영 시 corridor.half_width 는 None 또는 키 부재."""
    sm = {
        "sortie_id": "PRJ-02",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": True, "armament": [], "battery_pct": 65},
        "corridor_spec": {"type": "polyline_buffer", "axis": [[37.70, 127.20]],
                          "alt_min": 50, "alt_max": 300},  # half_width 없음
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "uav_mission": {"name": "r", "purpose": "정찰", "type": "recon", "goal": None},
        "bases": [],
    }
    state = assemble_mettc(sm, normalize_c4i({}), signals=[])
    brief = project_onboard_brief(state, sortie_id=sm["sortie_id"])
    # half_width 없으면 corridor_deviation 이 default fallback 을 써야 함
    assert brief["corridor"].get("half_width") is None


def test_half_width_used_as_threshold_source_end_to_end() -> None:
    """GCS 투영 후 onboard corridor 이탈 감시가 half_width 를 임계로 사용해야 한다 (#363)."""
    from onboard.corridor import assess_corridor_deviation
    from onboard.layer_02_sensor.mock_source import build_normal_envelope

    state, sm = _state()  # half_width=20
    brief = project_onboard_brief(state, sortie_id=sm["sortie_id"])
    raw = build_normal_envelope("E2E", 0, 0)
    out = assess_corridor_deviation(raw, brief)
    # half_width=20 이 브리핑에 실려 threshold_source 가 "half_width" 이어야 한다.
    assert out["threshold_source"] == "half_width", (
        f"threshold_source={out['threshold_source']!r} — 'half_width' 기대"
    )
    assert out["threshold_m"] == 20


def test_legacy_corridor_preserves_waypoint_alt_and_ids_and_base_alt() -> None:
    # codex P1 회귀: 레거시 corridor 라운드트립이 per-waypoint alt_m/id, base alt_m 을
    # 소실하면 안 됨 (승인 비행계획 변경 방지).
    from gcs.layer_01_info_center.run import assemble_draft
    inp = {
        "sortie_id": "L", "directive_text": "", "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": True, "armament": [], "battery_pct": 65},
        "corridor": {"waypoints": [{"id": "wpA", "lat": 37.7, "lon": 127.2, "alt_m": 150}],
                     "bases": {"emergency": {"id": "base_e", "lat": 37.49, "lon": 127.0, "alt_m": 50}}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
    }
    corr = assemble_draft(inp)["draft_brief"]["corridor"]
    wp = corr["waypoints"][0]
    assert wp["id"] == "wpA" and wp["alt_m"] == 150
    assert corr["bases"]["emergency"]["alt_m"] == 50
    assert corr["bases"]["emergency"]["id"] == "base_e"
