"""corpus 변환기 + 회수 단위 테스트 (임시 sqlite, 네트워크 없음).

이 테스트는 루트 CI(`python -m pytest`, testpaths=["tests"])가 수집하도록 tests/
아래에 둔다 — infra/log 의 corpus 는 sys.path 로 임포트한다(파이프라인 무변경).
corpus.py 는 표준 라이브러리만 쓰므로 httpx/fastapi 불필요.
"""

import pytest
from corpus import CorpusStore, episode_to_corpus_records

def _episode():
    """정찰 임무 enriched episode (docs/RAG-corpus.md §3-1 형태)."""
    return {
        "mission_id": "m-0417",
        "raw_log_ref": "raw/m-0417.json",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "corridor_region": "KR-hill-07",
        "outcome": "rtb_success",
        "ts": 1751600000000,
        "threat_judgments": [
            {"threat_event": "T3", "confidence": 0.92, "kill_chain_stage": "후기"},
            {"threat_event": "T1", "confidence": 0.71, "kill_chain_stage": "중기"},
        ],
    }


# ── 변환기: episode → 학습레코드 ──────────────────────────────────────────────


def test_transform_one_record_per_threat_judgment():
    records = episode_to_corpus_records(_episode())
    assert len(records) == 2
    assert [r["threat_event"] for r in records] == ["T3", "T1"]


def test_transform_maps_core_five_fields():
    record = episode_to_corpus_records(_episode())[0]
    assert record["mission_context"] == "정찰"
    assert record["posture"] == {"watchcon": 3, "defcon": 3, "infocon": 4}
    assert record["threat_event"] == "T3"
    assert record["confidence"] == 0.92          # 판정 confidence
    assert record["outcome"] == "rtb_success"     # 실제 outcome


def test_transform_carries_provenance_fields():
    record = episode_to_corpus_records(_episode())[0]
    assert record["mission_id"] == "m-0417"
    assert record["raw_log_ref"] == "raw/m-0417.json"
    assert record["corridor_region"] == "KR-hill-07"
    assert record["kill_chain_stage"] == "후기"
    assert record["ts"] == 1751600000000


def test_transform_empty_threat_judgments_yields_no_records():
    episode = _episode()
    episode["threat_judgments"] = []
    assert episode_to_corpus_records(episode) == []


def test_transform_skips_judgment_without_threat_event():
    episode = _episode()
    episode["threat_judgments"] = [
        {"threat_event": "T3", "confidence": 0.9},
        {"confidence": 0.5},  # threat_event 없음 → 건너뜀
    ]
    records = episode_to_corpus_records(episode)
    assert len(records) == 1
    assert records[0]["threat_event"] == "T3"


def test_transform_requires_mission_id_and_context():
    for missing in ("mission_id", "mission_context"):
        episode = _episode()
        del episode[missing]
        with pytest.raises(ValueError):
            episode_to_corpus_records(episode)


# ── 저장 + 회수 ───────────────────────────────────────────────────────────────


@pytest.fixture()
def store(tmp_path):
    s = CorpusStore(tmp_path / "corpus.db")
    yield s
    s.close()


def _strike_episode():
    return {
        "mission_id": "m-0500",
        "raw_log_ref": "raw/m-0500.json",
        "mission_context": "타격",
        "posture": {"watchcon": 2, "defcon": 2, "infocon": 3},
        "corridor_region": "KR-plain-02",
        "outcome": "target_neutralized",
        "ts": 1751700000000,
        "threat_judgments": [
            {"threat_event": "T3", "confidence": 0.55, "kill_chain_stage": "초기"},
        ],
    }


def test_ingest_returns_count_and_persists(store):
    count = store.ingest_episode(_episode())
    assert count == 2
    assert len(store.retrieve()) == 2


def test_ingest_is_idempotent_on_mission_and_threat(store):
    store.ingest_episode(_episode())
    store.ingest_episode(_episode())  # 재집계
    assert len(store.retrieve()) == 2  # 중복 삽입 없음


def test_retrieve_filters_by_mission_context(store):
    store.ingest_episode(_episode())        # 정찰 (T3, T1)
    store.ingest_episode(_strike_episode())  # 타격 (T3)
    recon = store.retrieve(mission_context="정찰")
    assert len(recon) == 2
    assert {r["mission_context"] for r in recon} == {"정찰"}


def test_retrieve_filters_by_threat_event(store):
    store.ingest_episode(_episode())
    store.ingest_episode(_strike_episode())
    t3 = store.retrieve(threat_event="T3")
    assert {r["mission_id"] for r in t3} == {"m-0417", "m-0500"}
    assert all(r["threat_event"] == "T3" for r in t3)


