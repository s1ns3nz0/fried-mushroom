"""link_loss — C2 통신두절 failsafe 타임라인 advisory 검증.

순수 관찰자(cross-cycle)라 결정론 검증. link_status(03) 상태 어휘를 데이터 계약으로 소비.
"""

from onboard.link_loss import assess_link_loss


def _win(*states):
    """상태 시퀀스(오래된→최신)를 link_status ChannelOutput 유사 dict 윈도우로."""
    return [{"channel": "link_status", "state": s} for s in states]


def test_empty_window_unknown():
    r = assess_link_loss([])
    assert r["assessable"] is False
    assert r["recommended_action"] == "UNKNOWN"


def test_normal_link_continue():
    r = assess_link_loss(_win("anomaly", "anomaly", "normal"))
    assert r["recommended_action"] == "CONTINUE"
    assert r["outage_streak"] == 0  # 재획득 → 과거 두절 무관


def test_degraded_only_monitors():
    r = assess_link_loss(_win("normal", "degraded"))
    assert r["recommended_action"] == "MONITOR"
    assert r["outage_streak"] == 0


def test_short_outage_monitor():
    # 두절 2s (< hold 3s) → MONITOR.
    r = assess_link_loss(_win("normal", "anomaly", "anomaly"), cycle_interval_s=1.0)
    assert r["recommended_action"] == "MONITOR"
    assert r["outage_streak"] == 2
    assert r["outage_seconds"] == 2.0


def test_hold_threshold():
    r = assess_link_loss(_win(*(["anomaly"] * 4)), cycle_interval_s=1.0)  # 4s ≥ hold 3s, < rtl 10s
    assert r["recommended_action"] == "HOLD"


def test_rtl_threshold():
    r = assess_link_loss(_win(*(["anomaly"] * 12)), cycle_interval_s=1.0)  # 12s ≥ rtl 10s
    assert r["recommended_action"] == "RTL"


def test_land_threshold():
    r = assess_link_loss(_win(*(["anomaly"] * 40)), cycle_interval_s=1.0)  # 40s ≥ land 30s
    assert r["recommended_action"] == "LAND"


def test_streak_counts_only_trailing():
    # 과거 두절 뒤 열화 회복 → 말단 스트릭만 계산(두절 1회).
    r = assess_link_loss(_win("anomaly", "anomaly", "degraded", "anomaly"), cycle_interval_s=2.0)
    assert r["outage_streak"] == 1
    assert r["outage_seconds"] == 2.0


def test_cycle_interval_scales_timeline():
    # interval 5s × 2 두절 = 10s ≥ rtl 10s → RTL.
    r = assess_link_loss(_win("anomaly", "anomaly"), cycle_interval_s=5.0)
    assert r["recommended_action"] == "RTL"


def test_string_window_accepted():
    r = assess_link_loss(["normal", "anomaly", "anomaly", "anomaly"], cycle_interval_s=1.0, hold_s=2.0)
    assert r["recommended_action"] == "HOLD"


def test_advisory_only_flag_and_no_mutation():
    win = _win("anomaly", "anomaly")
    before = [dict(e) for e in win]
    r = assess_link_loss(win)
    assert r["advisory_only"] is True
    assert win == before  # 입력 불변
