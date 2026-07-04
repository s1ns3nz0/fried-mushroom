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


# ── #410: 가변 cadence 실경과 합산 ────────────────────────────────────────────


def test_variable_cadence_sums_actual_seconds():
    """가변 cadence: streak 각 사이클의 실경과를 합산한다 (#410 핵심).

    [0s, 1s, 8s] 항법상실 3사이클 → sum=9s → RTL(≥8s).
    스칼라 폴백(8×3=24s)이면 LAND(≥20s) 오에스컬레이션.
    """
    r = assess_nav_integrity(_win("anomaly", "anomaly", "anomaly"), cycle_seconds=[0.0, 1.0, 8.0])
    assert r["recommended_action"] == "RTL", f"RTL 예상(sum=9s), got {r['recommended_action']}"
    assert abs(r["untrusted_seconds"] - 9.0) < 0.01, f"9.0s 예상, got {r['untrusted_seconds']}"


def test_variable_cadence_partial_streak_sums_trailing_only():
    """cycle_seconds: 말단 상실 스트릭만 합산 — 앞 정상 사이클 제외."""
    # [normal, anomaly, anomaly]: streak=2, cycle_seconds[-2:] = [1.0, 8.0] → sum=9s ≥ rtl=8s
    r = assess_nav_integrity(
        _win("normal", "anomaly", "anomaly"),
        cycle_seconds=[5.0, 1.0, 8.0],
    )
    assert r["recommended_action"] == "RTL"
    assert abs(r["untrusted_seconds"] - 9.0) < 0.01


def test_cycle_seconds_none_falls_back_to_scalar():
    """cycle_seconds=None 이면 기존 cycle_interval_s 스칼라 동작 유지 (backward-compat)."""
    r = assess_nav_integrity(_win("anomaly", "anomaly", "anomaly"), cycle_interval_s=8.0, cycle_seconds=None)
    assert r["untrusted_seconds"] == 24.0
    assert r["recommended_action"] == "LAND"


def test_cycle_seconds_empty_falls_back_to_scalar():
    """cycle_seconds=[] 이면 스칼라 폴백."""
    r = assess_nav_integrity(_win("anomaly", "anomaly"), cycle_interval_s=1.0, cycle_seconds=[])
    assert r["untrusted_seconds"] == 2.0
