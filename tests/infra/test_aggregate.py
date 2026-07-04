"""aggregate.aggregate_threat_judgments + build_episode_index 위협판정 집계 단위 테스트.

라운드 2(#143): threat_modeling_log → 위협별 판정(confidence 보존) 집계기.
test_corpus.py와 동일하게 infra/log 를 sys.path 로 임포트(파이프라인 무변경, stdlib 전용).
→ 계약 소스 오브 트루스: docs/RAG-corpus.md §2-2, §3-1.
"""

from aggregate import (  # noqa: E402
    aggregate_threat_events,
    aggregate_threat_judgments,
    build_episode_index,
)


def _threat_modeling_log():
    """T3(초기→후기 발전), T1(중기) 시계열 판정 로그."""
    return [
        {"ts": 10, "threat_event": "T3", "confidence": 0.40, "kill_chain_stage": "초기"},
        {"ts": 20, "threat_event": "T1", "confidence": 0.71, "kill_chain_stage": "중기"},
        {"ts": 30, "threat_event": "T3", "confidence": 0.92, "kill_chain_stage": "후기"},
    ]


# ── aggregate_threat_judgments ────────────────────────────────────────────────


def test_judgments_one_per_unique_threat_first_seen_order():
    judgments = aggregate_threat_judgments(_threat_modeling_log())
    assert [j["threat_event"] for j in judgments] == ["T3", "T1"]


def test_judgments_latest_ts_wins_preserving_confidence_stage_ts():
    judgments = aggregate_threat_judgments(_threat_modeling_log())
    t3 = next(j for j in judgments if j["threat_event"] == "T3")
    assert t3["confidence"] == 0.92          # 후기 판정(ts=30) 확신도
    assert t3["kill_chain_stage"] == "후기"   # 최신 킬체인 단계
    assert t3["ts"] == 30                     # 최신 ts 보존


def test_judgments_preserves_per_threat_fields():
    judgments = aggregate_threat_judgments(_threat_modeling_log())
    t1 = next(j for j in judgments if j["threat_event"] == "T1")
    assert t1 == {
        "threat_event": "T1",
        "confidence": 0.71,
        "kill_chain_stage": "중기",
        "ts": 20,
    }


def test_judgments_skips_entries_without_threat_event():
    log = [
        {"ts": 10, "threat_event": "T3", "confidence": 0.5, "kill_chain_stage": "초기"},
        {"ts": 20, "confidence": 0.9, "kill_chain_stage": "중기"},  # threat_event 없음
    ]
    judgments = aggregate_threat_judgments(log)
    assert [j["threat_event"] for j in judgments] == ["T3"]


def test_judgments_empty_and_none_log():
    assert aggregate_threat_judgments([]) == []
    assert aggregate_threat_judgments(None) == []


# ── aggregate_threat_events (문자열 배열, judgments에서 파생) ─────────────────


def test_threat_events_unique_first_seen_order():
    assert aggregate_threat_events(_threat_modeling_log()) == ["T3", "T1"]


# ── build_episode_index 결선 ─────────────────────────────────────────────────


def test_build_episode_index_wires_real_threat_judgments():
    raw_log = {"mission_id": "m-0417", "threat_modeling_log": _threat_modeling_log()}
    episode = build_episode_index(raw_log, "raw/m-0417.json")
    assert episode["mission_id"] == "m-0417"
    assert episode["raw_log_ref"] == "raw/m-0417.json"
    # 실 confidence(자리표시 아님)를 위협별로 보존
    judgments = episode["threat_judgments"]
    assert {j["threat_event"]: j["confidence"] for j in judgments} == {
        "T3": 0.92,
        "T1": 0.71,
    }
    # 문자열 배열도 병존(schema.sql episode_index.threat_events)
    assert episode["threat_events"] == ["T3", "T1"]


def test_build_episode_index_no_threat_log_yields_empty():
    episode = build_episode_index({"mission_id": "m-0"}, "raw/m-0.json")
    assert episode["threat_judgments"] == []
    assert episode["threat_events"] == []
