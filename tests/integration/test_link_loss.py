"""link_loss — C2 통신두절 failsafe 타임라인 advisory 검증.

순수 관찰자(cross-cycle)라 결정론 검증. link_status(03) 상태 어휘를 데이터 계약으로 소비.
실질두절 판정은 payload 물리 신호(근-전손 패킷손실 / 마진 소실) 기준 — anomaly(열화-존재)와 구분.
"""

from onboard.link_loss import assess_link_loss


def _win(*states):
    """상태 시퀀스(오래된→최신) → link_status ChannelOutput 유사 dict. 링크 '존재'(두절 아님)."""
    return [{"channel": "link_status", "state": s} for s in states]


def _lost(n, *, state="anomaly"):
    """n 사이클 실질두절(근-전손 패킷손실 payload) 윈도우 조각."""
    return [{"channel": "link_status", "state": state, "payload": {"packet_loss_rate": 1.0}}
            for _ in range(n)]


def test_empty_window_unknown():
    r = assess_link_loss([])
    assert r["assessable"] is False
    assert r["recommended_action"] == "UNKNOWN"


def test_normal_link_continue():
    r = assess_link_loss(_lost(2) + _win("normal"))
    assert r["recommended_action"] == "CONTINUE"
    assert r["outage_streak"] == 0  # 재획득 → 과거 두절 무관


def test_anomaly_present_not_outage():
    # 회귀(codex #372 P2): anomaly(열화-존재, 두절 payload 없음)는 failsafe 를 개시하지 않아야.
    r = assess_link_loss(_win("normal", "anomaly", "anomaly", "anomaly"), cycle_interval_s=1.0)
    assert r["recommended_action"] == "MONITOR"
    assert r["outage_streak"] == 0


def test_degraded_only_monitors():
    r = assess_link_loss(_win("normal", "degraded"))
    assert r["recommended_action"] == "MONITOR"
    assert r["outage_streak"] == 0


def test_short_outage_monitor():
    # 실질두절 2s (< hold 3s) → MONITOR.
    r = assess_link_loss(_win("normal") + _lost(2), cycle_interval_s=1.0)
    assert r["recommended_action"] == "MONITOR"
    assert r["outage_streak"] == 2
    assert r["outage_seconds"] == 2.0


def test_hold_threshold():
    r = assess_link_loss(_lost(4), cycle_interval_s=1.0)  # 4s ≥ hold 3s, < rtl 10s
    assert r["recommended_action"] == "HOLD"


def test_rtl_threshold():
    r = assess_link_loss(_lost(12), cycle_interval_s=1.0)  # 12s ≥ rtl 10s
    assert r["recommended_action"] == "RTL"


def test_land_threshold():
    r = assess_link_loss(_lost(40), cycle_interval_s=1.0)  # 40s ≥ land 30s
    assert r["recommended_action"] == "LAND"


def test_streak_counts_only_trailing():
    # 과거 두절 뒤 열화 회복 → 말단 스트릭만 계산(두절 1회).
    r = assess_link_loss(_lost(2) + _win("degraded") + _lost(1), cycle_interval_s=2.0)
    assert r["outage_streak"] == 1
    assert r["outage_seconds"] == 2.0


def test_cycle_interval_scales_timeline():
    # interval 5s × 2 두절 = 10s ≥ rtl 10s → RTL.
    r = assess_link_loss(_lost(2), cycle_interval_s=5.0)
    assert r["recommended_action"] == "RTL"


def test_margin_collapse_is_outage():
    # RSSI ≤ 노이즈플로어(마진 0) → 신호 매몰 = 실질두절.
    win = [{"channel": "link_status", "state": "anomaly",
            "payload": {"rssi_dbm": -95.0, "noise_floor_dbm": -95.0}} for _ in range(4)]
    r = assess_link_loss(win, cycle_interval_s=1.0, hold_s=2.0)
    assert r["recommended_action"] == "HOLD"
    assert r["outage_streak"] == 4


def test_explicit_lost_token_accepted():
    r = assess_link_loss(["normal", "lost", "lost", "lost"], cycle_interval_s=1.0, hold_s=2.0)
    assert r["recommended_action"] == "HOLD"


def test_advisory_only_flag_and_no_mutation():
    win = _lost(2)
    before = [dict(e) for e in win]
    r = assess_link_loss(win)
    assert r["advisory_only"] is True
    assert win == before  # 입력 불변
