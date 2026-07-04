"""confidence 캘리브레이션 모델 — 코퍼스 outcome 으로 위협 confidence 를 보정 (3번째 실 ML).

isotonic regression(PAV, Pool Adjacent Violators)으로 "raw 위협 confidence → 실제 성공확률"
단조 매핑을 코퍼스(confidence, outcome)에서 학습한다. 확률 캘리브레이션의 표준 비모수 방법
(sklearn CalibratedClassifierCV 의 isotonic 과 동일 원리)이며 순수 Python — 무거운 의존 없음.

SCC-1(CLAUDE.md CRITICAL): 캘리브레이션 값은 **병렬 advisory**(운용자에게 "모델 0.9 이지만
과거 성공률 0.7" 참고 제공)일 뿐, 결정론 RAC/판정을 바꾸지 않는다. weight_advisor(라운드 3)의
캘리브레이션 통계의 실모델 버전 — 통계 대신 학습된 매핑을 낸다.
"""

from __future__ import annotations

from typing import Any

from weight_advisor import outcome_label

_MIN_SAMPLES = 5  # 학습 표본 최소치 — 미만이면 캘리브레이터 없음(과적합/무의미 방지).


def _pav_isotonic(points: list[tuple[float, float, float]]) -> list[tuple[float, float]]:
    """Pool Adjacent Violators — 단조 비감소 적합. (x 우측경계, 보정값) 브레이크포인트 반환.

    points 는 (x, 라벨합, 가중치=표본수) 이며 x **오름차순 + distinct** 여야 한다.
    (동일 x 는 fit_calibrator 에서 미리 그룹핑 — 순서 의존/중복 브레이크포인트 방지.)
    """
    # 각 블록: [합, 가중치, 우측경계 x]
    blocks: list[list[float]] = [[sy, w, x] for x, sy, w in points]
    i = 0
    while i < len(blocks) - 1:
        left_mean = blocks[i][0] / blocks[i][1]
        right_mean = blocks[i + 1][0] / blocks[i + 1][1]
        if left_mean > right_mean:  # 단조 위반 → 인접 병합
            blocks[i][0] += blocks[i + 1][0]
            blocks[i][1] += blocks[i + 1][1]
            blocks[i][2] = blocks[i + 1][2]
            del blocks[i + 1]
            if i > 0:
                i -= 1
        else:
            i += 1
    return [(b[2], b[0] / b[1]) for b in blocks]


class ConfidenceCalibrator:
    """학습된 isotonic 매핑. `calibrate(raw)` → 보정 확률. 미학습/표본부족 시 None 반환."""

    def __init__(self, breakpoints: list[tuple[float, float]] | None):
        self._bp = breakpoints  # (x_우측경계, 보정값) 오름차순

    @property
    def fitted(self) -> bool:
        return bool(self._bp)

    def calibrate(self, raw_confidence: float) -> float | None:
        """raw confidence → 보정 확률(단조 계단함수). 미학습 시 None."""
        if not self._bp:
            return None
        for x_edge, value in self._bp:
            if raw_confidence <= x_edge:
                return round(value, 4)
        return round(self._bp[-1][1], 4)  # 최대 경계 초과 → 마지막 블록값


def fit_calibrators_by_threat(records: list[dict[str, Any]]) -> dict[str, ConfidenceCalibrator]:
    """threat_event 별 캘리브레이터 학습 — 위협마다 경험 성공률이 다르므로 별도 곡선.

    라운드 3 advisory 계약(위협-특이 캘리브레이션)과 정합. 혼합 코퍼스를 그대로 넣으면 된다.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        te = r.get("threat_event")
        if te is not None:
            buckets.setdefault(te, []).append(r)
    return {te: fit_calibrator(recs) for te, recs in buckets.items()}


def fit_calibrator(records: list[dict[str, Any]]) -> ConfidenceCalibrator:
    """단일-위협(사전 필터) 레코드 → isotonic 캘리브레이터 학습.

    혼합 threat_event 코퍼스는 fit_calibrators_by_threat 를 쓸 것 — 여기선 threat 구분 없이
    (confidence, outcome라벨) 전체를 한 곡선으로 학습한다(위협별 rate 상이 시 부정확).
    outcome 분류 가능 + confidence 있는 레코드만 표본. _MIN_SAMPLES 미만이면 미학습.
    """
    pairs: list[tuple[float, int]] = []
    for r in records:
        label = outcome_label(r.get("outcome"))
        conf = r.get("confidence")
        if label is None or conf is None:
            continue
        pairs.append((float(conf), label))
    if len(pairs) < _MIN_SAMPLES:
        return ConfidenceCalibrator(None)
    # 동일 confidence 를 먼저 그룹핑(라벨합/표본수) → 순서 무관 + 중복 브레이크포인트 방지.
    grouped: dict[float, list[float]] = {}
    for conf, label in pairs:
        g = grouped.setdefault(conf, [0.0, 0.0])
        g[0] += label
        g[1] += 1.0
    points = [(x, grouped[x][0], grouped[x][1]) for x in sorted(grouped)]
    return ConfidenceCalibrator(_pav_isotonic(points))
