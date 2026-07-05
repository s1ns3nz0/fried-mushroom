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


# ── #410: 가변 cadence 실경과 합산 ────────────────────────────────────────────


def test_variable_cadence_sums_actual_seconds():
    """가변 cadence: streak 각 사이클의 실경과를 합산한다 (#410 핵심).

    [0s, 1s, 11s] 두절 3사이클 → sum=12s → RTL(≥10s).
    스칼라 폴백(11×3=33s)이면 LAND(≥30s) 오에스컬레이션 — 이 테스트가 그걸 막는다.
    """
    r = assess_link_loss(_lost(3), cycle_seconds=[0.0, 1.0, 11.0])
    assert r["recommended_action"] == "RTL", f"RTL 예상(sum=12s), got {r['recommended_action']}"
    assert abs(r["outage_seconds"] - 12.0) < 0.01, f"12.0s 예상, got {r['outage_seconds']}"


def test_variable_cadence_partial_streak_sums_trailing_only():
    """cycle_seconds: 말단 두절 스트릭만 합산 — 앞 정상 사이클은 제외."""
    # [normal, lost, lost]: streak=2, cycle_seconds[-2:] = [1.0, 11.0] → sum=12s ≥ rtl=10s
    r = assess_link_loss(
        _win("normal") + _lost(2),
        cycle_seconds=[5.0, 1.0, 11.0],
    )
    assert r["recommended_action"] == "RTL"
    assert abs(r["outage_seconds"] - 12.0) < 0.01


def test_cycle_seconds_none_falls_back_to_scalar():
    """cycle_seconds=None 이면 기존 cycle_interval_s 스칼라 동작 유지 (backward-compat)."""
    r = assess_link_loss(_lost(3), cycle_interval_s=11.0, cycle_seconds=None)
    assert r["outage_seconds"] == 33.0
    assert r["recommended_action"] == "LAND"


def test_cycle_seconds_empty_falls_back_to_scalar():
    """cycle_seconds=[] 이면 스칼라 폴백."""
    r = assess_link_loss(_lost(3), cycle_interval_s=1.0, cycle_seconds=[])
    assert r["outage_seconds"] == 3.0


def test_cycle_seconds_length_mismatch_falls_back_to_scalar():
    # codex P2: cycle_seconds 가 window 보다 짧으면(resume 시 window 만 seed) 과소집계 금지 —
    # 스칼라 폴백으로 full streak 카운트. 4개 seconds 로 12 두절 윈도우 → 12*1.0 = RTL.
    win = _lost(12)
    r = assess_link_loss(win, cycle_interval_s=1.0, cycle_seconds=[0.1, 0.1, 0.1, 0.1])
    assert r["recommended_action"] == "RTL"
    assert r["outage_seconds"] == 12.0
