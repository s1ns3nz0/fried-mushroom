"""RAG 코퍼스 — episode → 학습레코드 변환 + 저장/회수 (라운드 1-3).

episode(집계 산출)를 "위협 판정 하나당 학습레코드 하나"로 펼쳐 corpus_record 테이블에
저장하고, "다음 임무 브리핑 시 NLP confidence 참고자료"를 메타필터로 회수한다.

- 스키마·계약 소스 오브 트루스: docs/RAG-corpus.md
- 저장 스키마: schema.sql (corpus_record)
- 스타일: store.py:EpisodeStore 미러링 (SQLite + 동일 파일 공존 가능)

경계(범위 밖): CHANNEL_WEIGHTS 등 shared/constants.py 상수 재학습은 이번 라운드 범위 밖이다
(docs/RAG-corpus.md §7). 이 모듈은 어떤 상수도 읽거나 쓰지 않는다.
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from aggregate import NARRATIVE_PENDING

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# 라운드1/2가 만든 기존 corpus_record에는 라운드3 컬럼이 없다 — `CREATE TABLE IF NOT EXISTS`는
# 기존 테이블에 컬럼을 추가하지 않으므로, 인덱스 생성 전에 별도로 마이그레이션해야 한다.
# → docs/RAG-corpus.md §6-2, #166 Codex P2.
_ROUND3_NEW_COLUMNS = ("narrative_status", "narrative", "embedding")

# 벡터 백엔드(sqlite_vec)는 선택 의존 — narrative 하이브리드 재순위의 활성화 게이트.
# 미설치(CI 기본) 시 retrieve()는 메타필터-only로 자동 하향(degrade)한다.
# docs/RAG-corpus.md §6-2.
try:
    import sqlite_vec  # noqa: F401

    _VEC_BACKEND_AVAILABLE = True
except ImportError:
    _VEC_BACKEND_AVAILABLE = False


def _canonical_posture(posture: Any) -> str | None:
    """posture dict를 표준 JSON(정렬 키)으로 직렬화 — 회수 시 정확일치 비교용."""
    if posture is None:
        return None
    return json.dumps(posture, sort_keys=True, ensure_ascii=False)


def _serialize_embedding(embedding: list[float] | None) -> str | None:
    """narrative 임베딩(list[float])을 표준 JSON 배열 텍스트로 직렬화."""
    if embedding is None:
        return None
    return json.dumps(embedding)


def _posture_within(
    record_posture: dict[str, Any] | None,
    query_posture: dict[str, Any],
    tolerance: int,
) -> bool:
    """레코드 posture가 질의 posture에 ±tolerance 근접하는지 판정 (docs/RAG-corpus.md §6-1).

    질의 각 키에 대해 레코드가 그 키를 가지고 |record-query| ≤ tolerance 를 모두 만족해야 한다.
    질의에 없는 키는 무시. 레코드 posture가 None이거나 질의 키를 결여하면 비매칭.
    """
    if record_posture is None:
        return False
    for key, qval in query_posture.items():
        if key not in record_posture:
            return False
        if abs(record_posture[key] - qval) > tolerance:
            return False
    return True


def _cosine_similarity(a: list[float] | None, b: list[float] | None) -> float | None:
    """두 벡터의 코사인유사도. 길이 불일치/빈 벡터/영벡터면 None(비교 불가)."""
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return None
    return dot / (norm_a * norm_b)


def _rerank_by_narrative_similarity(
    records: list[dict[str, Any]], query_embedding: list[float]
) -> list[dict[str, Any]]:
    """narrative 임베딩 코사인유사도 내림차순 재순위 (docs/RAG-corpus.md §6-2).

    # debt: 후보 집합 전체를 순수 Python으로 O(n) 스캔한다(sqlite_vec ANN 미사용).
    # 코퍼스 규모가 커져 스캔 비용이 문제되면 episode_vec류 가상테이블 검색으로 승격.
    embedding이 없는 레코드는 유사도 -inf 취급으로 순위 맨 뒤로 밀린다.
    """
    scored = [
        (_cosine_similarity(r.get("embedding"), query_embedding), r) for r in records
    ]
    scored.sort(key=lambda pair: pair[0] if pair[0] is not None else float("-inf"), reverse=True)
    return [r for _, r in scored]


def episode_to_corpus_records(episode: dict[str, Any]) -> list[dict[str, Any]]:
    """enriched episode → 코퍼스 학습레코드 리스트.

    위협 판정(threat_judgments) 하나당 학습레코드 1건. 판정이 없으면 빈 리스트.
    → 매핑 규칙: docs/RAG-corpus.md §3, §4.
    """
    mission_id = episode.get("mission_id")
    mission_context = episode.get("mission_context")
    if not mission_id or not mission_context:
        raise ValueError("episode requires 'mission_id' and 'mission_context'")

    records: list[dict[str, Any]] = []
    for judgment in episode.get("threat_judgments") or []:
        threat_event = judgment.get("threat_event")
        if not threat_event:
            continue  # 위협 식별 불가 → 회수 키 성립 안 함
        records.append(
            {
                "mission_id": mission_id,
                "raw_log_ref": episode.get("raw_log_ref"),
                "mission_context": mission_context,
                "posture": episode.get("posture"),
                "threat_event": threat_event,
                "confidence": judgment.get("confidence"),
                "outcome": episode.get("outcome"),
                "corridor_region": episode.get("corridor_region"),
                "kill_chain_stage": judgment.get("kill_chain_stage"),
                "narrative_status": episode.get("narrative_status"),
                "narrative": episode.get("narrative"),
                "embedding": episode.get("embedding"),
                "ts": episode.get("ts"),
            }
        )
    return records


class CorpusStore:
    """corpus_record CRUD + 메타필터 회수 (store.py:EpisodeStore 스타일 미러링)."""

    def __init__(self, db_path: str | Path = "corpus.db") -> None:
        self.db_path = Path(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._migrate_round3_columns()
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_corpus_narrative_status"
            " ON corpus_record (narrative_status)"
        )
        self._conn.commit()

    def _migrate_round3_columns(self) -> None:
        """라운드1/2가 만든 기존 corpus_record에 라운드3 컬럼을 추가한다 (idempotent).

        신규 DB는 schema.sql의 CREATE TABLE로 이미 컬럼을 갖고 있으므로 no-op.
        → #166 Codex P2.
        """
        existing = {
            row[1] for row in self._conn.execute("PRAGMA table_info(corpus_record)")
        }
        for column in _ROUND3_NEW_COLUMNS:
            if column not in existing:
                self._conn.execute(
                    f"ALTER TABLE corpus_record ADD COLUMN {column} TEXT"
                )

    def upsert_records(self, records: list[dict[str, Any]]) -> int:
        """학습레코드 리스트 삽입/갱신 ((mission_id, threat_event) 기준 멱등). 건수 반환."""
        for record in records:
            self._conn.execute(
                """
                INSERT INTO corpus_record (
                    mission_id, raw_log_ref, mission_context, posture,
                    threat_event, confidence, outcome, corridor_region,
                    kill_chain_stage, narrative_status, narrative, embedding, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (mission_id, threat_event) DO UPDATE SET
                    raw_log_ref = excluded.raw_log_ref,
                    mission_context = excluded.mission_context,
                    posture = excluded.posture,
                    confidence = excluded.confidence,
                    outcome = excluded.outcome,
                    corridor_region = excluded.corridor_region,
                    kill_chain_stage = excluded.kill_chain_stage,
                    narrative_status = excluded.narrative_status,
                    narrative = excluded.narrative,
                    embedding = excluded.embedding,
                    ts = excluded.ts
                """,
                (
                    record["mission_id"],
                    record.get("raw_log_ref"),
                    record["mission_context"],
                    _canonical_posture(record.get("posture")),
                    record["threat_event"],
                    record.get("confidence"),
                    record.get("outcome"),
                    record.get("corridor_region"),
                    record.get("kill_chain_stage"),
                    record.get("narrative_status"),
                    record.get("narrative"),
                    _serialize_embedding(record.get("embedding")),
                    record.get("ts"),
                ),
            )
        self._conn.commit()
        return len(records)

    def ingest_episode(self, episode: dict[str, Any]) -> int:
        """episode 변환 → 저장 편의 메서드. 저장한 학습레코드 건수 반환."""
        return self.upsert_records(episode_to_corpus_records(episode))

    def retrieve(
        self,
        mission_context: str | None = None,
        posture: dict[str, Any] | None = None,
        threat_event: str | None = None,
        top_k: int = 20,
        posture_tolerance: int | None = None,
        narrative_query_embedding: list[float] | None = None,
    ) -> list[dict[str, Any]]:
        """메타필터 회수 (mission_context/posture/threat_event AND). 최신·고확신 우선.

        → 회수 계약: docs/RAG-corpus.md §6. 반환 dict는 학습레코드 스키마(posture는 dict 역직렬화).
        top_k는 0 이상이어야 한다 (음수는 SQLite `LIMIT -1`로 해석되어 전체 반환되므로 거부).
        posture 필터는 기본 정확일치이며, posture_tolerance(정수 ≥ 0)를 주면 근접매칭한다
        (질의 각 키에 대해 |record-query| ≤ tolerance). → 근접 규칙: docs/RAG-corpus.md §6-1.

        `narrative_status='pending'`인 레코드는 항상 제외한다(정책, 끄는 옵션 없음).
        `narrative_query_embedding`을 주면 벡터 백엔드(sqlite_vec) 설치 시 후보를 narrative
        코사인유사도로 재순위한다. 벡터 백엔드 미설치 시 예외 없이 메타필터-only로 하향(degrade).
        → 라운드 3 계약: docs/RAG-corpus.md §6-2.
        """
        if top_k < 0:
            raise ValueError("top_k must be non-negative")
        if posture_tolerance is not None and posture_tolerance < 0:
            raise ValueError("posture_tolerance must be non-negative")

        # 근접매칭은 SQL 문자열 동등비교로 표현 불가 → posture 외 필터로 후보 축소 후 Python 필터.
        posture_near = posture is not None and posture_tolerance is not None
        apply_narrative_rerank = (
            narrative_query_embedding is not None and _VEC_BACKEND_AVAILABLE
        )

        clauses: list[str] = ["(narrative_status IS NULL OR narrative_status != ?)"]
        params: list[Any] = [NARRATIVE_PENDING]
        if mission_context is not None:
            clauses.append("mission_context = ?")
            params.append(mission_context)
        if posture is not None and not posture_near:
            clauses.append("posture = ?")
            params.append(_canonical_posture(posture))
        if threat_event is not None:
            clauses.append("threat_event = ?")
            params.append(threat_event)

        where = f" WHERE {' AND '.join(clauses)}"
        sql = (
            "SELECT mission_id, raw_log_ref, mission_context, posture, threat_event,"
            " confidence, outcome, corridor_region, kill_chain_stage,"
            " narrative_status, narrative, embedding, ts"
            f" FROM corpus_record{where}"
            " ORDER BY ts DESC, confidence DESC"
        )
        if not posture_near and not apply_narrative_rerank:
            sql += " LIMIT ?"
            params.append(top_k)

        rows = self._conn.execute(sql, params).fetchall()
        records = [self._row_to_record(row) for row in rows]
        if posture_near:
            records = [
                r
                for r in records
                if _posture_within(r["posture"], posture, posture_tolerance)
            ]
            if not apply_narrative_rerank:
                records = records[:top_k]
        if apply_narrative_rerank:
            records = _rerank_by_narrative_similarity(records, narrative_query_embedding)[:top_k]
        return records

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["posture"] = (
            json.loads(record["posture"]) if record["posture"] is not None else None
        )
        record["embedding"] = (
            json.loads(record["embedding"]) if record["embedding"] is not None else None
        )
        return record

    def retrieve_semantic(
        self,
        query_text: str,
        *,
        mission_context: str | None = None,
        posture: dict[str, Any] | None = None,
        threat_event: str | None = None,
        top_k: int = 20,
        posture_tolerance: int | None = None,
        model_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """자연어 질의 → 임베딩 모델로 벡터화 → 메타필터 후보를 narrative 유사도로 재순위.

        embedding 모델(선택 의존) 미가용 시 query 벡터가 None → retrieve()가 메타필터-only 로
        자동 하향(하위호환). 순수 advisory 회수 — 결정론 판정 무관(SCC-1).
        """
        # 재순위 백엔드가 없으면 임베딩 자체를 건너뛴다 — 어차피 무시될 벡터를 위해
        # 대형 모델을 로드/다운로드하지 않는다(codex P2).
        query_vec = None
        if _VEC_BACKEND_AVAILABLE:
            import embedding

            query_vec = embedding.embed(query_text, model_name or embedding.DEFAULT_MODEL)
        return self.retrieve(
            mission_context=mission_context,
            posture=posture,
            threat_event=threat_event,
            top_k=top_k,
            posture_tolerance=posture_tolerance,
            narrative_query_embedding=query_vec,
        )

    def close(self) -> None:
        self._conn.close()
