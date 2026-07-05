"""failsafe_arbiter — 온보드 안전 3축 failsafe 통합 중재 검증.

각 축 advisory 의 출력 report dict 만 소비(모듈 import 없음). 합성 report 로 결정론 검증.
"""

from onboard.failsafe_arbiter import assess_failsafe


def _rep(action, assessable=True):
    return {"recommended_action": action, "assessable": assessable, "advisory_only": True}


def test_empty_unknown():
    r = assess_failsafe({})
    assert r["assessable"] is False
    assert r["recommended_action"] == "UNKNOWN"
    assert r["driving_axes"] == []


def test_none_input_unknown():
    assert assess_failsafe(None)["recommended_action"] == "UNKNOWN"


def test_all_continue():
    r = assess_failsafe({"energy": _rep("CONTINUE"), "comms": _rep("CONTINUE"), "nav": _rep("CONTINUE")})
    assert r["recommended_action"] == "CONTINUE"
    assert r["severity"] == 0
    assert r["driving_axes"] == []


def test_most_conservative_wins():
    # energy RTL(3) vs comms MONITOR(1) vs nav CONTINUE(0) → RTL.
    r = assess_failsafe({"energy": _rep("RTL"), "comms": _rep("MONITOR"), "nav": _rep("CONTINUE")})
    assert r["recommended_action"] == "RTL"
    assert r["severity"] == 3
    assert r["driving_axes"] == ["energy"]


def test_unrecognized_action_alone_is_unknown_not_continue():
    # codex P2: 미인식 action 이 유일 기여면 CONTINUE 로 하향하지 않고 UNKNOWN(불가지).
    r = assess_failsafe({"comms": _rep("DITCH")})
    assert r["recommended_action"] == "UNKNOWN"
    assert r["assessable"] is False
    assert r["contributions"] == {"comms": "DITCH"}


def test_unrecognized_with_calm_recognized_is_unknown():
    # 인식된 축이 전부 CONTINUE(sev0)이고 미인식 action 존재 → 하향 금지, UNKNOWN.
    r = assess_failsafe({"nav": _rep("CONTINUE"), "comms": _rep("FOOBAR")})
    assert r["recommended_action"] == "UNKNOWN"
    assert r["assessable"] is False


def test_unrecognized_does_not_downgrade_recognized_escalation():
    # 인식된 에스컬레이션(LAND)은 미인식 action 이 있어도 지배, 미인식은 병기.
    r = assess_failsafe({"nav": _rep("LAND"), "comms": _rep("DITCH")})
    assert r["recommended_action"] == "LAND"
    assert r["severity"] == 4
    assert r["contributions"]["comms"] == "DITCH"


def test_land_dominates():
    r = assess_failsafe({"energy": _rep("RTL"), "comms": _rep("LAND"), "nav": _rep("RTL")})
    assert r["recommended_action"] == "LAND"
    assert r["severity"] == 4
    assert r["driving_axes"] == ["comms"]


def test_tie_break_nav_over_comms():
    # comms HOLD(2) vs nav DR_HOLD(2) 동률 → nav 우선.
    r = assess_failsafe({"comms": _rep("HOLD"), "nav": _rep("DR_HOLD")})
    assert r["severity"] == 2
    assert r["recommended_action"] == "DR_HOLD"
    assert r["driving_axes"] == ["nav", "comms"]


def test_unknown_axis_excluded():
    # nav UNKNOWN 은 기여 제외 → comms MONITOR 지배.
    r = assess_failsafe({"nav": _rep("UNKNOWN"), "comms": _rep("MONITOR")})
    assert r["recommended_action"] == "MONITOR"
    assert "nav" not in r["contributions"]


def test_non_assessable_excluded():
    r = assess_failsafe({"energy": _rep("RTL", assessable=False), "comms": _rep("MONITOR")})
    assert r["recommended_action"] == "MONITOR"
    assert "energy" not in r["contributions"]


def test_all_axes_unknown_is_unknown():
    r = assess_failsafe({"energy": _rep("UNKNOWN"), "comms": None, "nav": _rep("RTL", assessable=False)})
    assert r["assessable"] is False
    assert r["recommended_action"] == "UNKNOWN"


def test_contributions_reported():
    r = assess_failsafe({"energy": _rep("CONTINUE"), "comms": _rep("HOLD"), "nav": _rep("MONITOR")})
    assert r["contributions"] == {"energy": "CONTINUE", "comms": "HOLD", "nav": "MONITOR"}
    assert r["advisory_only"] is True


def test_input_not_mutated():
    reports = {"comms": _rep("RTL")}
    before = {"comms": dict(reports["comms"])}
    assess_failsafe(reports)
    assert reports["comms"] == before["comms"]


# ── EW 축 (ew_jamming) 통합 ─────────────────────────────────────────────────


def test_ew_emcon_evade_drives_failsafe():
    # ew EMCON_EVADE(3) vs 나머지 저심각 → EW 가 지배, EMCON_EVADE 그대로 방출.
    r = assess_failsafe({"energy": _rep("CONTINUE"), "comms": _rep("MONITOR"),
                         "nav": _rep("CONTINUE"), "ew": _rep("EMCON_EVADE")})
    assert r["recommended_action"] == "EMCON_EVADE"
    assert r["severity"] == 3
    assert r["driving_axes"] == ["ew"]


def test_ew_monitor_ranks_low():
    # ew MONITOR(1) vs nav DR_HOLD(2) → nav 지배.
    r = assess_failsafe({"ew": _rep("MONITOR"), "nav": _rep("DR_HOLD")})
    assert r["recommended_action"] == "DR_HOLD"
    assert r["severity"] == 2


def test_emcon_evade_ties_rtl_precedence_order():
    # ew EMCON_EVADE(3) 와 energy RTL(3) 동률 → 축 우선순위 ew > energy → EMCON_EVADE.
    r = assess_failsafe({"energy": _rep("RTL"), "ew": _rep("EMCON_EVADE")})
    assert r["severity"] == 3
    assert r["recommended_action"] == "EMCON_EVADE"
    assert r["driving_axes"] == ["ew", "energy"]


def test_nav_outranks_ew_on_tie():
    # nav RTL(3) 와 ew EMCON_EVADE(3) 동률 → nav 우선(가장 근본적) → RTL.
    r = assess_failsafe({"nav": _rep("RTL"), "ew": _rep("EMCON_EVADE")})
    assert r["severity"] == 3
    assert r["recommended_action"] == "RTL"
    assert r["driving_axes"] == ["nav", "ew"]


def test_land_still_dominates_emcon_evade():
    r = assess_failsafe({"ew": _rep("EMCON_EVADE"), "comms": _rep("LAND")})
    assert r["recommended_action"] == "LAND"
    assert r["severity"] == 4
