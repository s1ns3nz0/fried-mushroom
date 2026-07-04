"""layer_07_planning.run 골든 테스트.

run() 은 (FlightPlanOutput, debounce_state) 튜플을 반환한다(신규 — RAC 완화
디바운스, ADR-004 07 한정 예외). debounce_state=None(기본값) 이면 첫 사이클
취급으로 디바운스 없이 즉시 반영되므로, 기존 단일 사이클 테스트들은 두 번째
반환값을 무시(`_`)하는 것 외엔 영향받지 않는다.
"""
import pytest
from onboard.layer_07_planning.run import run
from onboard.shared.constants import RAC_ORDER


def _make_response(flight_action, threat_category=None, rac="High", kill_chain_stage="후기",
                    primary_threat_event=None):
    return {
        "primary_threat_event": primary_threat_event,
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
    out, _ = run(response, {"bearing_deg": 45.0}, _CYCLE_CTX)
    assert out["flight_action"] == "RTL"
    assert out["target_bearing_deg"] == 225.0
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "threat_reverse(channel)"
    assert out["speed_mode"] == "MAX"


def test_t7_navigation_altitude_change_reroute():
    response = _make_response("ALTITUDE_CHANGE_REROUTE", "NAVIGATION")
    out, _ = run(response, None, _CYCLE_CTX)
    assert out["altitude_delta_m"] == 50
    assert out["target_bearing_deg"] == 180
    assert out["replan_scope"] == "FULL"
    assert out["reroute_anchor"] == "optimal_terrain"
    assert out["speed_mode"] == "MAX"


def test_maintain_all_zero():
    response = _make_response("MAINTAIN", None, rac="Low", kill_chain_stage=None)
    out, _ = run(response, None, _CYCLE_CTX)
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "NONE"
    assert out["reroute_anchor"] == "mission_corridor_resume"  # 신규 확정 — null 아님
    assert out["speed_mode"] == "NORMAL"


def test_posture_elevate_altitude_only():
    response = _make_response("POSTURE_ELEVATE", "PHYSICAL")
    out, _ = run(response, None, _CYCLE_CTX)
    assert out["altitude_delta_m"] == 25
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "terrain_fallback"
    assert out["speed_mode"] == "CAUTIOUS"


def test_reroute_full_scope():
    response = _make_response("REROUTE", "REMOTE")
    out, _ = run(response, {"bearing_deg": 90.0}, _CYCLE_CTX)
    assert out["replan_scope"] == "FULL"
    assert out["target_bearing_deg"] == 270.0
    assert out["speed_mode"] == "MAX"


def test_unknown_flight_action_raises():
    response = _make_response("INVALID")
    with pytest.raises(KeyError):
        run(response, None, _CYCLE_CTX)


def test_remote_reroute_with_bearing_anchor():
    response = _make_response("REROUTE", "REMOTE")
    out, _ = run(response, {"bearing_deg": 90.0}, _CYCLE_CTX)
    assert out["reroute_anchor"] == "threat_reverse(channel)"
    assert out["target_bearing_deg"] == 270.0
    assert out["replan_scope"] == "FULL"


def test_remote_reroute_no_bearing_anchor():
    response = _make_response("REROUTE", "REMOTE")
    out, _ = run(response, None, _CYCLE_CTX)
    assert out["reroute_anchor"] == "last_known_good_position"
    assert out["target_bearing_deg"] is None
    assert out["replan_scope"] == "FULL"


def test_cfit_override_maintain_to_altitude_change():
    """TTC<3s + MAINTAIN → ALTITUDE_CHANGE 결정론적 override (RAC 무관)."""
    response = _make_response("MAINTAIN", "NAVIGATION", rac="Medium", kill_chain_stage=None)
    ctx = {**_CYCLE_CTX, "obstacle_ttc_s": 1.875}
    out, _ = run(response, None, ctx)
    assert out["flight_action"] == "ALTITUDE_CHANGE"
    assert out["altitude_delta_m"] == 15
    assert out["replan_scope"] == "LOCAL"
    assert out["speed_mode"] == "NORMAL"  # override 이후 effective_action(ALTITUDE_CHANGE) 기준


def test_cfit_override_not_triggered_when_ttc_safe():
    """TTC>=3s → override 없음, MAINTAIN 유지."""
    response = _make_response("MAINTAIN", None, rac="Low", kill_chain_stage=None)
    ctx = {**_CYCLE_CTX, "obstacle_ttc_s": 5.0}
    out, _ = run(response, None, ctx)
    assert out["flight_action"] == "MAINTAIN"
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "NONE"


def test_cfit_override_not_triggered_when_already_climbing():
    """TTC<3s 이지만 이미 ALTITUDE_CHANGE_REROUTE → 더 적극적 기존 action 유지."""
    response = _make_response("ALTITUDE_CHANGE_REROUTE", "NAVIGATION")
    ctx = {**_CYCLE_CTX, "obstacle_ttc_s": 1.0}
    out, _ = run(response, None, ctx)
    assert out["flight_action"] == "ALTITUDE_CHANGE_REROUTE"
    assert out["altitude_delta_m"] == 50


def test_cfit_override_speed_mode_ignores_weights():
    """(신규) CFIT override는 weights와 무관하게 항상 NORMAL — survival 우세여도 안 올라감(SCC-1)."""
    response = _make_response("MAINTAIN", "NAVIGATION", rac="Medium", kill_chain_stage=None)
    weights = {"stealth": 0.1, "survival": 0.5, "info_value": 0.3, "timeliness": 0.1}
    ctx = {**_CYCLE_CTX, "obstacle_ttc_s": 1.875, "weights": weights}
    out, _ = run(response, None, ctx)
    assert out["flight_action"] == "ALTITUDE_CHANGE"
    assert out["speed_mode"] == "NORMAL", "CFIT는 안전 최우선 — weights로 속도를 올리면 안 됨"


def test_non_cfit_maintain_speed_mode_reflects_weights():
    """(신규) CFIT 없는 정상 MAINTAIN은 weights.survival 우세 시 speed_mode가 MAX로 올라감."""
    response = _make_response("MAINTAIN", None, rac="Low", kill_chain_stage=None)
    weights = {"stealth": 0.1, "survival": 0.5, "info_value": 0.3, "timeliness": 0.1}
    out, _ = run(response, None, {**_CYCLE_CTX, "weights": weights})
    assert out["flight_action"] == "MAINTAIN"
    assert out["speed_mode"] == "MAX"


# --- 미커버 분기 보완 (issue #76) ---

def test_posture_elevate_target_bearing_locked():
    """POSTURE_ELEVATE + PHYSICAL + bearing 없음 → target_bearing_deg=lowest_exposure(270) 잠금."""
    response = _make_response("POSTURE_ELEVATE", "PHYSICAL")
    out, _ = run(response, None, _CYCLE_CTX)
    assert out["flight_action"] == "POSTURE_ELEVATE"
    assert out["target_bearing_deg"] == 270
    assert out["altitude_delta_m"] == 25
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "terrain_fallback"


def test_rtl_terrain_fallback():
    """RTL + PHYSICAL + bearing 없음 → lowest_exposure_bearing_deg 사용, terrain_fallback anchor."""
    response = _make_response("RTL", "PHYSICAL")
    out, _ = run(response, None, _CYCLE_CTX)
    assert out["flight_action"] == "RTL"
    assert out["target_bearing_deg"] == 270
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "terrain_fallback"


def test_altitude_change_reroute_physical_with_bearing():
    """ALTITUDE_CHANGE_REROUTE + PHYSICAL + bearing → threat_reverse + delta=50 잠금."""
    response = _make_response("ALTITUDE_CHANGE_REROUTE", "PHYSICAL")
    out, _ = run(response, {"bearing_deg": 90.0}, _CYCLE_CTX)
    assert out["flight_action"] == "ALTITUDE_CHANGE_REROUTE"
    assert out["target_bearing_deg"] == 270.0
    assert out["altitude_delta_m"] == 50
    assert out["replan_scope"] == "FULL"
    assert out["reroute_anchor"] == "threat_reverse(channel)"


def test_altitude_change_direct_physical_with_bearing():
    """ALTITUDE_CHANGE 직접(CFIT 경유 아님) + PHYSICAL + bearing → delta=15, scope=LOCAL 잠금."""
    response = _make_response("ALTITUDE_CHANGE", "PHYSICAL")
    out, _ = run(response, {"bearing_deg": 45.0}, _CYCLE_CTX)
    assert out["flight_action"] == "ALTITUDE_CHANGE"
    assert out["target_bearing_deg"] == 225.0
    assert out["altitude_delta_m"] == 15
    assert out["replan_scope"] == "LOCAL"
    assert out["reroute_anchor"] == "threat_reverse(channel)"


# ---------------------------------------------------------------------------
# RAC 완화 디바운스 통합 (신규 — ADR-004 07 한정 예외, run() 튜플 반환)
# ---------------------------------------------------------------------------


def test_first_cycle_no_debounce_state_immediate():
    """debounce_state=None(첫 사이클) → 디바운스 없이 그대로 반영, 상태 초기화."""
    response = _make_response("RTL", "PHYSICAL", rac="High")
    out, state = run(response, {"bearing_deg": 45.0}, _CYCLE_CTX)
    assert out["flight_action"] == "RTL"
    assert state["committed_rac_order"] == RAC_ORDER["High"]
    assert state["committed_flight_action"] == "RTL"


def test_deescalation_across_cycles_holds_then_releases():
    """RTL(High) 진입 후 MAINTAIN(Low)으로 완화 — 3사이클 연속돼야 실제로 MAINTAIN 반영."""
    rtl_response = _make_response("RTL", "PHYSICAL", rac="High")
    out0, state = run(rtl_response, {"bearing_deg": 45.0}, _CYCLE_CTX)
    assert out0["flight_action"] == "RTL"

    maintain_response = _make_response("MAINTAIN", None, rac="Low", kill_chain_stage=None)

    out1, state = run(maintain_response, None, _CYCLE_CTX, state)
    assert out1["flight_action"] == "RTL", "1사이클차 완화는 아직 반영 안 됨"

    out2, state = run(maintain_response, None, _CYCLE_CTX, state)
    assert out2["flight_action"] == "RTL", "2사이클차도 아직(N=3 미달)"

    out3, state = run(maintain_response, None, _CYCLE_CTX, state)
    assert out3["flight_action"] == "MAINTAIN", "3사이클차에 비로소 반영"
    assert out3["reroute_anchor"] == "mission_corridor_resume"


def test_escalation_immediate_even_mid_debounce():
    """완화 스트릭 진행 중이라도 다시 악화되면 즉시 반영(안전 우선, SCC-1)."""
    rtl_response = _make_response("RTL", "PHYSICAL", rac="High")
    _, state = run(rtl_response, {"bearing_deg": 45.0}, _CYCLE_CTX)

    medium_response = _make_response("ALTITUDE_CHANGE", "PHYSICAL", rac="Medium")
    out1, state = run(medium_response, {"bearing_deg": 45.0}, _CYCLE_CTX, state)
    assert out1["flight_action"] == "RTL", "완화 1사이클차 — 아직 RTL 유지"

    # 다시 High로 악화 — 디바운스 없이 즉시 RTL 반영(원래도 RTL 이었지만 committed 갱신 확인)
    out2, state = run(rtl_response, {"bearing_deg": 45.0}, _CYCLE_CTX, state)
    assert out2["flight_action"] == "RTL"
    assert state["candidate_streak"] == 0


def test_cfit_override_ignores_debounce():
    """디바운스로 MAINTAIN이 committed 상태여도 CFIT(TTC<3s)는 항상 즉시 override."""
    maintain_response = _make_response("MAINTAIN", None, rac="Low", kill_chain_stage=None)
    _, state = run(maintain_response, None, _CYCLE_CTX)

    ctx_with_ttc = {**_CYCLE_CTX, "obstacle_ttc_s": 1.0}
    nav_response = _make_response("MAINTAIN", "NAVIGATION", rac="Medium", kill_chain_stage=None)
    out, _ = run(nav_response, None, ctx_with_ttc, state)
    assert out["flight_action"] == "ALTITUDE_CHANGE", "CFIT는 디바운스 상태와 무관하게 즉시 적용"


def test_kill_chain_stage_progression_escalates_through_run():
    """(grill-me 라운드3 회귀) RAC=High 유지 + kill_chain_stage 초기→후기 진행 →
    run() 통합 경로에서도 디바운스 없이 즉시 POSTURE_ELEVATE→RTL 반영."""
    early_response = _make_response(
        "POSTURE_ELEVATE", "PHYSICAL", rac="High", kill_chain_stage="초기",
        primary_threat_event="T3",
    )
    out0, state = run(early_response, {"bearing_deg": 45.0}, _CYCLE_CTX)
    assert out0["flight_action"] == "POSTURE_ELEVATE"

    late_response = _make_response(
        "RTL", "PHYSICAL", rac="High", kill_chain_stage="후기",
        primary_threat_event="T3",
    )
    out1, state = run(late_response, {"bearing_deg": 45.0}, _CYCLE_CTX, state)
    assert out1["flight_action"] == "RTL", "RAC_ORDER 불변이어도 kill_chain_stage 진행은 즉시 반영"


def test_primary_threat_event_change_bypasses_debounce_hold_through_run():
    """(grill-me 라운드3 회귀) 완화 디바운스 보류 중 새 threat_event 등장 시 즉시 반영."""
    rtl_response = _make_response(
        "RTL", "PHYSICAL", rac="High", kill_chain_stage="후기", primary_threat_event="T3",
    )
    _, state = run(rtl_response, {"bearing_deg": 45.0}, _CYCLE_CTX)

    maintain_response = _make_response(
        "MAINTAIN", None, rac="Low", kill_chain_stage=None, primary_threat_event="T3",
    )
    out1, state = run(maintain_response, None, _CYCLE_CTX, state)
    assert out1["flight_action"] == "RTL", "같은 threat_event(T3) 완화 1사이클차 — 아직 보류"

    new_threat_response = _make_response(
        "MAINTAIN", None, rac="Low", kill_chain_stage=None, primary_threat_event="T1",
    )
    out2, state = run(new_threat_response, None, _CYCLE_CTX, state)
    assert out2["flight_action"] == "MAINTAIN", "새 threat_event(T1) 등장 → 디바운스 없이 즉시 반영"
