"""임무 결과 예측 모델(로지스틱) — 코퍼스 피처 → P(성공) (4번째 실 ML).

순수 numpy 모델이라 결정론 검증. conftest.py 가 infra/log 를 sys.path 로 임포트.
"""

import pytest

pytest.importorskip("numpy")  # ml extra 미설치 CI 에서는 학습 경로 건너뜀

from outcome_model import OutcomePredictor, fit_outcome_predictor


def _rec(mc, defcon, conf, outcome, threat="T3"):
    return {
        "mission_context": mc,
        "posture": {"defcon": defcon, "watchcon": defcon, "infocon": defcon},
        "threat_event": threat,
        "confidence": conf,
        "outcome": outcome,
    }


def test_insufficient_samples_not_fitted():
    p = fit_outcome_predictor([_rec("정찰", 5, 0.9, "rtb_success")] * 4)
    assert not p.fitted
    assert p.predict(_rec("정찰", 5, 0.9, "rtb_success")) is None


def test_learns_separable_success_pattern():
    # 안전 프로필(defcon5, conf0.9, 정찰) → 성공, 위험(defcon1, conf0.4, 타격) → 실패.
    recs = [_rec("정찰", 5, 0.9, "rtb_success") for _ in range(8)]
    recs += [_rec("타격", 1, 0.4, "lost", threat="T4") for _ in range(8)]
    p = fit_outcome_predictor(recs)
    assert p.fitted
    p_safe = p.predict(_rec("정찰", 5, 0.9, "rtb_success"))
    p_danger = p.predict(_rec("타격", 1, 0.4, "lost", threat="T4"))
    assert p_safe > 0.6, f"안전 프로필 성공확률 낮음: {p_safe}"
    assert p_danger < 0.4, f"위험 프로필 성공확률 높음: {p_danger}"
    assert p_safe > p_danger


def test_prediction_in_unit_range():
    recs = [_rec("정찰", 4, 0.8, "rtb_success") for _ in range(5)]
    recs += [_rec("타격", 2, 0.5, "lost") for _ in range(5)]
    p = fit_outcome_predictor(recs)
    val = p.predict(_rec("호송", 3, 0.7, "rtb_success"))
    assert val is not None and 0.0 <= val <= 1.0


def test_unknown_outcomes_excluded():
    assert not fit_outcome_predictor([_rec("정찰", 5, 0.9, "pending_unknown")] * 12).fitted


def test_featureless_records_stay_unfitted():
    # outcome 만 있고 METT+TC 피처 전무 → 절편-only 학습 방지, 미학습 유지.
    recs = [{"outcome": "rtb_success"} for _ in range(6)]
    recs += [{"outcome": "lost"} for _ in range(6)]
    p = fit_outcome_predictor(recs)
    assert not p.fitted
    assert p.predict({}) is None


def test_fitted_predictor_none_on_featureless_input():
    # 학습된 예측기라도 피처 없는 레코드는 무신호 → None(오도성 advisory 방지).
    recs = [_rec("정찰", 5, 0.9, "rtb_success") for _ in range(8)]
    recs += [_rec("타격", 1, 0.4, "lost") for _ in range(8)]
    p = fit_outcome_predictor(recs)
    assert p.fitted
    assert p.predict({}) is None
    assert p.predict({"outcome": "lost"}) is None


def test_unfitted_predict_none():
    assert OutcomePredictor(None).predict({"posture": {"defcon": 3}}) is None