def test_retrieve_filters_by_posture_exact_match(store):
    store.ingest_episode(_episode())
    store.ingest_episode(_strike_episode())
    hits = store.retrieve(posture={"watchcon": 3, "defcon": 3, "infocon": 4})
    assert {r["mission_id"] for r in hits} == {"m-0417"}


def test_retrieve_combined_filters_return_confidence_and_outcome(store):
    store.ingest_episode(_episode())
    store.ingest_episode(_strike_episode())
    hits = store.retrieve(mission_context="정찰", threat_event="T3")
    assert len(hits) == 1
    hit = hits[0]
    assert hit["confidence"] == 0.92
    assert hit["outcome"] == "rtb_success"
    assert hit["posture"] == {"watchcon": 3, "defcon": 3, "infocon": 4}


def test_retrieve_ordered_by_ts_then_confidence_desc(store):
    store.ingest_episode(_episode())        # ts 1751600000000, T3 conf 0.92
    store.ingest_episode(_strike_episode())  # ts 1751700000000, T3 conf 0.55
    t3 = store.retrieve(threat_event="T3")
    assert [r["mission_id"] for r in t3] == ["m-0500", "m-0417"]  # 최신 ts 우선


def test_retrieve_respects_top_k(store):
    store.ingest_episode(_episode())
    assert len(store.retrieve(top_k=1)) == 1


def test_retrieve_negative_top_k_raises(store):
    with pytest.raises(ValueError):
        store.retrieve(top_k=-1)


def test_retrieve_top_k_bounds_large_corpus(store):
    episode = _episode()
    episode["threat_judgments"] = [
        {"threat_event": f"T{i}", "confidence": 0.5, "kill_chain_stage": "초기"}
        for i in range(30)
    ]
    store.ingest_episode(episode)
    assert len(store.retrieve(top_k=5)) == 5


# ── posture 근접매칭 (라운드 2, docs/RAG-corpus.md §6-1) ──────────────────────


def _near_episode(mission_id, posture):
    ep = _episode()
    ep["mission_id"] = mission_id
    ep["posture"] = posture
    ep["threat_judgments"] = [
        {"threat_event": "T3", "confidence": 0.5, "kill_chain_stage": "초기"}
    ]
    return ep


def test_retrieve_posture_tolerance_matches_within_pm_one(store):
    store.ingest_episode(_near_episode("m-a", {"watchcon": 3, "defcon": 3, "infocon": 4}))
    store.ingest_episode(_near_episode("m-b", {"watchcon": 2, "defcon": 4, "infocon": 3}))  # 각 ±1
    store.ingest_episode(_near_episode("m-c", {"watchcon": 1, "defcon": 3, "infocon": 4}))  # watchcon 차 2
    hits = store.retrieve(
        posture={"watchcon": 3, "defcon": 3, "infocon": 4}, posture_tolerance=1
    )
    assert {r["mission_id"] for r in hits} == {"m-a", "m-b"}


def test_retrieve_posture_tolerance_zero_is_subset_value_match(store):
    store.ingest_episode(_near_episode("m-a", {"watchcon": 3, "defcon": 3, "infocon": 4}))
    store.ingest_episode(_near_episode("m-b", {"watchcon": 3, "defcon": 3, "infocon": 5}))
    # 질의에 없는 키는 무시 → defcon만 근접비교
    hits = store.retrieve(posture={"defcon": 3}, posture_tolerance=0)
    assert {r["mission_id"] for r in hits} == {"m-a", "m-b"}


def test_retrieve_posture_tolerance_missing_query_key_excludes_record(store):
    store.ingest_episode(_near_episode("m-a", {"watchcon": 3, "defcon": 3}))  # infocon 결여
    hits = store.retrieve(
        posture={"watchcon": 3, "defcon": 3, "infocon": 4}, posture_tolerance=1
    )
    assert hits == []


def test_retrieve_posture_exact_default_unaffected_by_round2(store):
    store.ingest_episode(_near_episode("m-a", {"watchcon": 3, "defcon": 3, "infocon": 4}))
    store.ingest_episode(_near_episode("m-b", {"watchcon": 2, "defcon": 4, "infocon": 3}))
    hits = store.retrieve(posture={"watchcon": 3, "defcon": 3, "infocon": 4})
    assert {r["mission_id"] for r in hits} == {"m-a"}  # 정확일치만


def test_retrieve_posture_tolerance_respects_top_k_after_filter(store):
    for i in range(5):
        store.ingest_episode(_near_episode(f"m-{i}", {"watchcon": 3, "defcon": 3, "infocon": 4}))
    hits = store.retrieve(
        posture={"watchcon": 3, "defcon": 3, "infocon": 4},
        posture_tolerance=1,
        top_k=2,
    )
    assert len(hits) == 2


def test_retrieve_negative_posture_tolerance_raises(store):
    with pytest.raises(ValueError):
        store.retrieve(posture={"defcon": 3}, posture_tolerance=-1)
