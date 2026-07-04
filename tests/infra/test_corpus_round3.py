"""RAG 코퍼스 라운드 3 회귀 테스트 (#166) — pending 제외 정책 + narrative 벡터 하이브리드 회수.

test_corpus.py와 동일하게 infra/log를 sys.path로 임포트한다(conftest.py, 파이프라인 무변경).
→ 계약 소스 오브 트루스: docs/RAG-corpus.md §6-2.

세 갈래:
(a) pending 제외: narrative_status='pending' 판정은 회수에서 항상 제외된다.
(b) 하이브리드 재순위: narrative 유사도로 순서가 바뀐다 (벡터 백엔드 있을 때만 — importorskip).
(c) 벡터 백엔드 부재 시 degrade: 벡터 없이도 retrieve()가 메타필터 결과를 정상 반환한다.
"""

import sqlite3

import corpus
import pytest
from aggregate import NARRATIVE_CONFIRMED, NARRATIVE_PENDING
from corpus import CorpusStore

_ROUND1_2_SCHEMA = """
CREATE TABLE corpus_record (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id       TEXT NOT NULL,
    raw_log_ref      TEXT,
    mission_context  TEXT NOT NULL,
    posture          TEXT,
    threat_event     TEXT NOT NULL,
    confidence       REAL,
    outcome          TEXT,
    corridor_region  TEXT,
    kill_chain_stage TEXT,
    ts               INTEGER,
    UNIQUE (mission_id, threat_event)
);
"""


def _episode(mission_id, narrative_status=None, embedding=None, ts=1751600000000, confidence=0.5):
    """단일 T3 판정을 담은 최소 enriched episode."""
    return {
        "mission_id": mission_id,
        "raw_log_ref": f"raw/{mission_id}.json",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "corridor_region": "KR-hill-07",
        "outcome": "rtb_success",
        "ts": ts,
        "narrative_status": narrative_status,
        "narrative": "선체 임무 서술" if narrative_status else None,
        "embedding": embedding,
        "threat_judgments": [
            {"threat_event": "T3", "confidence": confidence, "kill_chain_stage": "초기"},
        ],
    }


@pytest.fixture()
def store(tmp_path):
    s = CorpusStore(tmp_path / "corpus.db")
    yield s
    s.close()


# ── (a) pending 제외 정책 ──────────────────────────────────────────────────────


def test_pending_episode_excluded_from_retrieve(store):
    store.ingest_episode(_episode("m-pending", narrative_status=NARRATIVE_PENDING))
    assert store.retrieve() == []
    assert store.retrieve(mission_context="정찰") == []
    assert store.retrieve(threat_event="T3") == []


def test_confirmed_episode_included_in_retrieve(store):
    store.ingest_episode(_episode("m-confirmed", narrative_status=NARRATIVE_CONFIRMED))
    hits = store.retrieve()
    assert {r["mission_id"] for r in hits} == {"m-confirmed"}
    assert hits[0]["narrative_status"] == NARRATIVE_CONFIRMED


def test_episode_without_narrative_status_included_backward_compat(store):
    # 라운드 1/2가 만든 기존 episode에는 narrative_status 필드가 아예 없다(None).
    store.ingest_episode(_episode("m-legacy", narrative_status=None))
    hits = store.retrieve()
    assert {r["mission_id"] for r in hits} == {"m-legacy"}
    assert hits[0]["narrative_status"] is None


def test_pending_excluded_alongside_confirmed_records(store):
    store.ingest_episode(_episode("m-pending", narrative_status=NARRATIVE_PENDING))
    store.ingest_episode(_episode("m-confirmed", narrative_status=NARRATIVE_CONFIRMED))
    hits = store.retrieve(threat_event="T3")
    assert {r["mission_id"] for r in hits} == {"m-confirmed"}


def test_ingest_stores_pending_record_but_hides_from_retrieve(store):
    """저장(편입) 자체는 그대로 이뤄진다 — 감사가능성 원칙(§5). 회수만 가려진다."""
    count = store.ingest_episode(_episode("m-pending", narrative_status=NARRATIVE_PENDING))
    assert count == 1
    assert store.retrieve() == []  # 저장은 됐지만 회수는 제외


# ── (b) narrative 벡터 하이브리드 재순위 (벡터 백엔드 있을 때만) ───────────────


