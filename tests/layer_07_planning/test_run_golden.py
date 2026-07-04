"""layer_07_planning.run 골든 테스트."""
import pytest
from onboard.layer_07_planning.run import run


def _make_response(flight_action, threat_category=None, rac="High", kill_chain_stage="후기"):
    return {
        "primary_threat_event": None,
        "rac": rac,
        "kill_chain_stage": kill_chain_stage,
        "threat_category": threat_category,
        "flight_action": flight_action,
        "comms_level": "L0",
        "payload_action": [],
        "nav_mode": None,
        "special_action": None,
        "secondary_threats": [],
        "ai_reliability": "normal",
    }


_CYCLE_CTX = {
    "lowest_exposure_bearing_deg": 270,
    "optimal_terrain_bearing_deg": 180,
}


def test_t3_physical_rtl():
    response = _make_response("RTL", "PHYSICAL")
    out = run(response, {"bearing_deg": 45.0}, _CYCLE_CTX)
    assert out["flight_action"] == "RTL"
    assert out["target_bearing_deg"] == 225.0
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "threat_reverse(channel)"


def test_t7_navigation_altitude_change_reroute():
    response = _make_response("ALTITUDE_CHANGE_REROUTE", "NAVIGATION")
    out = run(response, None, _CYCLE_CTX)
    assert out["altitude_delta_m"] == 50
    assert out["target_bearing_deg"] == 180
    assert out["replan_scope"] == "FULL"
    assert out["reroute_anchor"] == "optimal_terrain"


def test_maintain_all_zero():
    response = _make_response("MAINTAIN", None, rac="Low", kill_chain_stage=None)
    out = run(response, None, _CYCLE_CTX)
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "NONE"
    assert out["reroute_anchor"] is None


def test_posture_elevate_altitude_only():
    response = _make_response("POSTURE_ELEVATE", "PHYSICAL")
    out = run(response, None, _CYCLE_CTX)
    assert out["altitude_delta_m"] == 25
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "terrain_fallback"


def test_reroute_full_scope():
    response = _make_response("REROUTE", "REMOTE")
    out = run(response, {"bearing_deg": 90.0}, _CYCLE_CTX)
    assert out["replan_scope"] == "FULL"
    assert out["target_bearing_deg"] == 270.0


def test_unknown_flight_action_raises():
    response = _make_response("INVALID")
    with pytest.raises(KeyError):
        run(response, None, _CYCLE_CTX)


def test_remote_reroute_with_bearing_anchor():
    response = _make_response("REROUTE", "REMOTE")
    out = run(response, {"bearing_deg": 90.0}, _CYCLE_CTX)
    assert out["reroute_anchor"] == "threat_reverse(channel)"
    assert out["target_bearing_deg"] == 270.0
    assert out["replan_scope"] == "FULL"


def test_remote_reroute_no_bearing_anchor():
    response = _make_response("REROUTE", "REMOTE")
    out = run(response, None, _CYCLE_CTX)
    assert out["reroute_anchor"] == "last_known_good_position"
    assert out["target_bearing_deg"] is None
    assert out["replan_scope"] == "FULL"


def test_cfit_override_maintain_to_altitude_change():
    """TTC<3s + MAINTAIN → ALTITUDE_CHANGE 결정론적 override (RAC 무관)."""
    response = _make_response("MAINTAIN", "NAVIGATION", rac="Medium", kill_chain_stage=None)
    ctx = {**_CYCLE_CTX, "obstacle_ttc_s": 1.875}
    out = run(response, None, ctx)
    assert out["flight_action"] == "ALTITUDE_CHANGE"
    assert out["altitude_delta_m"] == 15
    assert out["replan_scope"] == "LOCAL"


def test_cfit_override_not_triggered_when_ttc_safe():
    """TTC>=3s → override 없음, MAINTAIN 유지."""
    response = _make_response("MAINTAIN", None, rac="Low", kill_chain_stage=None)
    ctx = {**_CYCLE_CTX, "obstacle_ttc_s": 5.0}
    out = run(response, None, ctx)
    assert out["flight_action"] == "MAINTAIN"
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "NONE"


def test_cfit_override_not_triggered_when_already_climbing():
    """TTC<3s 이지만 이미 ALTITUDE_CHANGE_REROUTE → 더 적극적 기존 action 유지."""
    response = _make_response("ALTITUDE_CHANGE_REROUTE", "NAVIGATION")
    ctx = {**_CYCLE_CTX, "obstacle_ttc_s": 1.0}
    out = run(response, None, ctx)
    assert out["flight_action"] == "ALTITUDE_CHANGE_REROUTE"
    assert out["altitude_delta_m"] == 50


# --- 미커버 분기 보완 (issue #76) ---

def test_posture_elevate_target_bearing_locked():
    """POSTURE_ELEVATE + PHYSICAL + bearing 없음 → target_bearing_deg=lowest_exposure(270) 잠금."""
    response = _make_response("POSTURE_ELEVATE", "PHYSICAL")
    out = run(response, None, _CYCLE_CTX)
    assert out["flight_action"] == "POSTURE_ELEVATE"
    assert out["target_bearing_deg"] == 270
    assert out["altitude_delta_m"] == 25
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "terrain_fallback"


def test_rtl_terrain_fallback():
    """RTL + PHYSICAL + bearing 없음 → lowest_exposure_bearing_deg 사용, terrain_fallback anchor."""
    response = _make_response("RTL", "PHYSICAL")
    out = run(response, None, _CYCLE_CTX)
    assert out["flight_action"] == "RTL"
    assert out["target_bearing_deg"] == 270
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "terrain_fallback"


def test_altitude_change_reroute_physical_with_bearing():
    """ALTITUDE_CHANGE_REROUTE + PHYSICAL + bearing → threat_reverse + delta=50 잠금."""
    response = _make_response("ALTITUDE_CHANGE_REROUTE", "PHYSICAL")
    out = run(response, {"bearing_deg": 90.0}, _CYCLE_CTX)
    assert out["flight_action"] == "ALTITUDE_CHANGE_REROUTE"
    assert out["target_bearing_deg"] == 270.0
    assert out["altitude_delta_m"] == 50
    assert out["replan_scope"] == "FULL"
    assert out["reroute_anchor"] == "threat_reverse(channel)"


def test_altitude_change_direct_physical_with_bearing():
    """ALTITUDE_CHANGE 직접(CFIT 경유 아님) + PHYSICAL + bearing → delta=15, scope=LOCAL 잠금."""
    response = _make_response("ALTITUDE_CHANGE", "PHYSICAL")
    out = run(response, {"bearing_deg": 45.0}, _CYCLE_CTX)
    assert out["flight_action"] == "ALTITUDE_CHANGE"
    assert out["target_bearing_deg"] == 225.0
    assert out["altitude_delta_m"] == 15
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "threat_reverse(channel)"
