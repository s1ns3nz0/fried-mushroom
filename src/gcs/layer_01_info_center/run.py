"""run — 지상통제센터 AI(layer 01) 오케스트레이터. 2단계.

assemble_draft: 수집 입력 → NLP 해석 → C4I 대조 → 조립 → {draft_brief, signal_cards, warnings}.
finalize: 운용자 승인 게이트. 승인 시 온보드 MissionBrief 확정(+타임스탬프), 미승인 시 pending.

순수 함수 — ts_ms 는 유즈사이트가 주입한다(파이프라인 안에서 시간 조회 금지).
스펙 원칙: AI 는 후보만, 최종 결정은 사람(finalize approved). NLP 는 지시서만 읽음.
"""

from __future__ import annotations

from gcs.layer_01_info_center.assemble import assemble_brief
from gcs.layer_01_info_center.cross_check import cross_check
from gcs.layer_01_info_center.nlp_extract import extract_signals


def _interpret(sig: dict) -> str:
    if sig["signal_type"] == "threat":
        return f"위협 {sig.get('threat')} 후보"
    if sig["signal_type"] == "logistics":
        return f"병참 신호: {sig.get('effect')}"
    return sig["signal_type"]


def _card(sig: dict) -> dict:
    return {
        "source_phrase": sig["source_phrase"],
        "signal_type": sig["signal_type"],
        "interpretation": _interpret(sig),
        "confidence": sig["confidence"],
        "adjust_reason": sig.get("adjust_reason"),  # 대조 조정 이유 (없으면 None)
    }


def assemble_draft(inputs: dict) -> dict:
    """수집 입력 → 브리핑 초안 + 승인용 신호 카드 + 경고."""
    signals = extract_signals(inputs.get("directive_text", ""))
    adjusted, warnings = cross_check(
        signals,
        inputs.get("drone_profile", {}),
        inputs.get("mission_context", ""),
        inputs.get("c4i", {}),
    )
    draft_brief = assemble_brief(inputs)
    return {
        "draft_brief": draft_brief,
        "signal_cards": [_card(s) for s in adjusted],
        "warnings": warnings,
    }


def finalize(draft: dict, approved: bool, ts_ms: int) -> dict:
    """운용자 승인 게이트. 승인 시 온보드 MissionBrief 확정, 미승인 시 pending."""
    if approved:
        return {"mission_brief": draft["draft_brief"], "approved_ts_ms": ts_ms}
    return {
        "status": "pending_approval",
        "signal_cards": draft["signal_cards"],
        "warnings": draft["warnings"],
    }
