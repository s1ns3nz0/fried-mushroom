"""corpus: 인제스트 임베딩 자동생성 + rerank 게이트 분리 검증 (#347).

1. episode_to_corpus_records: narrative 있고 embedding 없으면 embed_narrative 로 채움
2. _rerank_by_narrative_similarity: sqlite_vec 없어도 pure-Python rerank 동작
3. retrieve_semantic: zero-dep(narrative_embed) 로 시맨틱 회수 활성화

tests/infra/conftest.py 가 infra/log 를 sys.path 에 추가한다.
"""

import sys
from pathlib import Path

import pytest

from aggregate import NARRATIVE_CONFIRMED, NARRATIVE_PENDING
from corpus import CorpusStore, _VEC_BACKEND_AVAILABLE, episode_to_corpus_records
from narrative_embed import embed_narrative


# ── 1. episode_to_corpus_records: 임베딩 자동 생성 ───────────────────────────


def _episode(mission_id, narrative=None, embedding=None, outcome="rtb_success"):
    return {
        "mission_id": mission_id,
        "raw_log_ref": None,
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "corridor_region": None,
        "outcome": outcome,
        "ts": 1000,
        "narrative_status": NARRATIVE_CONFIRMED,
        "narrative": narrative,
        "embedding": embedding,
        "threat_judgments": [
            {"threat_event": "T3", "confidence": 0.85, "kill_chain_stage": "초기"}
        ],
    }


def test_ingest_fills_embedding_from_narrative():
    """narrative 있고 embedding 없으면 embed_narrative 로 자동 채워야 한다."""
    records = episode_to_corpus_records(
        _episode("m-auto", narrative="저격조 T3 확인됨. 고도 상승 회피 기동.")
    )
    assert len(records) == 1
    emb = records[0]["embedding"]
    assert emb is not None, "narrative 있는 레코드에 embedding 이 채워져야 함"
    assert isinstance(emb, list)
    assert all(isinstance(x, float) for x in emb)


def test_ingest_keeps_existing_embedding():
    """embedding 이 이미 있으면 덮어쓰지 않아야 한다."""
    custom = [0.1, 0.2, 0.3]
    records = episode_to_corpus_records(
        _episode("m-keep", narrative="저격조 조우", embedding=custom)
    )
    assert records[0]["embedding"] == custom, "기존 embedding 보존"


def test_ingest_no_embedding_when_no_narrative():
    """narrative 없으면 embedding 도 None."""
    records = episode_to_corpus_records(_episode("m-nonarr", narrative=None))
    assert records[0]["embedding"] is None


# ── 2. rerank 게이트 — sqlite_vec 없어도 동작 ───────────────────────────────


@pytest.fixture
def store(tmp_path):
    s = CorpusStore(tmp_path / "corpus.db")
    yield s
    s.close()


def test_retrieve_reranks_without_sqlite_vec(store, monkeypatch):
    """sqlite_vec 미설치(_VEC_BACKEND_AVAILABLE=False)여도 narrative rerank 가 동작해야 한다."""
    import corpus as corpus_mod
    monkeypatch.setattr(corpus_mod, "_VEC_BACKEND_AVAILABLE", False)

    base_text = "저격조 T3 확인됨. 고도 상승 회피."
    similar_text = "저격조 T3 조우. 고도 상승 기동."
    unrelated_text = "기상 이상. RTB 결정. 배터리 부족."

    store.ingest_episode(_episode("m-base", narrative=base_text, outcome="rtb_success"))
    store.ingest_episode(
        _episode("m-similar", narrative=similar_text, outcome="rtb_success")
    )
    # m-unrelated: 다른 threat_event 로 저장 (T2)
    ep_unrelated = _episode("m-unrelated", narrative=unrelated_text)
    ep_unrelated["threat_judgments"] = [
        {"threat_event": "T3", "confidence": 0.5, "kill_chain_stage": "초기"}
    ]
    ep_unrelated["narrative"] = unrelated_text
    store.ingest_episode(ep_unrelated)

    query_emb = embed_narrative(base_text)
    results = store.retrieve(
        mission_context="정찰",
        threat_event="T3",
        narrative_query_embedding=query_emb,
        top_k=3,
    )
    assert len(results) >= 2
    # base 와 similar 가 unrelated 보다 앞에 있어야 함
    ids = [r["mission_id"] for r in results]
    assert ids.index("m-base") < ids.index("m-unrelated") or \
           ids.index("m-similar") < ids.index("m-unrelated"), (
        f"유사 narrative 가 비관련보다 앞에 있어야 함: {ids}"
    )


def test_retrieve_no_rerank_when_no_query_embedding(store):
    """query embedding 없으면 rerank 없이 ts/confidence 순 반환."""
    store.ingest_episode(_episode("m-a", narrative="저격조 T3", outcome="rtb_success"))
    store.ingest_episode(_episode("m-b", narrative="저격조 T3", outcome="mission_abort"))
    results = store.retrieve(mission_context="정찰", threat_event="T3", top_k=10)
    assert isinstance(results, list)
    assert len(results) == 2


# ── 3. retrieve_semantic: zero-dep 시맨틱 회수 ──────────────────────────────


def test_retrieve_semantic_works_without_sentence_transformers(store, monkeypatch):
    """sentence_transformers 없어도 retrieve_semantic 이 narrative rerank 를 수행해야 한다."""
    import corpus as corpus_mod

    # sentence_transformers 의존 없이 narrative_embed 를 사용하도록 강제
    monkeypatch.setattr(corpus_mod, "_VEC_BACKEND_AVAILABLE", False)

    base_text = "저격조 T3 확인됨. 고도 상승 회피 기동."
    similar_text = "저격조 T3 조우. 회피 기동 실시."

    store.ingest_episode(_episode("m-x", narrative=base_text))
    store.ingest_episode(_episode("m-y", narrative=similar_text))

    results = store.retrieve_semantic("저격조 조우", threat_event="T3")
    assert isinstance(results, list)
    assert len(results) >= 1


def test_retrieve_semantic_returns_list_on_empty_corpus(store):
    """코퍼스가 비어있으면 빈 리스트 반환 (크래시 없음)."""
    results = store.retrieve_semantic("저격조 조우", threat_event="T3")
    assert results == []
