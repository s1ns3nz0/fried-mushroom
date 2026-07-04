"""위협 사전확률 모델(범주형 나이브베이즈) — 맥락 → P(threat_event) (6번째 실 ML).

순수 파이썬 zero-dep 모델이라 결정론 검증. conftest.py 가 infra/log 를 sys.path 로.
"""

from threat_prior import ThreatPrior, fit_threat_prior


def _rec(mc, defcon, threat, corridor="west"):
    return {
        "mission_context": mc,
        "corridor_region": corridor,
        "posture": {"defcon": defcon, "watchcon": defcon, "infocon": defcon},
        "threat_event": threat,
    }


def test_insufficient_samples_not_fitted():
    m = fit_threat_prior([_rec("정찰", 3, "T3")] * 4)
    assert not m.fitted
    assert m.predict(_rec("정찰", 3, "T3")) is None


def test_learns_context_to_threat_association():
    # 정찰+낮은 defcon → T3 우세, 타격+높은 defcon → T7 우세.
    recs = [_rec("정찰", 2, "T3") for _ in range(8)]
    recs += [_rec("타격", 5, "T7", corridor="east") for _ in range(8)]
    m = fit_threat_prior(recs)
    assert m.fitted
    top_recon = m.predict(_rec("정찰", 2, "T3"))[0]
    top_strike = m.predict(_rec("타격", 5, "T7", corridor="east"))[0]
    assert top_recon[0] == "T3"
    assert top_strike[0] == "T7"


def test_probs_normalized_and_sorted():
    recs = [_rec("정찰", 2, "T3") for _ in range(6)] + [_rec("타격", 5, "T7") for _ in range(6)]
    m = fit_threat_prior(recs)
    out = m.predict(_rec("정찰", 3, "T3"))
    probs = [p for _, p in out]
    assert abs(sum(probs) - 1.0) < 1e-6
    assert probs == sorted(probs, reverse=True)
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_partial_context_still_predicts():
    # 피처 일부만 있어도(mission_context 만) 결측은 생략하고 예측.
    recs = [_rec("정찰", 2, "T3") for _ in range(8)] + [_rec("타격", 5, "T7") for _ in range(8)]
    m = fit_threat_prior(recs)
    out = m.predict({"mission_context": "정찰"})
    assert out is not None and out[0][0] == "T3"


def test_unlabeled_records_excluded():
    recs = [{"mission_context": "정찰", "posture": {"defcon": 3}} for _ in range(12)]  # threat_event 없음
    assert not fit_threat_prior(recs).fitted


def test_featureless_query_none():
    recs = [_rec("정찰", 2, "T3") for _ in range(8)] + [_rec("타격", 5, "T7") for _ in range(8)]
    m = fit_threat_prior(recs)
    assert m.fitted
    assert m.predict({}) is None


def test_query_feature_absent_from_training_ignored():
    # mission_context 만으로 학습 → posture 포함 질의도 미관측 피처 무시하고 안전 예측.
    recs = [{"mission_context": "정찰", "threat_event": "T3"} for _ in range(8)]
    recs += [{"mission_context": "타격", "threat_event": "T7"} for _ in range(8)]
    m = fit_threat_prior(recs)
    out = m.predict({"mission_context": "정찰", "posture": {"defcon": 3}, "corridor_region": "z"})
    assert out is not None and out[0][0] == "T3"


def test_three_class_probs_sum_to_one():
    recs = [_rec("정찰", 2, "T3") for _ in range(5)]
    recs += [_rec("타격", 5, "T7") for _ in range(5)]
    recs += [_rec("호송", 3, "T5", corridor="north") for _ in range(5)]
    m = fit_threat_prior(recs)
    out = m.predict(_rec("정찰", 2, "T3"))
    assert len(out) == 3
    assert abs(sum(p for _, p in out) - 1.0) < 1e-9


def test_unfitted_predict_none():
    assert ThreatPrior(None).predict(_rec("정찰", 3, "T3")) is None
