"""05 Risk Assessment — AI 강화판 병렬 참고지표 (RAC 에 영향 없음).

CPU 기반 연속값 계산: continuous_L(04 confidence 재사용), continuous_S(margin_penalty),
교차검증(rac_ai_equivalent 대비 신뢰도), compound_urgency_score(우선순위 점수).
결정론적 RAC 를 절대 덮어쓰지 않는다 (ADR-003). D4D `05` / `D-1` §6.
"""

from __future__ import annotations

from ..shared.constants import (
    AI_RELIABILITY_DELTA_THRESHOLD,
    COMPOUND_UPPER_BOUND,
    CONFIDENCE_ANCHOR,
    CONTINUOUS_S_BASE_SCORE,
    CONTINUOUS_S_TO_NUM_THRESHOLDS,
    KILL_CHAIN_LATE_BONUS,
    RAC_ORDER,
)

# margin_penalty 항목 (D-1 §6, 팀 설정값). "확실히 존재하는 필드"만 반영.
# constants.py 에 별도 상수가 없어 모듈 상수로 둔다 (step6.md 허용, 값 출처 D-1).
_BATTERY_LOW_THRESHOLD = 30
_LINK_QUALITY_LOW_THRESHOLD = 0.5
_MARGIN_PENALTY_BATTERY = 0.10
_MARGIN_PENALTY_SPARE_ASSET = 0.05
_MARGIN_PENALTY_LINK = 0.05

# kill_chain_stage 후기 판정 라벨.
_LATE_STAGE = "후기"


def continuous_l(base: float, confidence: float) -> float:
    """continuous_L = min(base × (confidence/앵커), min(base×3, 0.95)).

    04 의 confidence(최저 앵커 0.7) 로 base_rate 를 보정. 별도 AI 모델 없음.
    """
    scaled = base * (confidence / CONFIDENCE_ANCHOR)
    cap = min(base * 3, COMPOUND_UPPER_BOUND)
    return min(scaled, cap)


def margin_penalty(
    battery_pct: float | None,
    spare_asset_available: bool,
    link_quality: float | None,
) -> float:
    """운영마진 패널티 합.

    배터리<30%(+0.10) + 예비기체없음(+0.05) + link_quality<0.5(+0.05).
    데이터 없음(None) 은 해당 패널티 미적용 (graceful degradation).
    """
    penalty = 0.0
    if battery_pct is not None and battery_pct < _BATTERY_LOW_THRESHOLD:
        penalty += _MARGIN_PENALTY_BATTERY
    if not spare_asset_available:
        penalty += _MARGIN_PENALTY_SPARE_ASSET
    if link_quality is not None and link_quality < _LINK_QUALITY_LOW_THRESHOLD:
        penalty += _MARGIN_PENALTY_LINK
    return penalty


def continuous_s(
    severity_label_final: str,
    battery_pct: float | None,
    spare_asset_available: bool,
    link_quality: float | None,
) -> float:
    """continuous_S = min(base_score[label] + margin_penalty, 0.95)."""
    base = CONTINUOUS_S_BASE_SCORE[severity_label_final]
    penalty = margin_penalty(battery_pct, spare_asset_available, link_quality)
    return min(base + penalty, COMPOUND_UPPER_BOUND)


def s_num_from_continuous(s: float) -> int:
    """continuous_S → severity_num_ai. CONTINUOUS_S_TO_NUM_THRESHOLDS 내림차순 순회.

    표 아래(<0.20) 는 4(Negligible).
    """
    for threshold, num in CONTINUOUS_S_TO_NUM_THRESHOLDS:
        if s >= threshold:
            return num
    return 4


def cross_check_reliability(rac: str, rac_ai: str) -> str:
    """|RAC_ORDER[rac] - RAC_ORDER[rac_ai]| >= 2 → 'low', else 'normal'.

    통보용 플래그일 뿐, RAC 자체는 바꾸지 않는다.
    """
    diff = abs(RAC_ORDER[rac] - RAC_ORDER[rac_ai])
    return "low" if diff >= AI_RELIABILITY_DELTA_THRESHOLD else "normal"


def urgency_score(cont_l: float, cont_s: float, kill_chain_stage: str) -> float:
    """compound_urgency_score = min(continuous_L × continuous_S + (후기 보너스), 0.95)."""
    bonus = KILL_CHAIN_LATE_BONUS if kill_chain_stage == _LATE_STAGE else 0.0
    return min(cont_l * cont_s + bonus, COMPOUND_UPPER_BOUND)
