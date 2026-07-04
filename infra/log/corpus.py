"""RAG 코퍼스 — episode → 학습레코드 변환 + 저장/회수 (라운드 1).

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
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def _canonical_posture(posture: Any) -> str | None:
    """posture dict를 표준 JSON(정렬 키)으로 직렬화 — 회수 시 정확일치 비교용."""
    if posture is None:
        return None
    return json.dumps(posture, sort_keys=True, ensure_ascii=False)


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

    def upsert_records(self, records: list[dict[str, Any]]) -> int:
        """학습레코드 리스트 삽입/갱신 ((mission_id, threat_event) 기준 멱등). 건수 반환."""
        for record in records:
            self._conn.execute(
                """
                INSERT INTO corpus_record (
                    mission_id, raw_log_ref, mission_context, posture,
                    threat_event, confidence, outcome, corridor_region,
                    kill_chain_stage, ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (mission_id, threat_event) DO UPDATE SET
                    raw_log_ref = excluded.raw_log_ref,
                    mission_context = excluded.mission_context,
                    posture = excluded.posture,
                    confidence = excluded.confidence,
                    outcome = excluded.outcome,
                    corridor_region = excluded.corridor_region,
                    kill_chain_stage = excluded.kill_chain_stage,
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
    ) -> list[dict[str, Any]]:
        """메타필터 회수 (mission_context/posture/threat_event AND). 최신·고확신 우선.

        → 회수 계약: docs/RAG-corpus.md §6. 반환 dict는 학습레코드 스키마(posture는 dict 역직렬화).
        top_k는 0 이상이어야 한다 (음수는 SQLite `LIMIT -1`로 해석되어 전체 반환되므로 거부).
        posture 필터는 기본 정확일치이며, posture_tolerance(정수 ≥ 0)를 주면 근접매칭한다
        (질의 각 키에 대해 |record-query| ≤ tolerance). → 근접 규칙: docs/RAG-corpus.md §6-1.
        """
        if top_k < 0:
            raise ValueError("top_k must be non-negative")
        if posture_tolerance is not None and posture_tolerance < 0:
            raise ValueError("posture_tolerance must be non-negative")

        # 근접매칭은 SQL 문자열 동등비교로 표현 불가 → posture 외 필터로 후보 축소 후 Python 필터.
        posture_near = posture is not None and posture_tolerance is not None

        clauses: list[str] = []
        params: list[Any] = []
        if mission_context is not None:
            clauses.append("mission_context = ?")
            params.append(mission_context)
        if posture is not None and not posture_near:
            clauses.append("posture = ?")
            params.append(_canonical_posture(posture))
        if threat_event is not None:
            clauses.append("threat_event = ?")
            params.append(threat_event)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT mission_id, raw_log_ref, mission_context, posture, threat_event,"
            " confidence, outcome, corridor_region, kill_chain_stage, ts"
            f" FROM corpus_record{where}"
            " ORDER BY ts DESC, confidence DESC"
        )
        if not posture_near:
            sql += " LIMIT ?"
            params.append(top_k)

        rows = self._conn.execute(sql, params).fetchall()
        records = [self._row_to_record(row) for row in rows]
        if posture_near:
            records = [
                r
                for r in records
                if _posture_within(r["posture"], posture, posture_tolerance)
            ][:top_k]
        return records

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["posture"] = (
            json.loads(record["posture"]) if record["posture"] is not None else None
        )
        return record

    def close(self) -> None:
        self._conn.close()
