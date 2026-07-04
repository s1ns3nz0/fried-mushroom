"""nav_integrity — 🔵 파생 읽기전용. GNSS/항법 무결성 저하 failsafe 타임라인 advisory (cross-cycle).

파이프라인은 무상태(ADR-004)라 사이클마다 항법을 독립 판독한다(03 `position_consistency` →
GPS·IMU·기압 잔차/위성수/HDOP 로 normal/degraded/anomaly). 그래서 "항법 신뢰가 **얼마나 오래**
깨져 있었는가"라는 지속시간은 어떤 단일 사이클도 못 본다 — 그러나 GNSS 두절/스푸핑 대응
(계속/추측항법 선회/귀환/착륙)은 본질적으로 신뢰상실 **지속시간**에 좌우된다.

`link_loss` 가 통신 안전 축을, `endurance` 가 에너지 안전 축을 본다면, 이 모듈은 **항법 안전**
축을 채운다(형제 관계). 최근 N 사이클의 `position_consistency` 출력 윈도우를 받아 말단 연속
신뢰상실(anomaly) 스트릭 → 상실 초 → 에스컬레이션 권고를 낸다:

  CONTINUE(정상) < MONITOR(약한 fix/단기상실) < DR_HOLD(추측항법 선회) < RTL(귀환) < LAND(착륙)

anomaly(잔차 초과)는 GPS 스푸핑/발산이므로 권고 시 GPS 를 신뢰하지 말고 관성항법(dead-reckoning)
으로 전환할 것을 함의한다. degraded(위성 부족/HDOP 높음)는 fix 가 약할 뿐 사용가능 → 감시만.

CRITICAL (SCC-1): advisory 만 산출한다. 어떤 사이클 결과도 변경하지 않고 입력을 변이하지 않으며
결정론 06 Response·07 Planning 의 판정을 **대체하지 않는다**(병렬 항법 안전지표). `position_
consistency` 의 상태 어휘(normal/degraded/anomaly)를 데이터 계약으로만 참조하며 03 모듈을
import 하지 않는다(레이어 격리). 어떤 상수도 쓰거나 바꾸지 않는다.
"""

from __future__ import annotations

from typing import Any

# 신뢰상실(anomaly) 지속 → 권고 에스컬레이션 임계(초). 팀 설계값 — advisory 라 상수 불변 대상 아님.
# 항법 상실은 통신 상실보다 급함(스스로 위치를 모름) → link_loss 보다 짧은 타임라인.
_DEFAULT_DR_HOLD_S = 3.0   # 이 이상 → 추측항법으로 선회대기, fix 재획득 시도
_DEFAULT_RTL_S = 8.0       # 이 이상 → 추측항법 귀환 개시
_DEFAULT_LAND_S = 20.0     # 이 이상 → 자동착륙 failsafe(항법 불가)
_DEFAULT_CYCLE_INTERVAL_S = 1.0

# position_consistency(03) 상태 어휘 — 항법 신뢰상실로 볼 상태.
_UNTRUSTED_STATE = "anomaly"


def _state_of(entry: Any) -> str | None:
    """윈도우 원소 → 항법 상태 문자열. position_consistency ChannelOutput dict 또는 상태 문자열 허용."""
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
        "untrusted_streak": kw.get("untrusted_streak", 0),
        "untrusted_seconds": kw.get("untrusted_seconds", 0.0),
        "dead_reckoning": kw.get("dead_reckoning", False),
        "note": kw.get("note", ""),
    }


def assess_nav_integrity(
    nav_window: list[Any],
    *,
    cycle_interval_s: float = _DEFAULT_CYCLE_INTERVAL_S,
    cycle_seconds: list[float] | None = None,
    dr_hold_s: float = _DEFAULT_DR_HOLD_S,
    rtl_s: float = _DEFAULT_RTL_S,
    land_s: float = _DEFAULT_LAND_S,
) -> dict[str, Any]:
    """최근 position_consistency 출력 윈도우(오래된→최신) → 항법 failsafe 권고. advisory.

    윈도우 원소는 03 `position_consistency` ChannelOutput dict({"state": ...}) 또는 상태 문자열.
    cycle_seconds: nav_window 와 병렬인 사이클별 실경과(초) 리스트 (#410). 제공 시 말단 streak
    구간의 실경과를 합산(가변 cadence 정확). None/빈 리스트면 cycle_interval_s 스칼라 폴백.
    반환: {assessable, recommended_action(CONTINUE|MONITOR|DR_HOLD|RTL|LAND|UNKNOWN),
           advisory_only, current_state, untrusted_streak, untrusted_seconds, dead_reckoning, note}.
    """
    window = list(nav_window or [])
    states = [_state_of(e) for e in window]
    current = states[-1] if states else None

    if current is None:
        return _report(False, "UNKNOWN", note="항법 상태 부재 — GNSS 무결성 판단 불가.")

    # fix 재획득(최신 정상) → 즉시 CONTINUE, 과거 상실 무관.
    if current == "normal":
        return _report(True, "CONTINUE", current_state=current, note="항법 정상 — GNSS 신뢰.")

    # 말단 연속 신뢰상실(anomaly) 스트릭 계산.
    streak = 0
    for s in reversed(states):
        if s == _UNTRUSTED_STATE:
            streak += 1
        else:
            break
    if cycle_seconds and streak > 0:
        untrusted_s = sum(cycle_seconds[-streak:])
    else:
        untrusted_s = streak * cycle_interval_s

    # 신뢰상실 아님(degraded) → fix 약하나 사용가능, 에스컬레이션 없이 감시.
    if streak == 0:
        return _report(True, "MONITOR", current_state=current, untrusted_streak=0,
                       untrusted_seconds=0.0,
                       note=f"항법 fix 약화({current}) — 감시 유지, failsafe 미개시.")

    if untrusted_s >= land_s:
        action, note = "LAND", f"⚠ 항법상실 {untrusted_s:.0f}s ≥ {land_s:.0f}s — 자동착륙 failsafe 권고."
    elif untrusted_s >= rtl_s:
        action, note = "RTL", f"⚠ 항법상실 {untrusted_s:.0f}s ≥ {rtl_s:.0f}s — 추측항법 귀환 권고."
    elif untrusted_s >= dr_hold_s:
        action, note = "DR_HOLD", f"항법상실 {untrusted_s:.0f}s ≥ {dr_hold_s:.0f}s — 추측항법 선회·재획득 시도 권고."
    else:
        action, note = "MONITOR", f"항법상실 {untrusted_s:.0f}s — 감시 유지, 재획득 대기."

    # 신뢰상실 스트릭 중이면 GPS 불신·관성항법 전환 함의.
    dr = action in ("DR_HOLD", "RTL", "LAND")
    return _report(True, action, current_state=current, untrusted_streak=streak,
                   untrusted_seconds=round(untrusted_s, 1), dead_reckoning=dr, note=note)
