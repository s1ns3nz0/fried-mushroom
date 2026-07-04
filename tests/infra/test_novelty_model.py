"""임무 이례성(novelty) 탐지 모델 — kNN 거리 기반 (5번째 실 ML).

순수 numpy 라 결정론 검증. conftest.py 가 infra/log 를 sys.path 로 임포트.
"""

import pytest

pytest.importorskip("numpy")  # ml extra 미설치 CI 는 학습경로 skip

from novelty_model import NoveltyDetector, fit_novelty_detector


def _rec(mc, defcon, conf, threat="T3"):
    return {
        "mission_context": mc,
        "posture": {"defcon": defcon, "watchcon": defcon, "infocon": defcon},
        "threat_event": threat,
        "confidence": conf,
    }


def test_insufficient_samples_not_fitted():
    det = fit_novelty_detector([_rec("정찰", 5, 0.9)] * 4)
    assert not det.fitted
    assert det.score(_rec("정찰", 5, 0.9)) is None


def test_flags_outlier_as_novel():
    # 조밀 클러스터(정찰, defcon5 근방) + 확연히 벗어난 이상치.
    recs = [_rec("정찰", 5, 0.9) for _ in range(10)]
    recs += [_rec("정찰", 5, 0.88) for _ in range(5)]
    det = fit_novelty_detector(recs)
    assert det.fitted
    inlier = det.score(_rec("정찰", 5, 0.9))
    outlier = det.score(_rec("타격", 1, 0.1, threat="T7"))
    assert inlier["novelty"] < outlier["novelty"]
    assert outlier["is_novel"] is True
    assert outlier["percentile"] >= inlier["percentile"]


def test_score_fields_and_ranges():
    recs = [_rec("정찰", 4, 0.8) for _ in range(6)] + [_rec("타격", 2, 0.5) for _ in range(6)]
    det = fit_novelty_detector(recs)
    s = det.score(_rec("호송", 3, 0.7))
    assert set(s) == {"novelty", "percentile", "is_novel"}
    assert s["novelty"] >= 0.0
    assert 0.0 <= s["percentile"] <= 1.0
    assert isinstance(s["is_novel"], bool)


def test_no_outcome_label_required():
    # outcome 필드 전무해도 학습됨(비지도) — 결과 예측기와의 핵심 차이.
    recs = [_rec("정찰", 5, 0.9) for _ in range(8)] + [_rec("타격", 2, 0.4) for _ in range(4)]
    assert fit_novelty_detector(recs).fitted


def test_featureless_records_excluded():
    recs = [{"note": "no features"} for _ in range(12)]
    assert not fit_novelty_detector(recs).fitted


def test_fitted_none_on_featureless_query():
    recs = [_rec("정찰", 5, 0.9) for _ in range(8)] + [_rec("타격", 2, 0.4) for _ in range(4)]
    det = fit_novelty_detector(recs)
    assert det.fitted
    assert det.score({}) is None


def test_missing_posture_imputed_not_extreme():
    # posture 없는 부분 레코드는 결측→평균대치라 극단 z-score(이례 오탐)로 튀지 않아야.
    recs = [_rec("정찰", 5, 0.9) for _ in range(10)] + [_rec("정찰", 5, 0.88) for _ in range(4)]
    det = fit_novelty_detector(recs)
    partial = {"mission_context": "정찰", "confidence": 0.9}  # posture 결측
    full = _rec("정찰", 5, 0.9)
    s_partial = det.score(partial)
    s_full = det.score(full)
    # 결측 대치가 평균(=클러스터 중심)이므로 부분 레코드도 이례로 오탐되지 않는다.
    assert s_partial["is_novel"] is False
    assert s_partial["novelty"] < det.score(_rec("타격", 1, 0.1, threat="T7"))["novelty"]


def test_absent_numeric_column_neutral():
    # posture 전무 코퍼스: 학습에 없던 수치컬럼은 질의에 값이 있어도 인위적 0기준 오탐 안 냄.
    recs = [{"mission_context": "정찰", "threat_event": "T3", "confidence": 0.9} for _ in range(12)]
    det = fit_novelty_detector(recs)
    # posture 를 포함한 질의 — 학습 전무 컬럼이므로 중립 처리되어 이례로 튀지 않아야.
    q = {"mission_context": "정찰", "posture": {"defcon": 1, "watchcon": 1, "infocon": 1},
         "threat_event": "T3", "confidence": 0.9}
    assert det.score(q)["is_novel"] is False


def test_unfitted_score_none():
    assert NoveltyDetector(None).score(_rec("정찰", 5, 0.9)) is None
