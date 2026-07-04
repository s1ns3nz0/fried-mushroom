"""embedding 모델 + CorpusStore.retrieve_semantic 배선 (RAG 라운드 3, 첫 실 ML 모델).

배선/하향 로직은 주입 벡터로 결정론 검증(모델 불필요). 실 모델은 선택 의존이라
importorskip + 로드 실패(네트워크/가중치 부재) 시 skip 하는 smoke 1건으로만 확인.
conftest.py 가 infra/log 를 sys.path 로 임포트한다.
"""

import math

import corpus
import embedding
import pytest
from aggregate import NARRATIVE_CONFIRMED
from corpus import CorpusStore


def _episode(mission_id, embedding_vec, ts, confidence):
    return {
        "mission_id": mission_id,
        "raw_log_ref": f"raw/{mission_id}.json",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "corridor_region": "KR-hill-07",
        "outcome": "rtb_success",
        "ts": ts,
        "narrative_status": NARRATIVE_CONFIRMED,
        "narrative": f"{mission_id} 서술",
        "embedding": embedding_vec,
        "threat_judgments": [{"threat_event": "T3", "confidence": confidence, "kill_chain_stage": "초기"}],
    }


@pytest.fixture()
def store(tmp_path):
    s = CorpusStore(tmp_path / "corpus.db")
    yield s
    s.close()


# ── embed(): 계약 ─────────────────────────────────────────────────────────────


def test_embed_empty_or_none_is_none():
    assert embedding.embed("") is None
    assert embedding.embed(None) is None


def test_embed_none_when_model_unavailable(monkeypatch):
    # 모델 로드 불가(선택 의존 미설치/네트워크) → embed None (하위호환 하향).
    monkeypatch.setattr(embedding, "_load", lambda name: None)
    assert embedding.embed("적 저격조 조우 회피") is None


# ── retrieve_semantic(): 배선 + 하향 ─────────────────────────────────────────


def test_retrieve_semantic_degrades_when_model_unavailable(store, monkeypatch):
    # 백엔드는 있으나 모델 미가용 → query 벡터 None → 메타필터-only(ts/confidence) 로 하향.
    monkeypatch.setattr(corpus, "_VEC_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(embedding, "embed", lambda text, name=None: None)
    store.ingest_episode(_episode("m-a", [1.0, 0.0, 0.0], ts=1751600000000, confidence=0.10))
    store.ingest_episode(_episode("m-b", [0.0, 1.0, 0.0], ts=1751700000000, confidence=0.99))
    hits = store.retrieve_semantic("적 저격조", threat_event="T3")
    assert [r["mission_id"] for r in hits] == ["m-b", "m-a"]  # ts/confidence 순(재순위 없음)


def test_retrieve_semantic_reranks_with_model(store, monkeypatch):
    # model_name 명시 + _VEC_BACKEND_AVAILABLE=True → embedding.embed 모델 경로 사용.
    # 모델이 쿼리를 [1,0,0]으로 임베딩 → 유사도로 m-a 가 앞으로(ts/confidence 반전).
    monkeypatch.setattr(embedding, "embed", lambda text, name=None: [1.0, 0.0, 0.0])
    monkeypatch.setattr(corpus, "_VEC_BACKEND_AVAILABLE", True)
    store.ingest_episode(_episode("m-a", [1.0, 0.0, 0.0], ts=1751600000000, confidence=0.10))
    store.ingest_episode(_episode("m-b", [0.0, 1.0, 0.0], ts=1751700000000, confidence=0.99))
    hits = store.retrieve_semantic(
        "적 저격조 조우", threat_event="T3",
        model_name="test-model",  # #347: model_name 명시 시 embedding.embed 경로
    )
    assert [r["mission_id"] for r in hits] == ["m-a", "m-b"]  # 시맨틱 유사도 우선


# ── 실 모델 smoke (선택 의존, 네트워크 필요 시 skip) ──────────────────────────


def test_real_model_smoke():
    pytest.importorskip("sentence_transformers")
    small = "sentence-transformers/all-MiniLM-L6-v2"
    vec = embedding.embed("적 저격조 조우 후 고도 상승 회피", small)
    if vec is None:
        pytest.skip("임베딩 모델 가중치 로드 불가(네트워크/캐시 부재)")
    assert len(vec) == 384, "MiniLM 384차원"
    assert abs(math.sqrt(sum(x * x for x in vec)) - 1.0) < 1e-3, "L2 정규화 벡터"
    assert embedding.embed("적 저격조 조우 후 고도 상승 회피", small) == vec, "결정론(같은 텍스트=같은 벡터)"
