"""05 Risk Assessment — L(발생가능성) 결정론 계산.

base_rate 조회(threat_category 별 컨텍스트 민감도) → l_value_to_class 등급화 →
posture_shift_steps 로 경계태세 보정. D4D `05. Risk Assessment` / `D-1` §2~3.

threat_category 3분류는 06 과 공유하므로 shared.constants 에서 import (CLAUDE.md 레이어 격리).
"""

from __future__ import annotations

from ..shared.constants import (
    BASE_RATE_PHYSICAL,
    BASE_RATE_REMOTE_NAV,
    L_VALUE_TO_CLASS_THRESHOLDS,
    THREAT_CATEGORY,
)

# l_class 순서 (A=가장 높음). shift_class 인덱싱용.
_CLASS_ORDER: tuple[str, ...] = ("A", "B", "C", "D", "E", "F")

# posture 키 누락 시 평시(가장 낮은 경계) 로 보수적 처리.
_PEACETIME_LEVEL = 5

# 경계태세 기준 축: 물리·EW계는 watchcon/defcon, 사이버계(T2)는 infocon (D-1 §3).
_CYBER_THREATS = frozenset({"T2"})


def base_rate(threat_event: str, mission_context: str) -> float:
    """base_rate 조회.

    PHYSICAL(T3/T4) 은 (threat_event, mission_context) 조합,
    REMOTE/NAVIGATION 은 threat_event 단독(컨텍스트 무관).
    """
    if THREAT_CATEGORY[threat_event] == "PHYSICAL":
        return BASE_RATE_PHYSICAL[(threat_event, mission_context)]
    return BASE_RATE_REMOTE_NAV[threat_event]


def l_value_to_class(rate: float) -> str:
    """l_value → A~F 등급. L_VALUE_TO_CLASS_THRESHOLDS 를 내림차순 순회, 첫 매칭이 등급.

    표(최하 0.01="E") 아래는 "F". (constants 가 SSOT; D-1 인라인 예시와 달리 0<rate<0.01 은 F.)
    """
    for threshold, l_class in L_VALUE_TO_CLASS_THRESHOLDS:
        if rate >= threshold:
            return l_class
    return "F"


def posture_shift_steps(posture: dict, threat_event: str) -> int:
    """경계태세 → 등급 상향 steps.

    기준 level: 사이버계(T2)=infocon, 그 외(물리·EW계)=min(watchcon, defcon).
    level>=4 → 0, level==3 → 1, level<=2 → 2 (D-1 §3, 팀 자체 정의).
    키 누락 시 평시(5) 로 간주.
    """
    if threat_event in _CYBER_THREATS:
        level = posture.get("infocon", _PEACETIME_LEVEL)
    else:
        level = min(
            posture.get("watchcon", _PEACETIME_LEVEL),
            posture.get("defcon", _PEACETIME_LEVEL),
        )
    if level >= 4:
        return 0
    if level == 3:
        return 1
    return 2


def shift_class(l_class: str, steps: int) -> str:
    """l_class 를 A쪽으로 steps 만큼 이동. A 상한 / F 하한 고정.

    steps 양수=상향(A쪽), 음수=하향(F쪽). 경계 밖은 clamp.
    """
    idx = _CLASS_ORDER.index(l_class) - steps
    idx = min(len(_CLASS_ORDER) - 1, max(0, idx))
    return _CLASS_ORDER[idx]
