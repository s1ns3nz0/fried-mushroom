"""sitrep — 🔵 파생 읽기전용. 운용자 상황판단 리포트(SITREP).

현재 사이클의 결정 근거(`explain.explain_cycle`)와 최근 궤적 조기경보(`trend.assess_threat_trend`)를
융합해, 운용자가 한눈에 볼 **주의수준**과 헤드라인·권고를 만든다. "지금 무슨 결정을 왜 내렸고
(explain), 위협이 어디로 가고 있으며(trend), 그래서 얼마나 주목해야 하는가(attention_level)"를
한 화면으로 제공한다.

주의수준(ROUTINE < MONITOR < ALERT < ACT)은 현재 RAC × 궤적 악화 × 위협 존재를 융합한
단일 실행지표다 — 그러나 어디까지나 참고용이다.

CRITICAL (SCC-1): advisory 만 산출한다. 결정을 바꾸지 않고 입력을 변이하지 않으며 결정론
로직·상수를 쓰지 않는다(RAC_ORDER 읽기전용만 참조).
"""

from __future__ import annotations

from typing import Any

from onboard.explain import explain_cycle
from onboard.shared.constants import RAC_ORDER
from onboard.trend import assess_threat_trend

_LEVEL_ORDER = ("ROUTINE", "MONITOR", "ALERT", "ACT")

# RAC_ORDER: High=1, Serious=2, Medium=3, Low=4. 심각(즉시 주목) = High/Serious.
_SEVERE_MAX_RANK = 2


def _rac_from_explain(current: dict[str, Any]) -> str | None:
    for s in current.get("steps", []):
        if s.get("layer") == "05":
            return s.get("detail", {}).get("rac")
    return None


def _attention_level(primary_te, rac, flight_action, trend) -> str:
    rank = RAC_ORDER.get(rac) if rac else None
    severe = rank is not None and rank <= _SEVERE_MAX_RANK
    acting = flight_action not in (None, "MAINTAIN")
    if not primary_te:
        return "ROUTINE"
    if trend.get("level") == "critical" or (severe and acting):
        return "ACT"
    if trend.get("escalating") or trend.get("level") == "warning" or severe:
        return "ALERT"
    return "MONITOR"


def build_sitrep(
    results: list[dict[str, Any]],
    *,
    window: int | None = None,
) -> dict[str, Any]:
    """사이클 결과 시퀀스(오래된→최신) → 운용자 SITREP.

    반환: {attention_level, headline, flight_action, primary_threat_event,
           current(explain), trend(assess), recommendation, advisory_only}
    """
    seq = list(results or [])
    latest = seq[-1] if seq else {}
    current = explain_cycle(latest)
    trend = assess_threat_trend(seq, window=window)

    primary_te = current.get("primary_threat_event")
    flight_action = current.get("flight_action")
    rac = _rac_from_explain(current)
    level = _attention_level(primary_te, rac, flight_action, trend)

    if not primary_te:
        headline = f"[{level}] 위협 없음 — {flight_action or '대기'}"
        rec = "정상 운용. 특이 조치 불요."
    else:
        desc = current["steps"][1]["detail"].get("threat_desc", "") if len(current.get("steps", [])) > 1 else ""
        headline = f"[{level}] {primary_te}({desc}) RAC={rac} → {flight_action}"
        if level == "ACT":
            rec = f"즉시 주목 — {flight_action} 실행 중, 궤적 {trend.get('level')}. 운용자 확인 요망."
        elif level == "ALERT":
            rec = f"경계 — {'악화 궤적' if trend.get('escalating') else '고위험'} 감지. 상황 주시."
        else:
            rec = "감시 — 위협 존재하나 안정. 추이 관찰."

    return {
        "attention_level": level,
        "headline": headline,
        "flight_action": flight_action,
        "primary_threat_event": primary_te,
        "current": current,
        "trend": trend,
        "recommendation": rec,
        "advisory_only": True,
    }
