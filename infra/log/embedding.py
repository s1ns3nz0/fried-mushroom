"""narrative 임베딩 모델 — 텍스트 → 벡터 (RAG 라운드 3 벡터 하이브리드 재순위의 입력).

프로젝트 첫 실제 ML 모델. sentence-transformers 는 **선택 의존**이며, 미설치/로드 실패 시
`embed()` 는 None 을 반환한다 → `CorpusStore` 는 메타필터-only 로 자동 하향(하위호환).

SCC-1(CLAUDE.md CRITICAL): 임베딩은 순수 **advisory 검색(유사 과거사례 회수)** 용이며,
결정론 RAC/위협 판정에 어떤 영향도 주지 않는다. 모델은 이 경계 밖에서만 쓰인다.

설계 정본: docs/RAG-corpus.md §6-2 (narrative 임베딩 코사인 재순위).
"""

from __future__ import annotations

import functools

# 다국어(한국어 narrative) 384차원. 도메인 텍스트가 한국어라 다국어 모델 기본값.
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@functools.lru_cache(maxsize=4)
def _load(model_name: str):
    """모델 1회 로드(프로세스 캐시). 의존성/가중치/네트워크 문제 시 None."""
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None
    try:
        return SentenceTransformer(model_name)
    except Exception:
        # 가중치 다운로드 실패/네트워크 부재 등 — 조용히 하향(선택 의존 계약).
        return None


def embed_available(model_name: str = DEFAULT_MODEL) -> bool:
    """임베딩 모델을 실제로 로드할 수 있는지."""
    return _load(model_name) is not None


def embed(text: str | None, model_name: str = DEFAULT_MODEL) -> list[float] | None:
    """텍스트 → L2 정규화 임베딩 list[float]. 빈 텍스트/모델 미가용 시 None.

    정규화 벡터라 코사인유사도 = 내적 (corpus._rerank_by_narrative_similarity 와 정합).
    """
    if not text:
        return None
    model = _load(model_name)
    if model is None:
        return None
    try:
        vec = model.encode([text], normalize_embeddings=True)[0]
    except Exception:
        return None
    return [float(x) for x in vec]
