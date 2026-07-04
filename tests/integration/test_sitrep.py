"""build_sitrep — 운용자 상황판단 리포트: 현재 근거(explain) + 궤적(trend) → 주의수준.

현재 사이클의 결정 근거와 최근 궤적 조기경보를 융합해 운용자가 한눈에 볼 **주의수준**
(ROUTINE/MONITOR/ALERT/ACT)과 헤드라인·권고를 만든다. CRITICAL: advisory 만 — 결정을
변경하지 않고 입력을 변이하지 않는다.
"""

import copy

from onboard.sitrep import build_sitrep


def _cyc(threat_event=None, confidence=None, kill_chain_stage=None, rac="Low",
         flight_action="MAINTAIN"):
    primary = None
    if threat_event:
        primary = {"threat_event": threat_event, "confidence": confidence,
                   "kill_chain_stage": kill_chain_stage}
    cands = [] if not primary else [{"threat_event": threat_event, "confidence": confidence,
                                     "kill_chain_stage": kill_chain_stage, "rac": rac,
                                     "priority_rank": 0}]
    return {
        "abstraction": {"channels": [{"channel": "link_status", "state": "normal"}]},
        "threat": {"primary": primary, "candidates": cands},
        "risk": {"candidates": cands, "ambient_rac": rac},
        "response": {"rac": rac, "kill_chain_stage": kill_chain_stage,
                     "primary_threat_event": threat_event, "flight_action": flight_action},
        "flight_plan": {"flight_action": flight_action, "replan_scope": "NONE",
                        "reroute_anchor": None, "target_bearing_deg": None,
                        "altitude_delta_m": 0, "speed_mode": "NORMAL", "route": []},
    }


_LEVELS = {"ROUTINE": 0, "MONITOR": 1, "ALERT": 2, "ACT": 3}


# ── 기본 계약 ────────────────────────────────────────────────────────────────

def test_empty_is_routine_graceful():
    out = build_sitrep([])
    assert out["attention_level"] == "ROUTINE"
    assert out["advisory_only"] is True


def test_advisory_only_and_no_mutation():
    seq = [_cyc("T3", 0.7, "초기", "Serious"), _cyc("T3", 0.9, "중기", "High", "RTL")]
    snap = copy.deepcopy(seq)
    out = build_sitrep(seq)
    assert out["advisory_only"] is True
    assert seq == snap


def test_structure_includes_current_and_trend():
    out = build_sitrep([_cyc("T3", 0.8, "초기", "Serious")])
    assert out["current"]["flight_action"] is not None  # explain 결과 내장
    assert "level" in out["trend"]                        # trend 결과 내장
    assert out["attention_level"] in _LEVELS


# ── 주의수준 융합 ────────────────────────────────────────────────────────────

def test_no_threat_is_routine():
    out = build_sitrep([_cyc(), _cyc()])
    assert out["attention_level"] == "ROUTINE"


def test_low_stable_threat_is_monitor():
    seq = [_cyc("T6", 0.5, "초기", "Medium"), _cyc("T6", 0.5, "초기", "Medium")]
    out = build_sitrep(seq)
    assert out["attention_level"] == "MONITOR"


def test_severe_threat_with_action_is_act():
    seq = [_cyc("T3", 0.9, "후기", "High", "RTL"), _cyc("T3", 0.9, "후기", "High", "RTL")]
    out = build_sitrep(seq)
    assert out["attention_level"] == "ACT"


def test_escalating_trend_at_least_alert():
    seq = [_cyc("T3", 0.6, "초기", "Medium"),
           _cyc("T3", 0.8, "중기", "Serious"),
           _cyc("T3", 0.92, "후기", "High", "RTL")]
    out = build_sitrep(seq)
    assert _LEVELS[out["attention_level"]] >= _LEVELS["ALERT"]  # 악화 궤적 → 최소 ALERT
    assert out["trend"]["escalating"] is True


def test_cleared_threat_returns_routine():
    seq = [_cyc("T3", 0.9, "후기", "High", "RTL"), _cyc(), _cyc()]
    out = build_sitrep(seq)
    assert out["attention_level"] == "ROUTINE"  # 최신 무위협 → 해소


# ── 헤드라인 ─────────────────────────────────────────────────────────────────

def test_headline_mentions_level_and_context():
    seq = [_cyc("T3", 0.9, "후기", "High", "RTL"), _cyc("T3", 0.9, "후기", "High", "RTL")]
    out = build_sitrep(seq)
    assert out["attention_level"] in out["headline"]
    assert "T3" in out["headline"]
    assert out["recommendation"]


def test_window_forwarded_to_trend():
    seq = [_cyc("T3", 0.9, "후기", "High", "RTL")] + [_cyc() for _ in range(4)]
    out = build_sitrep(seq, window=2)  # 최근 2 = 무위협
    assert out["attention_level"] == "ROUTINE"


def test_headline_threat_aligned_with_decision():
    """04 threat.primary 와 05/06 결정 primary 가 다르면 — 헤드라인은 결정 primary 기준."""
    r = _cyc("T3", 0.8, "중기", "Serious", "REROUTE")
    # 04 는 T5 를 primary 로, 05/06(결정)은 T3 를 primary 로 (RAC/action 은 T3 것)
    r["threat"]["primary"] = {"threat_event": "T5", "confidence": 0.6, "kill_chain_stage": "초기"}
    out = build_sitrep([r])
    assert out["primary_threat_event"] == "T3"       # 결정 primary
    assert "T3" in out["headline"] and "T5" not in out["headline"]
