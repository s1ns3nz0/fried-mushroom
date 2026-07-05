"""ew_jamming — EW 광대역 재밍 지속·방위 확정 advisory 검증.

순수 관찰자(cross-cycle)라 결정론 검증. rf_spectrum(03) 출력(state/payload.bearing_deg) 계약 소비.
"""

from onboard.ew_jamming import assess_ew_jamming


def _rf(state, bearing=None):
    return {"channel": "rf_spectrum", "state": state, "payload": {"bearing_deg": bearing}}


def test_empty_unknown():
    r = assess_ew_jamming([])
    assert r["assessable"] is False
    assert r["threat_level"] == "UNKNOWN"


def test_clear_when_normal():
    r = assess_ew_jamming([_rf("anomaly", 90), _rf("normal")])
    assert r["threat_level"] == "CLEAR"
    assert r["recommended_action"] == "CONTINUE"
    assert r["anomaly_streak"] == 0


def test_short_anomaly_monitor():
    r = assess_ew_jamming([_rf("normal"), _rf("anomaly", 90)], cycle_interval_s=1.0)  # 1s < confirm 2s
    assert r["threat_level"] == "MONITOR"
    assert r["anomaly_streak"] == 1


def test_suspected_threshold():
    r = assess_ew_jamming([_rf("anomaly", 90), _rf("anomaly", 92), _rf("anomaly", 88)], cycle_interval_s=1.0)
    # 3s ≥ confirm 2s, < sustained 5s → SUSPECTED.
    assert r["threat_level"] == "JAMMING_SUSPECTED"
    assert r["recommended_action"] == "MONITOR"


def test_confirmed_and_emcon_evade():
    win = [_rf("anomaly", 90 + i * 0.5) for i in range(6)]  # 6s ≥ sustained 5s, 방위 밀집
    r = assess_ew_jamming(win, cycle_interval_s=1.0)
    assert r["threat_level"] == "JAMMING_CONFIRMED"
    assert r["recommended_action"] == "EMCON_EVADE"
    assert r["bearing_stable"] is True
    assert 89.0 <= r["emitter_bearing_deg"] <= 93.0


def test_scattered_bearing_unstable():
    # 방위 산발(0/120/240 …) → 잡음, emitter 방위 미보고.
    win = [_rf("anomaly", b) for b in (0, 120, 240, 60, 300, 180)]
    r = assess_ew_jamming(win, cycle_interval_s=1.0)
    assert r["threat_level"] == "JAMMING_CONFIRMED"  # 지속은 함
    assert r["bearing_stable"] is False
    assert r["emitter_bearing_deg"] is None


def test_bearing_wraparound_stable():
    # 359/1/0/358 … 은 0° 근방 밀집 — 순환평균이 wraparound 를 올바로 처리.
    win = [_rf("anomaly", b) for b in (359, 1, 0, 358, 2, 1)]
    r = assess_ew_jamming(win, cycle_interval_s=1.0)
    assert r["bearing_stable"] is True
    b = r["emitter_bearing_deg"]
    assert b >= 358.0 or b <= 2.0


def test_streak_only_trailing():
    r = assess_ew_jamming([_rf("anomaly", 10), _rf("normal"), _rf("anomaly", 90)], cycle_interval_s=2.0)
    assert r["anomaly_streak"] == 1
    assert r["anomaly_seconds"] == 2.0


def test_missing_bearings_unstable_but_persists():
    win = [_rf("anomaly"), _rf("anomaly"), _rf("anomaly"), _rf("anomaly"), _rf("anomaly")]
    r = assess_ew_jamming(win, cycle_interval_s=1.0)  # 5s → confirmed, 방위 없음
    assert r["threat_level"] == "JAMMING_CONFIRMED"
    assert r["bearing_stable"] is False
    assert r["emitter_bearing_deg"] is None


def test_single_bearing_not_stable():
    # 스트릭 5s 중 방위 표본 1개만 → R=1.0 이라도 안정 선언 금지(cross-cycle 미증명).
    win = [_rf("anomaly"), _rf("anomaly"), _rf("anomaly"), _rf("anomaly"), _rf("anomaly", 90)]
    r = assess_ew_jamming(win, cycle_interval_s=1.0)
    assert r["threat_level"] == "JAMMING_CONFIRMED"
    assert r["bearing_stable"] is False
    assert r["emitter_bearing_deg"] is None


def test_advisory_only_and_no_mutation():
    win = [_rf("anomaly", 90), _rf("anomaly", 90)]
    before = [dict(e) for e in win]
    r = assess_ew_jamming(win)
    assert r["advisory_only"] is True
    assert win == before
