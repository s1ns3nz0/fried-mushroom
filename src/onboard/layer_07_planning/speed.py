"""07. Flight Planning — flight_action(+weights)별 속도 지시(이산 카테고리).

(신규) mission_brief.weights(운용자 임무 가치 가중치)가 speed_mode를 한 단계
조정한다 — 07 우선순위 조합에 weights가 실제로 연결되는 첫 지점(grill-me 발견:
이전엔 스키마에만 존재하고 어느 결정 로직도 읽지 않는 죽은 값이었음).

적용 범위는 _WEIGHT_ADJUSTABLE_ACTIONS(MAINTAIN/ALTITUDE_CHANGE/POSTURE_ELEVATE)
뿐이다. RTL/REROUTE/ALTITUDE_CHANGE_REROUTE는 이미 회피 진행중(항상 MAX)이라
weights로 늦추면 위험하므로 조정 대상에서 제외한다(SCC-1). CFIT override로
강제된 ALTITUDE_CHANGE도 마찬가지로 weights를 넘기지 않는 것은 run.py의 책임이다
(안전 최우선 override는 weights 무관하게 항상 NORMAL 고정).

weights.survival - weights.stealth 우세가 SPEED_WEIGHT_DOMINANCE_MARGIN을 넘으면
SPEED_MODE_ORDER(CAUTIOUS<NORMAL<MAX) 축에서 한 단계만 상/하향한다(clamp).
"""

from ..shared.constants import SPEED_MODE_ORDER, SPEED_WEIGHT_DOMINANCE_MARGIN

_MODE_MAP: dict[str, str] = {
    "RTL": "MAX",
    "REROUTE": "MAX",
    "ALTITUDE_CHANGE_REROUTE": "MAX",
    "POSTURE_ELEVATE": "CAUTIOUS",
    "ALTITUDE_CHANGE": "NORMAL",
    "MAINTAIN": "NORMAL",
}

_WEIGHT_ADJUSTABLE_ACTIONS = frozenset({"MAINTAIN", "ALTITUDE_CHANGE", "POSTURE_ELEVATE"})

_SPEED_BY_ORDER: dict[int, str] = {v: k for k, v in SPEED_MODE_ORDER.items()}
_MIN_ORDER = min(SPEED_MODE_ORDER.values())
_MAX_ORDER = max(SPEED_MODE_ORDER.values())


def compute_speed_mode(flight_action: str, weights: dict | None = None) -> str:
    """(flight_action, weights) → speed_mode(NORMAL/CAUTIOUS/MAX).

    weights=None(기본값)이거나 flight_action이 _WEIGHT_ADJUSTABLE_ACTIONS 밖이면
    기존 순수 룩업 그대로 반환. 실제 목표 m/s 변환은 오토파일럿 몫.
    """
    base = _MODE_MAP[flight_action]

    if weights is None or flight_action not in _WEIGHT_ADJUSTABLE_ACTIONS:
        return base

    dominance = weights.get("survival", 0.0) - weights.get("stealth", 0.0)
    order = SPEED_MODE_ORDER[base]

    if dominance > SPEED_WEIGHT_DOMINANCE_MARGIN:
        order = min(order + 1, _MAX_ORDER)
    elif dominance < -SPEED_WEIGHT_DOMINANCE_MARGIN:
        order = max(order - 1, _MIN_ORDER)

    return _SPEED_BY_ORDER[order]
