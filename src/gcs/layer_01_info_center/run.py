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


# 운용자가 승인 시 수정 가능한 GCS-소유 결정필드 (sortie_id=식별자 제외, 온보드-소유 필드 제외).
_OVERRIDABLE_FIELDS = frozenset({"mission_context", "posture", "drone_profile", "corridor", "weights"})


def finalize(draft: dict, approved: bool, ts_ms: int, overrides: dict | None = None) -> dict:
    """운용자 승인 게이트. 승인 시 온보드 MissionBrief + mettc_state 확정, 미승인 pending.

    overrides: 운용자가 승인 시 수정하는 결정필드 {field: value} (AI 초안을 사람이 필드단위 확정).
    _OVERRIDABLE_FIELDS 로 제한 — 미지/식별자/온보드-소유 필드 주입 금지(SCC-1·레이어 계약).
    적용 내역은 applied_overrides({field: {from, to}}) 로 감사기록. 원본 draft 는 변형하지 않는다.
    """
    if overrides and not approved:
        raise ValueError("overrides require approved=True (미승인 브리핑엔 확정필드가 없음)")
    if not approved:
        return {
            "status": "pending_approval",
            "signal_cards": draft["signal_cards"],
            "warnings": draft["warnings"],
        }

    brief = dict(draft["draft_brief"])
    applied: dict = {}
    for field, value in (overrides or {}).items():
        if field not in _OVERRIDABLE_FIELDS:
            raise ValueError(f"override 불가 필드: {field!r} (허용: {sorted(_OVERRIDABLE_FIELDS)})")
        applied[field] = {"from": brief.get(field), "to": value}
        brief[field] = value

    result = {
        "mission_brief": brief,
        "approved_ts_ms": ts_ms,
    }
    if applied:
        # 오버라이드된 브리핑이 정본 — AI 초안 mettc_state 는 해당 필드에서 불일치하므로 omit
        # (Codex P2: stale state 노출 방지). 감사기록은 applied_overrides 로 보존.
        result["applied_overrides"] = applied
    else:
        result["mettc_state"] = draft.get("mettc_state")
    return result
