"""ew_jamming — 🔵 파생 읽기전용. EW 광대역 재밍 지속·방위 확정 advisory (cross-cycle).

파이프라인은 무상태(ADR-004)라 사이클마다 RF 스펙트럼을 독립 판독한다(03 `rf_spectrum` →
광대역 이상 normal/anomaly + 방위 bearing_deg). 그래서 "재밍이 **얼마나 오래** 지속되는가"와
"방위가 **일관**된 실 emitter 인가 산발 잡음인가"는 어떤 단일 사이클도 못 본다.

`link_loss` 가 C2 링크 상실(결과)을 본다면, 이 모듈은 그 원인일 수 있는 **EW 재밍(광대역 간섭)**
을 본다 — 안전축 중 전자전(EW) 축이다. 최근 N 사이클의 `rf_spectrum` 출력 윈도우를 받아:

  - 말단 연속 이상(anomaly) 스트릭 → 재밍 지속 초
  - 스트릭 구간 방위의 순환 일관성(R) → 실 emitter(안정) vs 잡음(산발) 판별
  - 위협 등급: CLEAR < MONITOR < JAMMING_SUSPECTED < JAMMING_CONFIRMED

confirmed 시 EMCON(전파통제)·회피 기동을 권고한다(방위 반대로 이탈).

CRITICAL (SCC-1): advisory 만 산출한다. 결정론 04 위협판정·06 Response 를 **대체하지 않는**
병렬 EW 지표. 입력을 변이하지 않으며 03 모듈을 import 하지 않고 `rf_spectrum` 출력(state/
payload.bearing_deg)만 데이터 계약으로 참조한다(레이어 격리). 상수를 쓰거나 바꾸지 않는다.
"""

from __future__ import annotations

import math
from typing import Any

# 재밍 지속 → 등급 에스컬레이션 임계(초). 팀 설계값 — advisory 라 상수 불변 대상 아님.
_DEFAULT_CONFIRM_S = 2.0    # 이 이상 → 재밍 의심
_DEFAULT_SUSTAINED_S = 5.0  # 이 이상 → 재밍 확정(EMCON·회피 권고)
_DEFAULT_CYCLE_INTERVAL_S = 1.0
# 방위 순환 일관성(결과벡터 길이 R, 0..1) 이 이상이면 실 emitter 로 본다.
_DEFAULT_BEARING_STABLE_R = 0.9

_ANOMALY_STATE = "anomaly"


def _entry_state(entry: Any) -> str | None:
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        s = entry.get("state")
        return s if isinstance(s, str) else None
    return None


def _entry_bearing(entry: Any) -> float | None:
    if isinstance(entry, dict):
        b = (entry.get("payload") or {}).get("bearing_deg")
        if b is None:
            b = entry.get("bearing_deg")
        if isinstance(b, (int, float)):
            return float(b)
    return None


def _circular_stats(bearings: list[float]) -> tuple[float | None, float]:
    """방위 리스트 → (순환평균 deg, 결과벡터 길이 R). 빈 리스트면 (None, 0.0)."""
    if not bearings:
        return None, 0.0
    s = sum(math.sin(math.radians(b)) for b in bearings)
    c = sum(math.cos(math.radians(b)) for b in bearings)
    n = len(bearings)
    r = math.hypot(s, c) / n
    mean = math.degrees(math.atan2(s, c)) % 360.0
    return round(mean, 1), round(r, 3)


def _report(assessable, level, action, **kw):
    return {
        "assessable": assessable,
        "threat_level": level,
        "recommended_action": action,
        "advisory_only": True,
        "anomaly_streak": kw.get("anomaly_streak", 0),
        "anomaly_seconds": kw.get("anomaly_seconds", 0.0),
        "emitter_bearing_deg": kw.get("emitter_bearing_deg"),
        "bearing_stable": kw.get("bearing_stable", False),
        "note": kw.get("note", ""),
    }


def assess_ew_jamming(
    rf_window: list[Any],
    *,
    cycle_interval_s: float = _DEFAULT_CYCLE_INTERVAL_S,
    confirm_s: float = _DEFAULT_CONFIRM_S,
    sustained_s: float = _DEFAULT_SUSTAINED_S,
    bearing_stable_r: float = _DEFAULT_BEARING_STABLE_R,
) -> dict[str, Any]:
    """최근 rf_spectrum 출력 윈도우(오래된→최신) → EW 재밍 지속·방위 확정 advisory.

    윈도우 원소는 03 `rf_spectrum` ChannelOutput dict({"state","payload":{"bearing_deg"}}) 또는
    상태 문자열. 반환: {assessable, threat_level(CLEAR|MONITOR|JAMMING_SUSPECTED|
    JAMMING_CONFIRMED|UNKNOWN), recommended_action(CONTINUE|MONITOR|EMCON_EVADE),
    advisory_only, anomaly_streak, anomaly_seconds, emitter_bearing_deg, bearing_stable, note}.
    """
    window = list(rf_window or [])
    states = [_entry_state(e) for e in window]
    current = states[-1] if states else None

    if current is None:
        return _report(False, "UNKNOWN", "CONTINUE", note="RF 스펙트럼 상태 부재 — EW 판단 불가.")

    # 말단 연속 이상(anomaly) 스트릭.
    streak = 0
    for s in reversed(states):
        if s == _ANOMALY_STATE:
            streak += 1
        else:
            break

    if streak == 0:
        return _report(True, "CLEAR", "CONTINUE", note="광대역 RF 정상 — EW 위협 없음.")

    anomaly_s = streak * cycle_interval_s
    # 스트릭 구간(말단 streak 개)의 방위 → 순환 일관성.
    bearings = [b for b in (_entry_bearing(e) for e in window[-streak:]) if b is not None]
    mean_bearing, r = _circular_stats(bearings)
    # 단일 표본은 R=1.0 이라도 cross-cycle 일관성 증명 불가 → 최소 2 표본 요구.
    stable = len(bearings) >= 2 and r >= bearing_stable_r
    emitter_bearing = mean_bearing if stable else None

    if anomaly_s >= sustained_s:
        level, action = "JAMMING_CONFIRMED", "EMCON_EVADE"
        note = f"⚠ 재밍 {anomaly_s:.0f}s ≥ {sustained_s:.0f}s"
    elif anomaly_s >= confirm_s:
        level, action = "JAMMING_SUSPECTED", "MONITOR"
        note = f"재밍 의심 {anomaly_s:.0f}s ≥ {confirm_s:.0f}s"
    else:
        level, action = "MONITOR", "MONITOR"
        note = f"광대역 이상 {anomaly_s:.0f}s — 감시"
    note += (f", 방위 {emitter_bearing:.0f}°(R={r}) 안정 emitter."
             if stable else f", 방위 산발(R={r}) — 잡음 가능.")

    return _report(True, level, action, anomaly_streak=streak, anomaly_seconds=round(anomaly_s, 1),
                   emitter_bearing_deg=emitter_bearing, bearing_stable=stable, note=note)
