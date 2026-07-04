"""layer_06_response.run 골든 테스트."""
from onboard.layer_06_response.run import run


def _make_candidate(threat_event, rac, kill_chain_stage, ai_reliability="normal", rank=1):
    return {
        "threat_event": threat_event,
        "match_count": 2,
        "confidence": 0.90,
        "confidence_source": "deterministic",
        "kill_chain_stage": kill_chain_stage,
        "potential_outcome": "attrition_kill",
        "rac": rac,
        "l_class_final": "A",
        "severity_label_final": "Critical",
        "compound_risk_assessment": {"ai_reliability": ai_reliability},
        "compound_urgency_score": 0.85,
        "priority_rank": rank,
    }


_BRIEF = {
    "sortie_id": "TEST-01",
    "mission_context": "정찰",
    "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
    "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 65},
    "corridor": {},
    "weights": {},
}


def test_t3_late_high_rtl():
    risk = {"candidates": [_make_candidate("T3", "High", "후기")]}
    out = run(risk, _BRIEF)
    assert out["primary_threat_event"] == "T3"
    assert out["flight_action"] == "RTL"
    assert out["comms_level"] == "L3"
    assert out["threat_category"] == "PHYSICAL"
    assert out["payload_action"] == ["DATA_WIPE"]
    assert out["secondary_threats"] == []


def test_t3_early_high_posture_elevate():
    risk = {"candidates": [_make_candidate("T3", "High", "초기")]}
    out = run(risk, _BRIEF)
    assert out["flight_action"] == "POSTURE_ELEVATE"
    assert out["special_action"] == "INCREASE_ASSESSMENT_FREQUENCY"


def test_t4_late_high():
    risk = {"candidates": [_make_candidate("T4", "High", "후기")]}
    out = run(risk, _BRIEF)
    assert out["flight_action"] == "RTL"
    assert out["comms_level"] == "L3"
    assert out["payload_action"] == ["DATA_WIPE"]
    assert out["nav_mode"] is None


def test_t7_high_late_navigation():
    risk = {"candidates": [_make_candidate("T7", "High", "후기")]}
    out = run(risk, _BRIEF)
    assert out["threat_category"] == "NAVIGATION"
    assert out["flight_action"] == "ALTITUDE_CHANGE_REROUTE"


def test_no_threat_fallback_low():
    risk = {"candidates": [], "ambient_rac": "Low"}
    out = run(risk, _BRIEF)
    assert out["primary_threat_event"] is None
    assert out["rac"] == "Low"
    assert out["flight_action"] == "MAINTAIN"
    assert out["comms_level"] == "L0"


def test_secondary_threats_populated():
    primary = _make_candidate("T3", "High", "후기", rank=1)
    secondary = _make_candidate("T7", "Serious", "중기", rank=2)
    risk = {"candidates": [primary, secondary]}
    out = run(risk, _BRIEF)
    assert len(out["secondary_threats"]) == 1
    assert out["secondary_threats"][0]["threat_event"] == "T7"


def test_ai_reliability_propagated():
    risk = {"candidates": [_make_candidate("T3", "High", "후기", ai_reliability="low")]}
    out = run(risk, _BRIEF)
    assert out["ai_reliability"] == "low"
