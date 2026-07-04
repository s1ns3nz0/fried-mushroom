"""nav_integrity — GNSS/항법 무결성 저하 failsafe 타임라인 advisory 검증.

순수 관찰자(cross-cycle)라 결정론 검증. position_consistency(03) 상태 어휘를 데이터 계약으로 소비.
"""

from onboard.nav_integrity import assess_nav_integrity


def _win(*states):
    """상태 시퀀스(오래된→최신)를 position_consistency ChannelOutput 유사 dict 윈도우로."""
    return [{"channel": "position_consistency", "state": s} for s in states]


def test_empty_window_unknown():
    r = assess_nav_integrity([])
    assert r["assessable"] is False
    assert r["recommended_action"] == "UNKNOWN"


def test_normal_nav_continue():
    r = assess_nav_integrity(_win("anomaly", "anomaly", "normal"))
    assert r["recommended_action"] == "CONTINUE"
    assert r["untrusted_streak"] == 0
    assert r["dead_reckoning"] is False


def test_degraded_only_monitors():
    r = assess_nav_integrity(_win("normal", "degraded"))
    assert r["recommended_action"] == "MONITOR"
    assert r["untrusted_streak"] == 0
    assert r["dead_reckoning"] is False


def test_short_loss_monitor():
    r = assess_nav_integrity(_win("normal", "anomaly", "anomaly"), cycle_interval_s=1.0)
    assert r["recommended_action"] == "MONITOR"
    assert r["untrusted_streak"] == 2
    assert r["untrusted_seconds"] == 2.0
    assert r["dead_reckoning"] is False


def test_dr_hold_threshold():
    r = assess_nav_integrity(_win(*(["anomaly"] * 4)), cycle_interval_s=1.0)  # 4s ≥ 3s, < 8s
    assert r["recommended_action"] == "DR_HOLD"
    assert r["dead_reckoning"] is True


def test_rtl_threshold():
    r = assess_nav_integrity(_win(*(["anomaly"] * 10)), cycle_interval_s=1.0)  # 10s ≥ 8s
    assert r["recommended_action"] == "RTL"
    assert r["dead_reckoning"] is True


def test_land_threshold():
    r = assess_nav_integrity(_win(*(["anomaly"] * 25)), cycle_interval_s=1.0)  # 25s ≥ 20s
    assert r["recommended_action"] == "LAND"
    assert r["dead_reckoning"] is True


def test_streak_counts_only_trailing():
    # 과거 상실 뒤 degraded 회복 → 말단 스트릭만(상실 1회).
    r = assess_nav_integrity(_win("anomaly", "anomaly", "degraded", "anomaly"), cycle_interval_s=2.0)
    assert r["untrusted_streak"] == 1
    assert r["untrusted_seconds"] == 2.0


def test_cycle_interval_scales_timeline():
    # interval 4s × 2 상실 = 8s ≥ rtl 8s → RTL.
    r = assess_nav_integrity(_win("anomaly", "anomaly"), cycle_interval_s=4.0)
    assert r["recommended_action"] == "RTL"


def test_string_window_accepted():
    r = assess_nav_integrity(["normal", "anomaly", "anomaly", "anomaly"], cycle_interval_s=1.0, dr_hold_s=2.0)
    assert r["recommended_action"] == "DR_HOLD"


def test_advisory_only_flag_and_no_mutation():
    win = _win("anomaly", "anomaly")
    before = [dict(e) for e in win]
    r = assess_nav_integrity(win)
    assert r["advisory_only"] is True
    assert win == before
