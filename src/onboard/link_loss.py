"""link_loss — 🔵 파생 읽기전용. C2 통신두절(lost-link) failsafe 타임라인 advisory (cross-cycle).

파이프라인은 무상태(ADR-004)라 사이클마다 링크를 독립 판독한다(03 `link_status` → normal/
degraded/anomaly). 그래서 "링크가 **얼마나 오래** 끊겨 있었는가"라는 두절 지속시간은 어떤 단일
사이클도 못 본다 — 그러나 lost-link 대응(계속/선회대기/귀환/착륙)은 본질적으로 두절 **지속시간**
에 좌우된다(UAV 표준 GCS-failsafe 타임라인). endurance 가 에너지 안전, trend 가 위협 궤적을
본다면, 이 모듈은 **통신 안전**을 본다 — 비어 있던 축이다.

이 모듈은 파이프라인 위에 얹는 관찰자로, 최근 N 사이클의 `link_status` 출력 윈도우를 받아 말단
연속 두절 스트릭 → 두절 초 → 에스컬레이션 권고를 낸다:

  CONTINUE(정상) < MONITOR(열화/단기두절) < HOLD(선회대기) < RTL(귀환) < LAND(착륙)

CRITICAL (SCC-1): advisory 만 산출한다. 어떤 사이클 결과도 변경하지 않고 입력을 변이하지 않으며
결정론 06 Response 의 lost-link 판정을 **대체하지 않는다**(병렬 통신 안전지표). `link_status` 의
상태 어휘(normal/degraded/anomaly)를 데이터 계약으로만 참조하며 03 모듈을 import 하지 않는다
(레이어 격리). 어떤 상수도 쓰거나 바꾸지 않는다.
"""

from __future__ import annotations

from typing import Any

# 두절(anomaly) 지속 → 권고 에스컬레이션 임계(초). 팀 설계값 — advisory 라 상수 불변 대상 아님.
_DEFAULT_HOLD_S = 3.0   # 이 이상 완전두절 → 선회대기하며 재획득 시도
_DEFAULT_RTL_S = 10.0   # 이 이상 → 귀환 개시
_DEFAULT_LAND_S = 30.0  # 이 이상 → 자동착륙 failsafe
_DEFAULT_CYCLE_INTERVAL_S = 1.0

# link_status(03) 상태 어휘 — 완전두절로 볼 상태.
_LOST_STATE = "anomaly"
_DEGRADED_STATE = "degraded"


def _state_of(entry: Any) -> str | None:
    """윈도우 원소 → 링크 상태 문자열. link_status ChannelOutput dict 또는 상태 문자열 허용."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        s = entry.get("state")
        return s if isinstance(s, str) else None
    return None


def _report(assessable, action, **kw):
    return {
        "assessable": assessable,
        "recommended_action": action,
        "advisory_only": True,
        "current_state": kw.get("current_state"),
        "outage_streak": kw.get("outage_streak", 0),
        "outage_seconds": kw.get("outage_seconds", 0.0),
        "note": kw.get("note", ""),
    }


def assess_link_loss(
    link_window: list[Any],
    *,
    cycle_interval_s: float = _DEFAULT_CYCLE_INTERVAL_S,
    hold_s: float = _DEFAULT_HOLD_S,
    rtl_s: float = _DEFAULT_RTL_S,
    land_s: float = _DEFAULT_LAND_S,
) -> dict[str, Any]:
    """최근 link_status 출력 윈도우(오래된→최신) → lost-link failsafe 권고. advisory.

    윈도우 원소는 03 `link_status` ChannelOutput dict({"state": ...}) 또는 상태 문자열.
    반환: {assessable, recommended_action(CONTINUE|MONITOR|HOLD|RTL|LAND|UNKNOWN),
           advisory_only, current_state, outage_streak, outage_seconds, note}.
    """
    window = list(link_window or [])
    states = [_state_of(e) for e in window]
    current = states[-1] if states else None

    if current is None:
        return _report(False, "UNKNOWN", note="링크 상태 부재 — 통신두절 판단 불가.")

    # 링크 재획득(최신 정상) → 즉시 CONTINUE, 과거 두절 무관.
    if current == "normal":
        return _report(True, "CONTINUE", current_state=current,
                       note="링크 정상 — 통신 안전.")

    # 말단 연속 완전두절(anomaly) 스트릭 계산.
    streak = 0
    for s in reversed(states):
        if s == _LOST_STATE:
            streak += 1
        else:
            break
    outage_s = streak * cycle_interval_s

    # 완전두절 아님(degraded) → 링크 사용가능, 에스컬레이션 없이 감시.
    if streak == 0:
        return _report(True, "MONITOR", current_state=current, outage_streak=0, outage_seconds=0.0,
                       note=f"링크 열화({current}) — 감시 유지, failsafe 미개시.")

    if outage_s >= land_s:
        action, note = "LAND", f"⚠ 두절 {outage_s:.0f}s ≥ {land_s:.0f}s — 자동착륙 failsafe 권고."
    elif outage_s >= rtl_s:
        action, note = "RTL", f"⚠ 두절 {outage_s:.0f}s ≥ {rtl_s:.0f}s — 귀환(RTL) 권고."
    elif outage_s >= hold_s:
        action, note = "HOLD", f"두절 {outage_s:.0f}s ≥ {hold_s:.0f}s — 선회대기·재획득 시도 권고."
    else:
        action, note = "MONITOR", f"두절 {outage_s:.0f}s — 감시 유지, 재획득 대기."

    return _report(True, action, current_state=current, outage_streak=streak,
                   outage_seconds=round(outage_s, 1), note=note)
