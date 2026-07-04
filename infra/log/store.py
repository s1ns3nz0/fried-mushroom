"""episode_index 저장/검색 인터페이스 (스켈레톤).

SQLite(schema.sql) + sqlite-vec 벡터확장 위에서 episode_index를 관리한다.
- 저장: aggregate.build_episode_index 산출물 upsert (초기 narrative_status='pending')
- 승인: 오퍼레이터 확인 → 'human_confirmed' 전환 + embedding 채움 → 검색 코퍼스 편입
- 검색: 메타필터(threat_events/corridor_region) → 벡터 유사도 → 임계미달 시 1회 재검색

pending은 검색에서 완전 제외(감사가능성 원칙).
→ 스키마: docs/architecture/ground/02-learning-rag.md · schema.sql
→ 소비처: ground/rag (임무해석 카탈로그매칭에 유사 사례 주입)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class EpisodeStore:
    """episode_index CRUD + 하이브리드 검색(메타필터 + 벡터유사도) 인터페이스."""

    def __init__(self, db_path: str | Path = "episode_index.db") -> None:
        # TODO: sqlite3 연결, schema.sql 적용, sqlite-vec 확장 로드.
        self.db_path = Path(db_path)

    def upsert(self, episode: dict[str, Any]) -> None:
        """episode_index 레코드 삽입/갱신 (mission_id 기준).

        aggregate.build_episode_index 산출물을 그대로 받는다.
        신규는 narrative_status='pending'으로 편입(검색 제외 상태).
        """
        # TODO: INSERT ... ON CONFLICT(mission_id) DO UPDATE. JSON 필드 직렬화.
        raise NotImplementedError

    def confirm(self, mission_id: str, embedding: list[float]) -> None:
        """오퍼레이터 승인 → narrative_status='human_confirmed' + embedding 저장.

        승인 시점에 로컬 sentence-transformer 임베딩을 채워 검색 코퍼스에 편입.
        """
        # TODO: UPDATE narrative_status, embedding WHERE mission_id. episode_vec에도 반영.
        raise NotImplementedError

    def search(
        self,
        query_embedding: list[float],
        threat_events: list[str] | None = None,
        corridor_region: str | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """메타필터 → 벡터 유사도 검색 (human_confirmed만).

        1) threat_events/corridor_region으로 후보 축소(메타필터)
        2) query_embedding과 벡터 유사도 top_k
        3) 유사도 임계 미달 시 검색어 재구성 후 1회 재검색은 호출측(ground/rag) 책임.
        """
        # TODO: narrative_status='human_confirmed' 필터 + 메타필터 + episode_vec MATCH.
        raise NotImplementedError

    def get(self, mission_id: str) -> dict[str, Any] | None:
        """단건 조회 (mission_id)."""
        # TODO: SELECT ... WHERE mission_id.
        raise NotImplementedError
