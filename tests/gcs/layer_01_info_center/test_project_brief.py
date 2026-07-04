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
