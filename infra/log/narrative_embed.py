"""narrative_embed — 무-의존 결정론 n-gram 해싱 임베딩 (#347).

표준라이브러리(hashlib)만으로 텍스트 → 고정차원 L2-정규화 벡터를 생성한다.
ML 라이브러리(sentence-transformers 등) 없이 zero-dep 로 동작한다.

특성:
- 결정론: 같은 입력 → 같은 벡터 (PYTHONHASHSEED 무관, hashlib.md5 사용)
- L2 정규화: 코사인유사도 = 내적 (corpus._rerank_by_narrative_similarity 와 정합)
- 유사 텍스트: 겹치는 n-gram 비율이 높을수록 코사인유사도 높음

SCC-1: 이 모듈은 advisory 검색 채널 전용이다. 결정론 RAC/위협 판정에 영향 없음.
"""

from __future__ import annotations

import hashlib
import math

# 임베딩 차원 — 256은 zero-dep 해싱 정밀도와 메모리의 실용적 균형점.
EMBED_DIM = 256

# n-gram 크기 범위 — 2·3·4-gram 조합이 문자열 유사도를 가장 잘 포착한다.
_NGRAM_SIZES = (2, 3, 4)


def _stable_hash(s: str) -> int:
    """프로세스 간 결정론 해시 (hashlib.md5, PYTHONHASHSEED 무관)."""
    return int(hashlib.md5(s.encode("utf-8")).hexdigest(), 16)


def embed_narrative(text: str | None, dim: int = EMBED_DIM) -> list[float] | None:
    """텍스트 → L2-정규화 n-gram 해싱 벡터. 빈/None 입력 시 None.

    동일 텍스트는 항상 동일 벡터를 반환한다(결정론).
    유사한 텍스트(겹치는 n-gram 多)는 높은 코사인유사도를 가진다.
    """
    if not text or not text.strip():
        return None

    vec = [0.0] * dim
    for n in _NGRAM_SIZES:
        for i in range(len(text) - n + 1):
            gram = text[i : i + n]
            idx = _stable_hash(gram) % dim
            vec[idx] += 1.0

    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return [0.0] * dim
    return [x / norm for x in vec]
