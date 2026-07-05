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
from onboard.shared.constants import RAC_ORDER, THREAT_CATALOG
from onboard.trend import assess_threat_trend

_LEVEL_ORDER = ("ROUTINE", "MONITOR", "ALERT", "ACT")
_LEVEL_RANK = {l: i for i, l in enumerate(_LEVEL_ORDER)}

# RAC_ORDER: High=1, Serious=2, Medium=3, Low=4. 심각(즉시 주목) = High/Serious.
_SEVERE_MAX_RANK = 2

# failsafe action → 최소 attention_level (#414). CONTINUE/MONITOR/UNKNOWN 은 영향 없음.
_FAILSAFE_MIN_LEVEL: dict[str, str] = {
    "HOLD": "MONITOR",
    "DR_HOLD": "MONITOR",
    "RTL": "ALERT",
    "EMCON_EVADE": "ALERT",
    "LAND": "ACT",
}


def _rac_from_explain(current: dict[str, Any]) -> str | None:
    for s in current.get("steps", []):
        if s.get("layer") == "05":
            return s.get("detail", {}).get("rac")
    return None


def _failsafe_floor(failsafe: dict[str, Any] | None) -> str:
    """통합 failsafe report → 최소 attention_level. assessable=False/UNKNOWN 이면 ROUTINE."""
    if not failsafe or not failsafe.get("assessable"):
        return "ROUTINE"
    return _FAILSAFE_MIN_LEVEL.get(failsafe.get("recommended_action", ""), "ROUTINE")


def _attention_level(primary_te, rac, flight_action, trend, failsafe: dict[str, Any] | None = None) -> str:
    rank = RAC_ORDER.get(rac) if rac else None
    severe = rank is not None and rank <= _SEVERE_MAX_RANK
    acting = flight_action not in (None, "MAINTAIN")
    if not primary_te:
        threat_level = "ROUTINE"
    elif trend.get("level") == "critical" or (severe and acting):
        threat_level = "ACT"
    elif trend.get("escalating") or trend.get("level") == "warning" or severe:
        threat_level = "ALERT"
    else:
        threat_level = "MONITOR"
    # most-conservative-wins — failsafe floor 가 위협 기반 레벨을 낮추지 않음(SCC-1).
    floor = _failsafe_floor(failsafe)
    return floor if _LEVEL_RANK[floor] > _LEVEL_RANK[threat_level] else threat_level


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
    failsafe: dict[str, Any] | None = latest.get("failsafe")

    # 표시 위협은 **결정(05/06)의 primary** 기준 — RAC·flight_action 과 같은 후보라야 헤드라인이
    # 일관된다(04 threat.primary 는 match_count 로 다를 수 있음). 부재 시 explain 값으로 폴백.
    primary_te = (latest.get("response") or {}).get("primary_threat_event") \
        or current.get("primary_threat_event")
    flight_action = current.get("flight_action")
    rac = _rac_from_explain(current)
    level = _attention_level(primary_te, rac, flight_action, trend, failsafe)

    # failsafe suffix — HOLD 이상이면 헤드라인에 지배 축 포함(advisory).
    fs_action = (failsafe or {}).get("recommended_action", "") if failsafe and failsafe.get("assessable") else ""
    fs_suffix = ""
    if fs_action in _FAILSAFE_MIN_LEVEL:
        axes = ", ".join((failsafe or {}).get("driving_axes") or []) or "?"
        fs_suffix = f" | failsafe:{fs_action}({axes})"

    if not primary_te:
        headline = f"[{level}] 위협 없음 — {flight_action or '대기'}{fs_suffix}"
        rec = "정상 운용. 특이 조치 불요." if not fs_suffix else f"안전 축 이상({fs_action}) — 운용자 확인."
    else:
        desc = THREAT_CATALOG.get(primary_te, primary_te)
        headline = f"[{level}] {primary_te}({desc}) RAC={rac} → {flight_action}{fs_suffix}"
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
