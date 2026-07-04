"""narrative_embed — 무-의존 결정론 n-gram 임베딩 (#347).

ML 라이브러리 없이 표준라이브러리만으로 결정론·L2-정규화 벡터를 생성하고,
유사 텍스트가 높은 코사인유사도를 가짐을 검증한다.

tests/infra/conftest.py 가 infra/log 를 sys.path 에 추가한다.
"""

import math

import pytest

from narrative_embed import embed_narrative


# ── 기본 계약 ─────────────────────────────────────────────────────────────────


def test_returns_list_of_float():
    vec = embed_narrative("적 저격조 조우")
    assert isinstance(vec, list), "list 반환 기대"
    assert all(isinstance(x, float) for x in vec), "요소가 모두 float"
    assert len(vec) > 0, "빈 벡터 불가"


def test_empty_text_returns_none():
    assert embed_narrative("") is None


def test_none_input_returns_none():
    assert embed_narrative(None) is None


def test_whitespace_only_returns_none():
    assert embed_narrative("   ") is None


# ── L2 정규화 ─────────────────────────────────────────────────────────────────


def test_l2_normalized():
    vec = embed_narrative("저격조 확인됨. 고도 상승 회피 기동.")
    assert vec is not None
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-6, f"L2 정규화 기대 (norm={norm:.6f})"


def test_l2_normalized_for_short_text():
    vec = embed_narrative("T3")
    assert vec is not None
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-6


# ── 결정론 ────────────────────────────────────────────────────────────────────


def test_deterministic_same_text():
    """같은 텍스트 → 같은 벡터 (호출 간 랜덤성 없음)."""
    text = "적 저격조 T3 확인됨 고도 상승 회피"
    assert embed_narrative(text) == embed_narrative(text)


def test_deterministic_across_calls():
    """10회 반복 호출해도 동일한 결과."""
    text = "민가 인접 구역 ROE 주의"
    first = embed_narrative(text)
    for _ in range(9):
        assert embed_narrative(text) == first


# ── 유사도 순서 ────────────────────────────────────────────────────────────────


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def test_similar_texts_have_higher_cosine_than_unrelated():
    """유사 narrative 간 코사인유사도 > 전혀 다른 텍스트와의 유사도."""
    base = embed_narrative("저격조 T3 확인됨. 고도 상승 회피 기동.")
    similar = embed_narrative("저격조 T3 조우. 고도 상승 기동 회피.")
    unrelated = embed_narrative("기상 이상. 배터리 잔량 부족. RTB 결정.")
    assert base and similar and unrelated
    sim_similar = _cosine(base, similar)
    sim_unrelated = _cosine(base, unrelated)
    assert sim_similar > sim_unrelated, (
        f"유사 텍스트 유사도({sim_similar:.4f}) > 비관련 유사도({sim_unrelated:.4f}) 기대"
    )


def test_identical_text_has_cosine_one():
    """동일 텍스트 → 코사인유사도 ≈ 1.0."""
    text = "사이버 재밍 T2 식별. 전자전 대응 필요."
    vec = embed_narrative(text)
    assert vec is not None
    sim = _cosine(vec, vec)
    assert abs(sim - 1.0) < 1e-6, f"자기 코사인 1.0 기대 (got {sim:.6f})"


def test_different_texts_have_different_vectors():
    """전혀 다른 텍스트는 다른 벡터를 생성해야 한다."""
    v1 = embed_narrative("저격조 T3 조우")
    v2 = embed_narrative("배터리 부족 RTB")
    assert v1 != v2
