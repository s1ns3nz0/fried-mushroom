"""assess_threat_trend — 사이클 시퀀스의 위협 궤적 조기경보 advisory.

파이프라인은 무상태(ADR-004) — 사이클마다 독립 판정한다. 이 모듈은 그 위에 얹는 관찰자로,
최근 N 사이클 결과의 궤적(RAC 악화·킬체인 진행·확신도 상승·위협 지속)을 보고 조기경보를
낸다. CRITICAL: advisory 만 — 어떤 사이클 결과도 변경하지 않고 입력을 변이하지 않는다.
"""

import copy

import pytest

from onboard.trend import assess_threat_trend


def _cyc(threat_event=None, confidence=None, kill_chain_stage=None, rac="Low",
         flight_action="MAINTAIN"):
    """사이클 결과의 궤적 관련 부분집합."""
    primary = None
    if threat_event:
        primary = {"threat_event": threat_event, "confidence": confidence,
                   "kill_chain_stage": kill_chain_stage}
    return {
        "threat": {"primary": primary, "candidates": [] if not primary else [{"rac": rac}]},
        "risk": {"candidates": [] if not primary else [{"rac": rac, "priority_rank": 0}],
                 "ambient_rac": rac},
        "response": {"rac": rac, "kill_chain_stage": kill_chain_stage,
                     "primary_threat_event": threat_event, "flight_action": flight_action},
        "flight_plan": {"flight_action": flight_action},
    }


# ── 기본 계약 ────────────────────────────────────────────────────────────────

def test_empty_and_single_cycle_no_escalation():
    assert assess_threat_trend([])["escalating"] is False
    out = assess_threat_trend([_cyc("T3", 0.8, "초기", "Serious")])
    assert out["escalating"] is False   # 단일 사이클은 궤적 판단 불가
    assert out["advisory_only"] is True


def test_advisory_only_and_no_mutation():
    seq = [_cyc("T3", 0.7, "초기", "Serious"), _cyc("T3", 0.85, "중기", "High")]
    snap = copy.deepcopy(seq)
    out = assess_threat_trend(seq)
    assert out["advisory_only"] is True
    assert seq == snap  # 입력 무변이 (SCC-1)


# ── 악화 감지 ────────────────────────────────────────────────────────────────

def test_rac_escalation_detected():
    seq = [_cyc("T3", 0.6, "초기", "Medium"),
           _cyc("T3", 0.75, "초기", "Serious"),
           _cyc("T3", 0.9, "중기", "High")]
    out = assess_threat_trend(seq)
    assert out["escalating"] is True
    assert "rac_escalating" in out["signals"]
    assert out["rac_from"] == "Medium" and out["rac_to"] == "High"
    assert out["level"] in ("warning", "critical")


def test_kill_chain_advance_detected():
    seq = [_cyc("T3", 0.8, "초기", "Serious"),
           _cyc("T3", 0.82, "중기", "Serious"),
           _cyc("T3", 0.83, "후기", "Serious")]
    out = assess_threat_trend(seq)
    assert out["escalating"] is True
    assert "kill_chain_advancing" in out["signals"]


def test_confidence_rising_on_persistent_threat():
    seq = [_cyc("T3", 0.55, "초기", "Serious"),
           _cyc("T3", 0.70, "초기", "Serious"),
           _cyc("T3", 0.88, "초기", "Serious")]
    out = assess_threat_trend(seq)
    assert "confidence_rising" in out["signals"]
    assert "persistent_threat" in out["signals"]


# ── 안정/완화 ────────────────────────────────────────────────────────────────

def test_stable_threat_is_watch_not_escalating():
    seq = [_cyc("T3", 0.8, "초기", "Serious"), _cyc("T3", 0.8, "초기", "Serious")]
    out = assess_threat_trend(seq)
    assert out["escalating"] is False
    assert out["level"] == "watch"


def test_no_threat_window_is_level_none():
    seq = [_cyc(), _cyc(), _cyc()]
    out = assess_threat_trend(seq)
    assert out["level"] == "none"
    assert out["escalating"] is False


def test_deescalation_not_flagged_escalating():
    seq = [_cyc("T3", 0.9, "중기", "High"), _cyc("T3", 0.7, "초기", "Serious")]
    out = assess_threat_trend(seq)
    assert "rac_escalating" not in out["signals"]
    assert out["escalating"] is False


# ── 윈도우 / 임계 ────────────────────────────────────────────────────────────

def test_window_limits_to_recent_cycles():
    seq = [_cyc("T3", 0.9, "후기", "High")] + [_cyc() for _ in range(5)]  # 옛날 위협, 최근 무위협
    out = assess_threat_trend(seq, window=3)  # 최근 3개만 → 무위협
    assert out["level"] == "none"


def test_critical_level_on_high_rac_escalation():
    seq = [_cyc("T4", 0.7, "중기", "Serious"), _cyc("T4", 0.9, "후기", "High")]
    out = assess_threat_trend(seq)
    assert out["level"] == "critical"  # High 도달 + 악화
    assert out["primary_threat_event"] == "T4"


def test_cleared_threat_ends_window_is_none():
    """최신 사이클이 무위협이면(위협 해소) — 윈도우에 옛 위협 남아도 level=none."""
    seq = [_cyc("T3", 0.9, "후기", "High"), _cyc(), _cyc()]
    out = assess_threat_trend(seq)
    assert out["level"] == "none"
    assert out["escalating"] is False
    assert out["primary_threat_event"] is None
    assert "persistent_threat" not in out["signals"]


def test_reappearing_threat_not_stale_escalation():
    """T3 → T4 → T3: 최신 T3 스트릭은 1사이클 → 옛 T3 와 비교한 stale 악화 금지."""
    seq = [_cyc("T3", 0.6, "초기", "Medium"),
           _cyc("T4", 0.7, "중기", "Serious"),
           _cyc("T3", 0.9, "후기", "High")]
    out = assess_threat_trend(seq)
    assert out["primary_threat_event"] == "T3"
    assert "rac_escalating" not in out["signals"]      # 옛 T3(Medium)와 비교 안 함
    assert "persistent_threat" not in out["signals"]   # 현재 T3 스트릭=1
    assert out["escalating"] is False
