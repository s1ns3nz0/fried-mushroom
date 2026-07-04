"""run — 지상통제센터 AI(layer 01) 오케스트레이터. 2단계 (라운드2: 풀 METT+TC).

assemble_draft: 수집 입력 → NLP 해석 → C4I 대조 → mettc 조립 → 온보드 투영 브리핑.
  반환 {mettc_state, draft_brief, signal_cards, warnings}.
finalize: 운용자 승인 게이트. 승인 시 온보드 MissionBrief + mettc_state 확정(+ts), 미승인 pending.

순수 함수 — ts_ms 는 유즈사이트가 주입한다(파이프라인 안에서 시간 조회 금지).
스펙 원칙: AI 는 후보만, 최종 결정은 사람(finalize approved). NLP 는 지시서만 읽음.
하위호환: flat set_mission(corridor 형·레거시 c4i)도 수용 — mettc_assemble/normalize 흡수.
"""

from __future__ import annotations

from gcs.layer_01_info_center.c4i_schema import normalize_c4i
from gcs.layer_01_info_center.cross_check import cross_check
from gcs.layer_01_info_center.mettc_assemble import assemble_mettc
from gcs.layer_01_info_center.nlp_extract import extract_signals
from gcs.layer_01_info_center.project_brief import project_onboard_brief


def _interpret(sig: dict) -> str:
    st = sig["signal_type"]
    if st == "threat":
        return f"위협 {sig.get('threat')} 후보"
    if st == "severity":
        return f"심각도 신호({sig.get('domain')})"
    if st == "logistics":
        return f"병참 신호: {sig.get('effect')}"
    if st == "civil":
        return "민간지역 주의(ROE)"
    if st == "mission_purpose":
        return f"임무목적 추출: {sig.get('purpose')}"
    return st


def _card(sig: dict) -> dict:
    return {
        "source_phrase": sig["source_phrase"],
        "signal_type": sig["signal_type"],
        "interpretation": _interpret(sig),
        "confidence": sig["confidence"],
        "adjust_reason": sig.get("adjust_reason"),  # 대조 조정 이유 (없으면 None)
    }


def assemble_draft(inputs: dict) -> dict:
    """수집 입력 → mettc 상태 + 온보드 투영 브리핑 + 승인용 신호 카드 + 경고."""
    signals = extract_signals(inputs.get("directive_text", ""))
    c4i = normalize_c4i(inputs.get("c4i"))
    adjusted, warnings = cross_check(
        signals,
        inputs.get("drone_profile", {}),
        inputs.get("mission_context", ""),
        c4i,
    )
    state = assemble_mettc(inputs, c4i, adjusted)
    draft_brief = project_onboard_brief(state, sortie_id=inputs["sortie_id"])
    return {
        "mettc_state": state,
        "draft_brief": draft_brief,
        "signal_cards": [_card(s) for s in adjusted],
        "warnings": warnings,
    }


def finalize(draft: dict, approved: bool, ts_ms: int) -> dict:
    """운용자 승인 게이트. 승인 시 온보드 MissionBrief + mettc_state 확정, 미승인 pending."""
    if approved:
        return {
            "mission_brief": draft["draft_brief"],
            "mettc_state": draft.get("mettc_state"),
            "approved_ts_ms": ts_ms,
        }
    return {
        "status": "pending_approval",
        "signal_cards": draft["signal_cards"],
        "warnings": draft["warnings"],
    }
