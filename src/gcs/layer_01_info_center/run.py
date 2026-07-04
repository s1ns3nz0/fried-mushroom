"""run — 지상통제센터 AI(layer 01) 오케스트레이터. 2단계 (라운드2: 풀 METT+TC).

assemble_draft: 수집 입력 → NLP 해석 → C4I 대조 → mettc 조립 → 온보드 투영 브리핑.
  반환 {mettc_state, draft_brief, signal_cards, warnings}.
finalize: 운용자 승인 게이트. 승인 시 온보드 MissionBrief + mettc_state 확정(+ts), 미승인 pending.

순수 함수 — ts_ms 는 유즈사이트가 주입한다(파이프라인 안에서 시간 조회 금지).
스펙 원칙: AI 는 후보만, 최종 결정은 사람(finalize approved). NLP 는 지시서만 읽음.
하위호환: flat set_mission(corridor 형·레거시 c4i)도 수용 — mettc_assemble/normalize 흡수.
"""

from __future__ import annotations

import os
from typing import Any

from gcs.layer_01_info_center.briefing_advisor import build_briefing_advisory
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


def assemble_draft(inputs: dict, *, store: Any = None, ts_ms: int = 0) -> dict:
    """수집 입력 → mettc 상태 + 온보드 투영 브리핑 + 승인용 신호 카드 + 경고.

    store: CorpusStore 선택 주입. None 이면 briefing_advisory 를 생략(무-DB graceful).
    ts_ms: advisory generated_ts 용 타임스탬프(기본 0, 운용 시 유즈사이트에서 주입).
    inputs['use_nlp_model']=True(또는 env GCS_NLP_MODEL) 시 NLP 시맨틱 위협 보강 opt-in.
    """
    use_nlp = bool(inputs.get("use_nlp_model")) or os.environ.get("GCS_NLP_MODEL") == "1"
    signals = extract_signals(inputs.get("directive_text", ""), use_nlp_model=use_nlp)
    c4i = normalize_c4i(inputs.get("c4i"))
    adjusted, warnings = cross_check(
        signals,
        inputs.get("drone_profile", {}),
        inputs.get("mission_context", ""),
        c4i,
    )
    state = assemble_mettc(inputs, c4i, adjusted)
    draft_brief = project_onboard_brief(state, sortie_id=inputs["sortie_id"])

    # RAG advisory — store 주입 시에만 산출. 결정론 판정/신호 무변경(SCC-1).
    advisory: dict | None = None
    if store is not None:
        advisory = build_briefing_advisory(
            adjusted,
            inputs.get("mission_context"),
            inputs.get("posture"),
            store,
            generated_ts=ts_ms,
        )

    result: dict[str, Any] = {
        "mettc_state": state,
        "draft_brief": draft_brief,
        "signal_cards": [_card(s) for s in adjusted],
        "warnings": warnings,
        "briefing_advisory": advisory,
    }
    return result


# 운용자가 승인 시 수정 가능한 GCS-소유 결정필드 → 기대 타입 (sortie_id=식별자·온보드-소유 제외).
# 타입 검증으로 형태가 틀린 오버라이드(예: posture=정수)가 하류 crash 를 내지 않게 한다.
_OVERRIDABLE_FIELDS: dict[str, type | tuple[type, ...]] = {
    "mission_context": str,
    "posture": dict,
    "drone_profile": dict,
    "corridor": dict,
    "weights": dict,
}
# dict 필드는 replace 아닌 merge — 부분 오버라이드(예: posture={"defcon":2})가 나머지 키를
# 떨어뜨려 불완전 브리핑을 만들지 않게 한다 (codex P2).
_MERGE_FIELDS = frozenset({"posture", "drone_profile", "corridor", "weights"})
# mission_context 유효값 (온보드 MISSION_CONTEXTS 미러 — 레이어 경계상 onboard 상수 import 금지).
# 미러 드리프트 방지: 값 추가 시 shared/constants.MISSION_CONTEXTS 와 동기.
_VALID_MISSION_CONTEXTS = frozenset({"정찰", "타격", "호송", "수송"})


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
        if not isinstance(value, _OVERRIDABLE_FIELDS[field]):
            raise ValueError(
                f"override {field!r} 타입 오류: {_OVERRIDABLE_FIELDS[field].__name__} 기대, {type(value).__name__} 받음")
        if field == "mission_context" and value not in _VALID_MISSION_CONTEXTS:
            raise ValueError(f"override mission_context 무효: {value!r} (유효: {sorted(_VALID_MISSION_CONTEXTS)})")
        old = brief.get(field)
        # dict 필드는 기존 완전값에 병합 → 부분 오버라이드가 키를 떨어뜨리지 않음.
        new = {**old, **value} if field in _MERGE_FIELDS and isinstance(old, dict) else value
        applied[field] = {"from": old, "to": new}
        brief[field] = new

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
