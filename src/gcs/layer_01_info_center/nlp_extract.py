"""nlp_extract — 🟡 결정론 키워드룰 지시서 해석 (실 NLP 모델 stub, ADR-002).

지시서 원문(directive_text)만 읽어 위협/병참 신호를 뽑는다 (C4I·GCS 안 봄 — 추적성).
확실성 수식어로 확신도를 정하고, CONFIDENCE_FLOOR 미만은 제외한다(애매한 건 운용자에
안 보임). 실제 NLP 모델로 교체돼도 반환 Signal dict 키는 동일해야 한다.

Signal = {source_phrase, signal_type, threat?|effect?, confidence}.
"""

from __future__ import annotations

import re

CONFIDENCE_FLOOR = 0.7

_BASE = 0.85
_CERTAIN = 0.95
_HEDGE = 0.60

# 확실성 수식어 — 절(clause) 단위로 확신도 상/하향.
_CERTAIN_WORDS = ("확인됨", "확인", "식별", "확정")
_HEDGE_WORDS = ("가능성", "추정", "의심", "미확인")

# (매칭 문구들, signal_type, 부가필드). 하드코딩 룰 테이블 (임의 변경 금지).
_KEYWORD_RULES: list[tuple[tuple[str, ...], str, dict]] = [
    (("저격조", "소화기", "대구경화기", "무장 인원"), "threat", {"threat": "T3"}),
    (("사이버", "재밍", "전자전", "해킹"), "threat", {"threat": "T2"}),
    (("예비기체 없음", "예비드론 없음", "예비 없음"), "logistics", {"effect": "severity_escalate"}),
]

_CLAUSE_SPLIT = re.compile(r"[.\n。]")


def _clause_confidence(clause: str) -> float:
    if any(w in clause for w in _CERTAIN_WORDS):
        return _CERTAIN
    if any(w in clause for w in _HEDGE_WORDS):
        return _HEDGE
    return _BASE


def extract_signals(directive_text: str) -> list[dict]:
    """지시서 원문 → 신호 리스트 (confidence >= CONFIDENCE_FLOOR 만)."""
    signals: list[dict] = []
    for clause in _CLAUSE_SPLIT.split(directive_text or ""):
        conf = _clause_confidence(clause)
        for phrases, signal_type, extra in _KEYWORD_RULES:
            matched = next((p for p in phrases if p in clause), None)
            if matched is None:
                continue
            signals.append(
                {"source_phrase": matched, "signal_type": signal_type, **extra, "confidence": conf}
            )
    return [s for s in signals if s["confidence"] >= CONFIDENCE_FLOOR]
