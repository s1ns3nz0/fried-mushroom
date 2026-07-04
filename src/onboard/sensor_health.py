"""sensor_health — 🔵 파생 읽기전용. 03 전 채널 센서 건전성 종합 advisory (단일 사이클).

failsafe 관찰자(link_loss/nav_integrity)가 **한 채널을 시간축**으로 본다면, 이 모듈은 **한 사이클
안의 전 채널 폭**을 본다. 03 AbstractionOutput 의 11개 채널 quality/state 를 집계해 "지금 센서
그림을 얼마나 믿을 수 있는가"를 한눈에 낸다:

  - 전반 건전성 밴드: NOMINAL / DEGRADED / CRITICAL
  - 열화·이상 채널 목록(무엇이 신뢰를 깎는가)
  - 권고 확신도 할인계수(advisory) — 센서가 부실할 때 상위 판단이 참고할 하향 배수

quality 는 make_output 이 전 채널에서 [0,1] 로 균일 산출하는 신뢰 대리값이라 채널 비교의 앵커로
쓴다. 건전성은 **오직 quality 밴드**로 판정한다 — 03 계약에서 state="anomaly" 는 센서 고장이
아니라 **위협 탐지 신호**(총성 감지, 암호 다운그레이드, GPS 스푸핑 탐지 등)이므로, 고품질 anomaly
탐지는 오히려 센서가 잘 작동하는 것이다. 따라서 anomaly state 는 건전성 등급에 반영하지 않고
참고용으로 impaired 항목에 state 만 실어 보고한다.

CRITICAL (SCC-1): advisory 만 산출한다. 권고 확신도 할인은 **참고 배수일 뿐** 결정론 04
confidence·05 RAC 판정을 대체하거나 곱하지 않는다. 입력을 변이하지 않으며 상수를 쓰거나 바꾸지
않는다(레이어 격리 — AbstractionOutput dict 만 데이터 계약으로 소비).
"""

from __future__ import annotations

from typing import Any

# quality 건전성 밴드 임계 — 팀 설계값(advisory 라 상수 불변 대상 아님).
_DEFAULT_DEGRADED_Q = 0.6   # 이 미만 → 열화
_DEFAULT_CRITICAL_Q = 0.3   # 이 미만 → 이상(임계)

# 밴드 → 권고 확신도 할인계수(advisory 참고 배수).
_DISCOUNT = {"NOMINAL": 1.0, "DEGRADED": 0.85, "CRITICAL": 0.6}


def _channels_of(inp: Any) -> list[dict]:
    """입력 → 채널 리스트. AbstractionOutput({"channels":[...]}) 또는 채널 리스트 허용."""
    if isinstance(inp, dict):
        chans = inp.get("channels")
        return [c for c in chans if isinstance(c, dict)] if isinstance(chans, list) else []
    if isinstance(inp, list):
        return [c for c in inp if isinstance(c, dict)]
    return []


def assess_sensor_health(
    abstraction: Any,
    *,
    degraded_q: float = _DEFAULT_DEGRADED_Q,
    critical_q: float = _DEFAULT_CRITICAL_Q,
) -> dict[str, Any]:
    """03 AbstractionOutput → 센서 건전성 종합. advisory.

    반환: {assessable, health(NOMINAL|DEGRADED|CRITICAL|UNKNOWN), channel_count,
           min_quality, mean_quality, impaired, confidence_discount, advisory_only, note}.
    impaired: [{channel, state, quality, tier(degraded|critical)}] worst-first.
    """
    channels = _channels_of(abstraction)
    scored = [c for c in channels if isinstance(c.get("quality"), (int, float))]

    if not scored:
        return {
            "assessable": False, "health": "UNKNOWN", "channel_count": len(channels),
            "min_quality": None, "mean_quality": None, "impaired": [],
            "confidence_discount": 1.0, "advisory_only": True,
            "note": "품질 산출 채널 없음 — 센서 건전성 판단 불가.",
        }

    impaired: list[dict] = []
    for c in scored:
        q = float(c["quality"])
        if q < degraded_q:  # 건전성은 quality 만으로 — state 는 참고 보고용.
            impaired.append({
                "channel": c.get("channel"),
                "state": c.get("state"),
                "quality": round(q, 4),
                "tier": "critical" if q < critical_q else "degraded",
            })

    qualities = [float(c["quality"]) for c in scored]
    min_q = min(qualities)
    mean_q = sum(qualities) / len(qualities)

    if any(i["tier"] == "critical" for i in impaired):
        health = "CRITICAL"
    elif impaired:
        health = "DEGRADED"
    else:
        health = "NOMINAL"

    # worst-first(critical 먼저, 그 안에서 quality 오름차순).
    impaired.sort(key=lambda i: (0 if i["tier"] == "critical" else 1, i["quality"]))

    n_imp = len(impaired)
    note = (f"센서 {len(scored)}채널 중 {n_imp} 열화/이상 — 건전성 {health}."
            if n_imp else f"센서 {len(scored)}채널 전부 정상 — 건전성 NOMINAL.")
    return {
        "assessable": True, "health": health, "channel_count": len(scored),
        "min_quality": round(min_q, 4), "mean_quality": round(mean_q, 4),
        "impaired": impaired, "confidence_discount": _DISCOUNT[health],
        "advisory_only": True, "note": note,
    }
