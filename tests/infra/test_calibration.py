"""confidence 캘리브레이션 모델(isotonic/PAV) — 코퍼스 outcome 기반 (3번째 실 ML).

순수 Python 모델이라 결정론 검증(외부 의존 없음). conftest.py 가 infra/log 를 sys.path 로 임포트.
"""

from calibration import (
    ConfidenceCalibrator,
    _pav_isotonic,
    fit_calibrator,
    fit_calibrators_by_threat,
)


def _rec(conf, outcome, threat="T3"):
    return {"confidence": conf, "outcome": outcome, "threat_event": threat}


def test_per_threat_calibrators_separate_curves():
    # T3 는 과신(0.9→실제 0.4), T2 는 정확(0.9→0.9). 위협별 별도 곡선.
    recs = (
        [_rec(0.9, "rtb_success", "T3")] * 4 + [_rec(0.9, "lost", "T3")] * 6
        + [_rec(0.9, "rtb_success", "T2")] * 9 + [_rec(0.9, "lost", "T2")] * 1
    )
    cals = fit_calibrators_by_threat(recs)
    assert set(cals) == {"T3", "T2"}
    assert cals["T3"].calibrate(0.9) == 0.4
    assert cals["T2"].calibrate(0.9) == 0.9


def test_insufficient_samples_not_fitted():
    c = fit_calibrator([_rec(0.9, "rtb_success")] * 3)  # < _MIN_SAMPLES
    assert not c.fitted
    assert c.calibrate(0.9) is None


def test_overconfident_calibrated_down_to_empirical_rate():
    # 전부 conf 0.9 인데 실제 3/6 성공 → 캘리브레이션 0.5 (과신 보정).
    recs = [_rec(0.9, "rtb_success")] * 3 + [_rec(0.9, "lost")] * 3
    c = fit_calibrator(recs)
    assert c.fitted
    assert abs(c.calibrate(0.9) - 0.5) < 1e-6


def test_monotone_mapping_low_to_high():
    recs = [
        _rec(0.30, "lost"), _rec(0.40, "lost"), _rec(0.50, "lost"),
        _rec(0.60, "rtb_success"), _rec(0.70, "rtb_success"), _rec(0.80, "rtb_success"),
    ]
    c = fit_calibrator(recs)
    assert c.calibrate(0.30) == 0.0  # 낮은 conf → 낮은 성공확률
    assert c.calibrate(0.80) == 1.0  # 높은 conf → 높은 성공확률
    assert c.calibrate(0.35) <= c.calibrate(0.75)  # 단조


def test_calibrate_is_non_decreasing():
    recs = [_rec(c, o) for c, o in [
        (0.2, "lost"), (0.3, "rtb_success"), (0.4, "lost"),
        (0.6, "rtb_success"), (0.7, "lost"), (0.9, "rtb_success"),
    ]]
    c = fit_calibrator(recs)
    vals = [c.calibrate(x) for x in (0.1, 0.25, 0.45, 0.65, 0.85, 0.99)]
    assert vals == sorted(vals), f"단조 비감소 위반: {vals}"


def test_pav_pools_monotonicity_violation():
    # 비단조 입력 [1,0,1] → PAV 가 단조 비감소로 pooling. points=(x, 라벨합, 가중치).
    bp = _pav_isotonic([(0.2, 1.0, 1.0), (0.4, 0.0, 1.0), (0.6, 1.0, 1.0)])
    vals = [v for _, v in bp]
    assert vals == sorted(vals)


def test_duplicate_confidence_order_independent():
    # 동일 conf 0.9, 성공2/실패3 → 순서 무관하게 경험률 0.4.
    a = [_rec(0.9, "rtb_success")] * 2 + [_rec(0.9, "lost")] * 3
    b = [_rec(0.9, "lost")] * 3 + [_rec(0.9, "rtb_success")] * 2
    ca, cb = fit_calibrator(a), fit_calibrator(b)
    assert ca.calibrate(0.9) == cb.calibrate(0.9) == 0.4


def test_unknown_outcomes_excluded():
    # outcome 미분류(pending) → 표본 0 → 미학습.
    assert not fit_calibrator([_rec(0.9, "pending_unknown")] * 10).fitted


def test_missing_confidence_excluded():
    recs = [{"outcome": "rtb_success", "threat_event": "T3"}] * 10  # confidence 없음
    assert not fit_calibrator(recs).fitted


def test_calibrator_none_breakpoints_returns_none():
    assert ConfidenceCalibrator(None).calibrate(0.8) is None
