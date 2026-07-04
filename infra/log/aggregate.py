"""raw_log → episode_index 구조화집계 (스켈레톤).

수신·저장된 raw_log에서 검색용 구조화필드를 **완전자동** 집계하고,
narrative LLM 초안을 생성한다(자리표시 스텁). 사람 승인 전까지 `pending`.

워크플로우(docs/architecture/ground/02-learning-rag.md):
1. 임무종료 → raw_log 파일 기록 (collector.py)
2. 자동스크립트가 구조화필드(terrain_composition/threat_events/outcome) 즉시 집계 + narrative 초안  ← 여기
3. 오퍼레이터 승인 → episode_index 편입(검색가능) (store.py)
4. 미승인(pending)은 검색에서 완전 제외 — 감사가능성 원칙

집계 산출 = episode_index 레코드(narrative_status="pending"), store.upsert로 전달.
"""

from __future__ import annotations

from typing import Any

# narrative_status 값 (pending은 검색 코퍼스에서 제외).
NARRATIVE_PENDING = "pending"
NARRATIVE_CONFIRMED = "human_confirmed"


def aggregate_terrain_composition(gps_track: list[dict[str, Any]]) -> dict[str, float]:
    """gps_track의 terrain_class 분포를 비율로 집계.

    예: {"ridge": 0.4, "valley": 0.5, "open": 0.1} (합 ≈ 1.0).
    """
    # TODO: terrain_class별 카운트 → 정규화 비율.
    raise NotImplementedError


def aggregate_threat_events(threat_modeling_log: list[dict[str, Any]]) -> list[str]:
    """threat_modeling_log에서 등장한 threat_event 집합을 추출.

    예: ["T3", "T1"] (중복 제거, 등장 순/빈도순).
    """
    # TODO: threat_event 유니크 추출.
    raise NotImplementedError


def aggregate_outcome(raw_log: dict[str, Any]) -> str:
    """임무 결과(outcome) 판정.

    예: "rtb_success". risk_assessment_log·aircraft_state_series 말미로 추정.
    """
    # TODO: 최종 상태 기반 outcome 라벨링.
    raise NotImplementedError


def draft_narrative(raw_log: dict[str, Any]) -> str:
    """raw_log 요약 → narrative LLM 초안(자리표시 스텁).

    로컬/원격 LLM으로 임무 서술 초안 생성. 생성물은 narrative_status=pending으로
    저장되며 사람 승인 전까지 검색 코퍼스에서 제외된다.
    """
    # TODO: 시계열 요약 → 프롬프트 → LLM 호출. Phase 2 연동.
    raise NotImplementedError


def build_episode_index(raw_log: dict[str, Any], raw_log_ref: str) -> dict[str, Any]:
    """raw_log → episode_index 레코드 조립(narrative_status="pending").

    구조화필드 자동집계 + narrative 초안 + raw_log_ref 포인터를 묶는다.
    embedding은 별도(로컬 sentence-transformer) — store 편입 단계에서 채움.
    → 스키마: docs/architecture/ground/02-learning-rag.md (episode_index)
    """
    # TODO: 아래 필드 채워 반환. corridor_region은 mettc/corridor에서 파생.
    return {
        "mission_id": raw_log.get("mission_id"),
        "raw_log_ref": raw_log_ref,
        "corridor_region": None,        # TODO: corridor → region 코드(예: "KR-hill-07")
        "threat_events": None,          # TODO: aggregate_threat_events
        "outcome": None,                # TODO: aggregate_outcome
        "terrain_composition": None,    # TODO: aggregate_terrain_composition
        "narrative": None,              # TODO: draft_narrative
        "narrative_status": NARRATIVE_PENDING,
        "embedding": None,              # TODO: 승인 후 sentence-transformer 임베딩
        "ts": None,                     # TODO: 집계 시각
    }
