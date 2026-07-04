"""Step C — 확신도 · 킬체인 단계 산출.

결정론적 confidence 와 AI 강화판(로그오즈 결합)을 병렬 계산 후 교차검증.
AI 는 결정론 값을 덮어쓰지 않는다 — 불일치 시 결정론으로 폴백 (ADR-003, SCC-1).
math 모듈만 사용 (numpy 등 추가 의존성 없음).

입력 matched:
  [{"threat_event": str,
    "matched_channels": [{"name", "base_weight", "quality", "state"}, ...]}, ...]

반환 scored:
  [{"threat_event", "match_count", "confidence", "confidence_source",
    "kill_chain_stage", "_avg_weight"}, ...]
  ("_avg_weight" 는 primary 선정용 내부 필드 — 최종 출력에서 run.py 가 제거)
"""

from __future__ import annotations

import math

from onboard.shared.constants import (
    CONFIDENCE_BY_MATCH_COUNT,
    CONFIDENCE_UPPER_BOUND,
    CROSS_CHECK_TOLERANCE,
    PHASE_THREAT_MULTIPLIER,
    Q_MIN,
    W_MIN,
)

_MAX_MATCH_COUNT = max(CONFIDENCE_BY_MATCH_COUNT)  # 3 (이상은 상한 confidence)


def _logit(q: float) -> float:
    q = min(max(q, 0.001), 0.999)  # 0/1 극단값 domain error 방지
    return math.log(q / (1 - q))


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _det_confidence(match_count: int) -> float:
    return CONFIDENCE_BY_MATCH_COUNT.get(
        match_count, CONFIDENCE_BY_MATCH_COUNT[_MAX_MATCH_COUNT]
    )


def run(matched: list[dict], declared_phase: str) -> list[dict]:
    scored: list[dict] = []

    for entry in matched:
        threat_event = entry["threat_event"]

        # ── quality 2단 제외 ──
        effective: list[tuple[float, float]] = []  # (base_weight, quality)
        for ch in entry["matched_channels"]:
            w = ch["base_weight"]
            q = ch["quality"]
            if w < W_MIN:  # 구조적 하한 — 항상 제외
                continue
            if q < Q_MIN:  # 열화 하한 — 이번 사이클만 제외
                continue
            effective.append((w, q))

        if not effective:  # 근거가 다 무너지면 이번 사이클 미탐지
            continue

        match_count = len(effective)
        det_confidence = _det_confidence(match_count)
        avg_weight = sum(w for w, _ in effective) / match_count
        kill_chain_stage = (
            "후기"
            if avg_weight >= 0.35 and match_count >= 2
            else "중기"
            if match_count >= 1
            else "초기"
        )

        # ── AI 강화판: 로그오즈 결합 ──
        log_odds = sum(w * _logit(q) for w, q in effective)
        ai_confidence = _sigmoid(log_odds)

        # ── 교차검증: 불일치 시 결정론으로 폴백 ──
        if abs(ai_confidence - det_confidence) <= CROSS_CHECK_TOLERANCE:
            confidence, confidence_source = ai_confidence, "ai"
        else:
            confidence, confidence_source = det_confidence, "deterministic"

        # ── 국면 배수 (마지막, 0.95 상한) ──
        multiplier = PHASE_THREAT_MULTIPLIER.get((declared_phase, threat_event), 1.0)
        confidence = min(confidence * multiplier, CONFIDENCE_UPPER_BOUND)

        scored.append(
            {
                "threat_event": threat_event,
                "match_count": match_count,
                "confidence": round(confidence, 3),
                "confidence_source": confidence_source,
                "kill_chain_stage": kill_chain_stage,
                "_avg_weight": avg_weight,
            }
        )

    return scored
