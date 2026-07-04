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
