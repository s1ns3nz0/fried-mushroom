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
# 라운드2 확장: severity(화력)/logistics-resupply/civil — 대조표 ②③④ 신호원.
_KEYWORD_RULES: list[tuple[tuple[str, ...], str, dict]] = [
    (("저격조", "소화기", "대구경화기", "무장 인원"), "threat", {"threat": "T3"}),
    (("사이버", "재밍", "전자전", "해킹"), "threat", {"threat": "T2"}),
    (("예비기체 없음", "예비드론 없음", "예비 없음"), "logistics", {"effect": "severity_escalate"}),
    (("박격포", "대공", "포병", "대구경"), "severity", {"effect": "severity_escalate", "domain": "firepower"}),
    (("재보급", "보급 지연"), "logistics", {"effect": "severity_escalate", "domain": "resupply"}),
    (("민가", "민간", "시가지", "주거"), "civil", {"effect": "roe_caution"}),
]

# 임무목적 언급 — 온보드 mission_context 어휘 동일 (대조표 ⑤ 신호원). 첫 언급만 채택.
_PURPOSE_WORDS = ("정찰", "타격", "호송", "수송")

_CLAUSE_SPLIT = re.compile(r"[.\n。]")


def _semantic_threat(clause: str):
    """NLP 모델 위협 분류 위임 — 모델 미가용/미설치 시 None(키워드 폴백)."""
    try:
        from gcs.layer_01_info_center import nlp_model
    except ImportError:
        return None
    return nlp_model.classify_threat(clause)


def _clause_confidence(clause: str) -> float:
    if any(w in clause for w in _CERTAIN_WORDS):
        return _CERTAIN
    if any(w in clause for w in _HEDGE_WORDS):
        return _HEDGE
    return _BASE


def extract_signals(directive_text: str, *, use_nlp_model: bool = False) -> list[dict]:
    """지시서 원문 → 신호 리스트 (confidence >= CONFIDENCE_FLOOR 만).

    키워드 룰이 기본(결정론, 재현성). `use_nlp_model=True` 이고 NLP 모델(선택 의존)이 가용하면,
    키워드가 위협을 못 잡은 절을 시맨틱 유사도로 보강한다(동의어/의역 recall). 기본 False —
    설치된 패키지에 따라 결과가 달라지지 않게(CI 재현성). run.py 가 운용 설정으로 opt-in.
    """
    signals: list[dict] = []
    purpose_taken = False
    for clause in _CLAUSE_SPLIT.split(directive_text or ""):
        conf = _clause_confidence(clause)
        keyword_threat = False
        for phrases, signal_type, extra in _KEYWORD_RULES:
            matched = next((p for p in phrases if p in clause), None)
            if matched is None:
                continue
            if signal_type == "threat":
                keyword_threat = True
            signals.append(
                {"source_phrase": matched, "signal_type": signal_type, **extra, "confidence": conf}
            )
        # 키워드가 위협을 못 잡은 절 → NLP 모델 시맨틱 보강(opt-in, AI 강화판). 빈 절 제외.
        if use_nlp_model and not keyword_threat and clause.strip():
            model_hit = _semantic_threat(clause)
            if model_hit is not None:
                code, m_conf, seg = model_hit
                # 절의 확실성(hedge "가능성/추정" → 0.60)으로 모델 점수를 캡 — 키워드와 동일하게
                # 애매한 절은 floor 미만으로 필터되게. source_phrase 는 매칭 세그먼트(절보다 좁음).
                # 한계: NLP 세그먼트는 C4I 라벨의 substring 이 아닐 수 있어 cross_check 의 C4I
                # 근거 부스트를 못 받을 수 있음(탐지·표출은 정상) — 엔티티 추출/nlp-aware 매칭은 후속.
                signals.append(
                    {"source_phrase": seg[:40], "signal_type": "threat",
                     "threat": code, "confidence": min(m_conf, conf), "source": "nlp_model"}
                )
        # 임무목적 (대조표 ⑤) — 지시서 내 첫 언급만.
        if not purpose_taken:
            purpose = next((w for w in _PURPOSE_WORDS if w in clause), None)
            if purpose is not None:
                signals.append(
                    {"source_phrase": purpose, "signal_type": "mission_purpose",
                     "purpose": purpose, "confidence": conf}
                )
                purpose_taken = True
    return [s for s in signals if s["confidence"] >= CONFIDENCE_FLOOR]
