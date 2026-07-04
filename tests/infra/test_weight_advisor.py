"""weight_advisor — 결과검증 신뢰도 캘리브레이션 advisory (라운드 3 §2). TDD.

advisory-only: 산출물은 사람이 읽는 제안 리포트. 어떤 결정론 상수도 읽거나 쓰지 않는다 (SCC-1).
설계 정본: docs/RAG-corpus-round3.md.
"""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_INFRA_LOG = _ROOT / "infra" / "log"
if str(_INFRA_LOG) not in sys.path:
    sys.path.insert(0, str(_INFRA_LOG))

from weight_advisor import (  # noqa: E402
    build_advisory_report,
    confidence_calibration,
    outcome_label,
)


def _rec(threat_event, confidence, outcome):
    return {"threat_event": threat_event, "confidence": confidence, "outcome": outcome}


def test_outcome_label_maps_success_failure_and_excludes_unknown():
    assert outcome_label("rtb_success") == 1
    assert outcome_label("arrived") == 1
    assert outcome_label("captured") == 0
    assert outcome_label("lost") == 0
    assert outcome_label(None) is None
    assert outcome_label("weird_unlabeled") is None


def test_overconfident_threat_flagged():
    # T3 를 평균 0.9 로 불렀지만 실제 4건 중 2건만 성공 → 과신(calib_error>0).
    recs = [
        _rec("T3", 0.9, "rtb_success"),
        _rec("T3", 0.9, "mission_success"),
        _rec("T3", 0.9, "captured"),
        _rec("T3", 0.9, "lost"),
    ]
    rows = confidence_calibration(recs)
    t3 = next(r for r in rows if r["threat_event"] == "T3")
    assert t3["n"] == 4
    assert t3["mean_confidence"] == 0.9
    assert t3["hit_rate"] == 0.5
    assert round(t3["calib_error"], 3) == 0.4
    assert "overconfident" in t3["note"].lower() or "과신" in t3["note"]


def test_well_calibrated_near_zero_error():
    recs = [
        _rec("T1", 0.5, "rtb_success"),
        _rec("T1", 0.5, "lost"),
    ]
    t1 = confidence_calibration(recs)[0]
    assert t1["hit_rate"] == 0.5
    assert round(t1["calib_error"], 3) == 0.0


def test_low_sample_flag():
    recs = [_rec("T7", 0.8, "arrived")]  # n=1
    row = confidence_calibration(recs)[0]
    assert row["low_sample"] is True


def test_unknown_outcomes_excluded_from_calibration():
    # outcome None/미분류는 표본에서 제외 — 제외 후 표본 없으면 threat 자체 미출력.
    recs = [_rec("T2", 0.7, None), _rec("T2", 0.7, "pending_unknown")]
    assert confidence_calibration(recs) == []


def test_report_structure_and_guardrails():
    recs = [_rec("T3", 0.9, "rtb_success"), _rec("T3", 0.9, "lost")]
    report = build_advisory_report(recs, generated_ts=1234)
    assert report["generated_ts"] == 1234
    assert report["corpus_size"] == 2
    assert report["channel_weight_proposals"] == []  # 스키마 확장 전까지 빈 리스트
    assert report["guardrails"]["advisory_only"] is True
    assert report["guardrails"]["applied"] is False


def test_deterministic_report():
    recs = [_rec("T3", 0.9, "lost"), _rec("T1", 0.6, "rtb_success"), _rec("T3", 0.8, "arrived")]
    assert build_advisory_report(recs, 0) == build_advisory_report(recs, 0)


def test_advisor_does_not_import_constants():
    # SCC-1 안전 회귀: advisory 코드는 결정론 상수를 import 하지 않는다 (정적 소스 잠금).
    src = (_INFRA_LOG / "weight_advisor.py").read_text(encoding="utf-8")
    import_lines = [ln for ln in src.splitlines() if ln.lstrip().startswith(("import ", "from "))]
    assert not any("constants" in ln for ln in import_lines), "shared/constants import 금지"
    assert not any("shared" in ln for ln in import_lines), "온보드 shared 모듈 import 금지"
    assert "eval(" not in src and "exec(" not in src
