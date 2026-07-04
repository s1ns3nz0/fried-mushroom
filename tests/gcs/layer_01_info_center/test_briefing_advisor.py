"""briefing_advisor — RAG 학습루프 폐쇄: 과거 코퍼스 → 브리핑 confidence advisory.

CRITICAL: advisory 는 병렬 참고지표. 결정론 판정·신호 confidence 를 절대 변경하지 않는다
(MIL-STD-882E SCC-1). 이 테스트는 그 불변식과 이력 캘리브레이션 정확도를 검증한다.

코퍼스 저장은 infra/log/corpus.py 의 CorpusStore(tmp sqlite)를 실제로 사용한다.
"""

import copy
import sys
from pathlib import Path

import pytest

# infra/log 는 tests 수집 경로 밖이라 sys.path 로 붙인다(다른 infra 테스트와 동일 패턴).
_INFRA_LOG = Path(__file__).resolve().parents[3] / "infra" / "log"
if str(_INFRA_LOG) not in sys.path:
    sys.path.insert(0, str(_INFRA_LOG))

from corpus import CorpusStore  # noqa: E402

from gcs.layer_01_info_center.briefing_advisor import (  # noqa: E402
    ADVISORY_MIN_SAMPLES,
    build_briefing_advisory,
    signal_threat_events,
)

_POSTURE = {"watchcon": 3, "defcon": 3, "infocon": 4}


def _rec(mission_id, threat_event, confidence, outcome, *, context="정찰",
         posture=None, narrative_status=None):
    return {
        "mission_id": mission_id, "raw_log_ref": None,
        "mission_context": context, "posture": posture or _POSTURE,
        "threat_event": threat_event, "confidence": confidence, "outcome": outcome,
        "corridor_region": None, "kill_chain_stage": None, "ts": 1000,
        "narrative_status": narrative_status, "narrative": None, "embedding": None,
    }


@pytest.fixture
def store(tmp_path):
    s = CorpusStore(tmp_path / "corpus.db")
    yield s
    s.close()


def _threat_signal(t_code, conf=0.8):
    return {"source_phrase": "적", "signal_type": "threat", "threat": t_code, "confidence": conf}


# ── signal_threat_events ─────────────────────────────────────────────────────

def test_signal_threat_events_extracts_and_dedups():
    signals = [_threat_signal("T3"), _threat_signal("T2"), _threat_signal("T3"),
               {"signal_type": "civil", "effect": "roe_caution", "confidence": 0.7},
               {"signal_type": "mission_purpose", "purpose": "정찰", "confidence": 0.8}]
    assert signal_threat_events(signals) == ["T3", "T2"]  # 순서 보존 + 중복 제거, 비-threat 제외


def test_signal_threat_events_empty():
    assert signal_threat_events([]) == []
    assert signal_threat_events([{"signal_type": "civil", "confidence": 0.7}]) == []


# ── build_briefing_advisory: 기본 계약 ───────────────────────────────────────

def test_advisory_only_flag_always_true(store):
    out = build_briefing_advisory([_threat_signal("T3")], "정찰", _POSTURE, store,
                                  generated_ts=1234)
    assert out["advisory_only"] is True


def test_empty_history_marks_insufficient(store):
    out = build_briefing_advisory([_threat_signal("T3")], "정찰", _POSTURE, store,
                                  generated_ts=1234)
    adv = {a["threat_event"]: a for a in out["advisories"]}
    assert adv["T3"]["sample_size"] == 0
    assert adv["T3"]["sufficient_data"] is False
    assert adv["T3"]["outcome_distribution"] == {}
    assert "T3" in out["threat_events_without_history"]


def test_history_calibration_counts_and_distribution(store):
    store.upsert_records([
        _rec("m1", "T3", 0.90, "threat_confirmed"),
        _rec("m2", "T3", 0.80, "threat_confirmed"),
        _rec("m3", "T3", 0.70, "false_positive"),
    ])
    out = build_briefing_advisory([_threat_signal("T3")], "정찰", _POSTURE, store,
                                  generated_ts=1234, min_samples=3)
    adv = {a["threat_event"]: a for a in out["advisories"]}["T3"]
    assert adv["sample_size"] == 3
    assert adv["outcome_distribution"] == {"threat_confirmed": 2, "false_positive": 1}
    assert adv["avg_past_confidence"] == pytest.approx((0.90 + 0.80 + 0.70) / 3, abs=1e-6)
    assert adv["sufficient_data"] is True
    assert adv["threat_desc"]  # THREAT_CATALOG 설명 포함


