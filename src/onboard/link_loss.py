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

# 두절 지속 → 권고 에스컬레이션 임계(초). 팀 설계값 — advisory 라 상수 불변 대상 아님.
_DEFAULT_HOLD_S = 3.0   # 이 이상 완전두절 → 선회대기하며 재획득 시도
_DEFAULT_RTL_S = 10.0   # 이 이상 → 귀환 개시
_DEFAULT_LAND_S = 30.0  # 이 이상 → 자동착륙 failsafe
_DEFAULT_CYCLE_INTERVAL_S = 1.0

# 진짜 통신두절(사용 가능한 C2 링크 없음) 판정 — payload 물리 신호 기준.
# 03 link_status 의 anomaly 임계(마진<15dB / 손실>5%)는 '열화-존재'라 두절 아님(codex #372 P2):
# anomaly 라고 무조건 두절로 보면 링크가 나쁘지만 살아있는데도 HOLD/RTL/LAND 로 오에스컬레이션.
_LOST_PACKET_LOSS = 0.95   # 근-전손 패킷손실 → 실질 무링크
_LOST_MARGIN_DB = 0.0      # RSSI ≤ 노이즈플로어(마진 소실) → 신호 매몰
_LOST_STATE = "lost"       # 명시적 두절 토큰(문자열/상위계약 편의). link_status 어휘엔 없음.


def _state_of(entry: Any) -> str | None:
    """윈도우 원소 → 링크 상태 문자열. link_status ChannelOutput dict 또는 상태 문자열 허용."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        s = entry.get("state")
        return s if isinstance(s, str) else None
    return None


def _is_lost(entry: Any) -> bool:
    """이 사이클이 '사용 가능한 C2 링크 없음'인가. anomaly(열화-존재)와 구분.

    두절 근거는 payload 물리 신호: 근-전손 패킷손실 또는 마진 소실(RSSI ≤ 노이즈플로어).
    명시적 `state=="lost"` 토큰도 두절로 인정(상위계약/테스트 편의). anomaly/degraded 는
    '링크는 있으나 나쁨'이라 두절이 아니다 — failsafe 를 개시하지 않는다.
    """
    if _state_of(entry) == _LOST_STATE:
        return True
    if isinstance(entry, dict):
        payload = entry.get("payload") or {}
        loss = payload.get("packet_loss_rate")
        if isinstance(loss, (int, float)) and not isinstance(loss, bool) and loss >= _LOST_PACKET_LOSS:
            return True
        rssi, noise = payload.get("rssi_dbm"), payload.get("noise_floor_dbm")
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (rssi, noise)):
            if (rssi - noise) <= _LOST_MARGIN_DB:
                return True
    return False


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
    cycle_seconds: list[float] | None = None,
    hold_s: float = _DEFAULT_HOLD_S,
    rtl_s: float = _DEFAULT_RTL_S,
    land_s: float = _DEFAULT_LAND_S,
) -> dict[str, Any]:
    """최근 link_status 출력 윈도우(오래된→최신) → lost-link failsafe 권고. advisory.

    윈도우 원소는 03 `link_status` ChannelOutput dict({"state": ...}) 또는 상태 문자열.
    cycle_seconds: link_window 와 병렬인 사이클별 실경과(초) 리스트 (#410). 제공 시 말단 streak
    구간의 실경과를 합산(가변 cadence 정확). None/빈 리스트면 cycle_interval_s 스칼라 폴백.
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

    # 말단 연속 실질두절 스트릭 계산(payload 물리 신호 기반 — anomaly 문자열 아님).
    streak = 0
    for entry in reversed(window):
        if _is_lost(entry):
            streak += 1
        else:
            break
    if cycle_seconds and streak > 0:
        outage_s = sum(cycle_seconds[-streak:])
    else:
        outage_s = streak * cycle_interval_s

    # 실질두절 아님(anomaly/degraded 지만 링크 존재) → 에스컬레이션 없이 감시.
    if streak == 0:
        return _report(True, "MONITOR", current_state=current, outage_streak=0, outage_seconds=0.0,
                       note=f"링크 열화({current}) — 링크 존재, 감시 유지, failsafe 미개시.")

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