def test_narrative_hybrid_rerank_changes_order_when_vec_backend_available(store):
    pytest.importorskip("sqlite_vec")

    # m-a: ts/confidence 기준으로는 뒤지지만 쿼리 임베딩과 가장 가깝다.
    store.ingest_episode(
        _episode(
            "m-a", narrative_status=NARRATIVE_CONFIRMED,
            embedding=[1.0, 0.0, 0.0], ts=1751600000000, confidence=0.10,
        )
    )
    # m-b: ts/confidence 기준으로 가장 앞서지만 쿼리 임베딩과는 직교(가장 멀다).
    store.ingest_episode(
        _episode(
            "m-b", narrative_status=NARRATIVE_CONFIRMED,
            embedding=[0.0, 1.0, 0.0], ts=1751700000000, confidence=0.99,
        )
    )

    default_order = store.retrieve(threat_event="T3")
    assert [r["mission_id"] for r in default_order] == ["m-b", "m-a"]  # ts/confidence 우선

    reranked = store.retrieve(threat_event="T3", narrative_query_embedding=[1.0, 0.0, 0.0])
    assert [r["mission_id"] for r in reranked] == ["m-a", "m-b"]  # 유사도로 순서 반전


# ── (c) 벡터 백엔드 부재 시 graceful degrade ──────────────────────────────────


def test_retrieve_degrades_to_metafilter_only_without_vec_backend(store, monkeypatch):
    # 벡터 백엔드 미설치 상태를 강제(로컬에 sqlite_vec이 있어도 이 테스트는 결정적으로 재현).
    monkeypatch.setattr(corpus, "_VEC_BACKEND_AVAILABLE", False)

    store.ingest_episode(
        _episode(
            "m-a", narrative_status=NARRATIVE_CONFIRMED,
            embedding=[1.0, 0.0, 0.0], ts=1751600000000, confidence=0.10,
        )
    )
    store.ingest_episode(
        _episode(
            "m-b", narrative_status=NARRATIVE_CONFIRMED,
            embedding=[0.0, 1.0, 0.0], ts=1751700000000, confidence=0.99,
        )
    )

    # #347: 순수 파이썬 rerank 는 sqlite_vec 불필요 — _VEC_BACKEND_AVAILABLE=False 여도 적용된다.
    # [1,0,0] 질의 → m-a(embedding=[1,0,0]) 가 m-b 보다 유사도 높아 앞으로 재순위된다.
    hits = store.retrieve(threat_event="T3", narrative_query_embedding=[1.0, 0.0, 0.0])
    assert [r["mission_id"] for r in hits] == ["m-a", "m-b"]


def test_retrieve_without_narrative_query_embedding_unaffected_by_vec_flag(store, monkeypatch):
    monkeypatch.setattr(corpus, "_VEC_BACKEND_AVAILABLE", False)
    store.ingest_episode(_episode("m-a", narrative_status=NARRATIVE_CONFIRMED))
    # 기본값(narrative_query_embedding=None)은 라운드 1/2 동작 그대로(하위호환).
    assert len(store.retrieve()) == 1


# ── (d) 기존 라운드1/2 DB 오픈 시 컬럼 마이그레이션 (#166 Codex P2) ────────────


def test_opening_round1_2_db_migrates_missing_columns(tmp_path):
    """라운드1/2 스키마로 만든 기존 corpus_record를 라운드3 CorpusStore로 열면
    narrative_status/narrative/embedding 컬럼이 추가돼야 하고(마이그레이션),
    기존 오픈은 예외 없이 성공해야 하며 기존 데이터는 보존돼야 한다.
    """
    db_path = tmp_path / "legacy_corpus.db"

    legacy_conn = sqlite3.connect(db_path)
    legacy_conn.executescript(_ROUND1_2_SCHEMA)
    legacy_conn.execute(
        """
        INSERT INTO corpus_record (
            mission_id, raw_log_ref, mission_context, posture,
            threat_event, confidence, outcome, corridor_region,
            kill_chain_stage, ts
        ) VALUES ('m-legacy', 'raw/m-legacy.json', '정찰', '{"defcon": 3}',
                  'T3', 0.7, 'rtb_success', 'KR-hill-07', '초기', 1751600000000)
        """
    )
    legacy_conn.commit()
    legacy_conn.close()

    store = CorpusStore(db_path)
    try:
        columns = {
            row[1] for row in store._conn.execute("PRAGMA table_info(corpus_record)")
        }
        assert {"narrative_status", "narrative", "embedding"} <= columns

        row = store._conn.execute(
            "SELECT mission_id, threat_event, confidence FROM corpus_record"
            " WHERE mission_id = 'm-legacy'"
        ).fetchone()
        assert tuple(row) == ("m-legacy", "T3", 0.7)
    finally:
        store.close()