def test_min_samples_gating(store):
    store.upsert_records([_rec("m1", "T3", 0.9, "threat_confirmed"),
                          _rec("m2", "T3", 0.8, "threat_confirmed")])
    out = build_briefing_advisory([_threat_signal("T3")], "정찰", _POSTURE, store,
                                  generated_ts=1, min_samples=3)
    adv = {a["threat_event"]: a for a in out["advisories"]}["T3"]
    assert adv["sample_size"] == 2
    assert adv["sufficient_data"] is False  # 2 < 3


def test_does_not_mutate_input_signals(store):
    store.upsert_records([_rec("m1", "T3", 0.9, "threat_confirmed")])
    signals = [_threat_signal("T3", conf=0.8)]
    snapshot = copy.deepcopy(signals)
    build_briefing_advisory(signals, "정찰", _POSTURE, store, generated_ts=1)
    assert signals == snapshot  # advisory 는 신호를 절대 변경 안 함 (SCC-1)


def test_pending_records_excluded_from_calibration(store):
    store.upsert_records([
        _rec("m1", "T3", 0.9, "threat_confirmed"),
        _rec("m2", "T3", 0.8, "threat_confirmed", narrative_status="pending"),
    ])
    out = build_briefing_advisory([_threat_signal("T3")], "정찰", _POSTURE, store,
                                  generated_ts=1)
    adv = {a["threat_event"]: a for a in out["advisories"]}["T3"]
    assert adv["sample_size"] == 1  # pending 제외


def test_posture_tolerance_near_match(store):
    store.upsert_records([_rec("m1", "T3", 0.9, "threat_confirmed",
                               posture={"watchcon": 2, "defcon": 3, "infocon": 4})])
    # 정확일치면 0건
    exact = build_briefing_advisory([_threat_signal("T3")], "정찰", _POSTURE, store,
                                    generated_ts=1)
    assert {a["threat_event"]: a for a in exact["advisories"]}["T3"]["sample_size"] == 0
    # tolerance=1 이면 watchcon 2 vs 3 근접매칭 → 1건
    near = build_briefing_advisory([_threat_signal("T3")], "정찰", _POSTURE, store,
                                   generated_ts=1, posture_tolerance=1)
    assert {a["threat_event"]: a for a in near["advisories"]}["T3"]["sample_size"] == 1


def test_default_min_samples_constant():
    assert isinstance(ADVISORY_MIN_SAMPLES, int) and ADVISORY_MIN_SAMPLES >= 1


def test_non_threat_signals_produce_no_advisory(store):
    signals = [{"signal_type": "civil", "effect": "roe_caution", "confidence": 0.7}]
    out = build_briefing_advisory(signals, "정찰", _POSTURE, store, generated_ts=1)
    assert out["advisories"] == []
    assert out["threat_events_without_history"] == []


# ── 학습루프 폐쇄: 실제 nlp_extract 출력 → advisor 종단 ────────────────────────

def test_end_to_end_nlp_signals_to_advisory(store):
    """실제 지시서 → extract_signals → build_briefing_advisory 종단.

    코퍼스에 과거 T3(저격조) 이력을 심어두고, 신규 지시서에서 T3 신호가 뽑히면
    advisory 가 그 이력을 참고로 붙는지 확인 — RAG 학습루프가 실제로 닫힘.
    """
    from gcs.layer_01_info_center.nlp_extract import extract_signals

    store.upsert_records([
        _rec("past1", "T3", 0.88, "threat_confirmed"),
        _rec("past2", "T3", 0.83, "threat_confirmed"),
        _rec("past3", "T3", 0.60, "false_positive"),
    ])
    signals = extract_signals("적 저격조 확인됨. 정찰 임무.")
    t_codes = signal_threat_events(signals)
    assert "T3" in t_codes  # 지시서에서 T3 신호가 실제로 추출됨

    out = build_briefing_advisory(signals, "정찰", _POSTURE, store, generated_ts=1, min_samples=3)
    t3 = {a["threat_event"]: a for a in out["advisories"]}["T3"]
    assert t3["sample_size"] == 3
    assert t3["sufficient_data"] is True
    assert t3["outcome_distribution"] == {"threat_confirmed": 2, "false_positive": 1}
    # 결정 경로 무변경 — 원본 신호 confidence 그대로.
    assert all("confidence" in s for s in signals)
