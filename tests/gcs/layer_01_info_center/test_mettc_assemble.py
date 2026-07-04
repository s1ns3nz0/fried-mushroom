"""mettc_assemble — B-1 정본 {drone_profile, mettc} 조립 검증 (TDD, B-1 §1·§5.1).

킬러 ①: 조립본이 B-1 §1 예시 골격(6요소 + 필수 키)과 적합.
"""

import pytest

from gcs.layer_01_info_center.c4i_schema import normalize_c4i
from gcs.layer_01_info_center.mettc_assemble import assemble_mettc

_METTC_KEYS = {"M", "E", "T_terrain", "T_troops", "T_time", "C"}


def _set_mission(**over):
    base = {
        "sortie_id": "MET-01",
        "directive_text": "적 저격조 확인됨",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"id": "uav-7", "type": "quadrotor", "endurance_rated_s": 1800,
                          "spare_asset_available": True, "armament": [], "battery_pct": 65,
                          "sensor_suite": ["eo", "ir"]},
        "corridor_spec": {"type": "polyline_buffer", "axis": [[37.70, 127.20], [37.72, 127.22]],
                          "half_width": 20, "alt_min": 50, "alt_max": 300},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "higher_intent": "상급 의도",
        "unit_mission": "부대 임무",
        "uav_mission": {"name": "recon-A", "purpose": "정찰", "type": "recon", "goal": [37.72, 127.22]},
        "bases": [{"id": "home", "pos": [37.70, 127.20], "type": "home", "available": True}],
    }
    base.update(over)
    return base


def _c4i(**over):
    return normalize_c4i({
        "enemy_tracks": [{"track_id": "trk-1", "kind": "humint", "pos": [37.71, 127.21],
                          "confidence": 0.8, "label": "적 저격조 활동"}],
        "civil_density_draft": [{"id": "c-1", "center": [37.7, 127.2], "radius": 15, "density": "high"}],
        **over,
    })


def test_killer_b1_skeleton_conformance() -> None:
    state = assemble_mettc(_set_mission(), _c4i(), signals=[])
    assert set(state) == {"drone_profile", "mettc"}
    assert set(state["mettc"]) == _METTC_KEYS
    m = state["mettc"]["M"]
    assert m["posture"]["infocon"] == 4
    assert m["higher_intent"] == "상급 의도"
    assert m["uav_mission"]["purpose"] == "정찰"
    assert m["weights"]["stealth"] == 0.4
    assert state["mettc"]["T_terrain"]["corridor"]["half_width"] == 20


def test_e_tracks_from_c4i_with_source_tag() -> None:
    state = assemble_mettc(_set_mission(), _c4i(), signals=[])
    tracks = state["mettc"]["E"]["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["source"] == "c4i"
    assert tracks[0]["history"] == [] and tracks[0]["last_seen_tick"] is None


def test_initial_values_convention() -> None:
    # B-1 §5.1 초기값 규약.
    state = assemble_mettc(_set_mission(), _c4i(), signals=[])
    tt = state["mettc"]["T_time"]
    assert tt["elapsed_s"] == 0 and tt["eta_goal_s"] is None
    assert tt["endurance_s"] == 1800  # rated 에서 시작
    troops = state["mettc"]["T_troops"]
    assert troops["pos"][:2] == [37.70, 127.20]  # home base
    assert troops["battery"] == pytest.approx(0.65)
    assert troops["gps_quality"] is None and troops["comms_q"] is None
    assert state["mettc"]["T_terrain"]["weather"] is None
    assert state["mettc"]["T_terrain"]["terrain_ref"] == "onboard_dem"


def test_civil_sensitivity_from_draft_max_density() -> None:
    state = assemble_mettc(_set_mission(), _c4i(), signals=[])
    assert state["mettc"]["C"]["civil_sensitivity_estimate"] == "high"
    assert len(state["mettc"]["C"]["civil_areas"]) == 1


def test_civil_sensitivity_default_low() -> None:
    state = assemble_mettc(_set_mission(), normalize_c4i({}), signals=[])
    assert state["mettc"]["C"]["civil_sensitivity_estimate"] == "low"


def test_bases_into_t_troops_friendly() -> None:
    state = assemble_mettc(_set_mission(), _c4i(), signals=[])
    bases = state["mettc"]["T_troops"]["friendly"]["bases"]
    assert bases[0]["id"] == "home" and bases[0]["type"] == "home"


def test_legacy_corridor_waypoints_converted_to_axis() -> None:
    # corridor_spec 없이 기존 waypoints 형 → axis 역변환 (하위호환).
    sm = _set_mission()
    del sm["corridor_spec"]
    sm["corridor"] = {"waypoints": [{"id": "wp1", "lat": 37.70, "lon": 127.20, "alt_m": 120},
                                    {"id": "wp2", "lat": 37.72, "lon": 127.22, "alt_m": 120}],
                      "bases": {}}
    state = assemble_mettc(sm, normalize_c4i({}), signals=[])
    axis = state["mettc"]["T_terrain"]["corridor"]["axis"]
    assert axis == [[37.70, 127.20], [37.72, 127.22]]


def test_missing_required_raises() -> None:
    sm = _set_mission()
    del sm["posture"]
    with pytest.raises((ValueError, KeyError)):
        assemble_mettc(sm, normalize_c4i({}), signals=[])
