"""임무 결과 예측 모델 — METT+TC 피처 → P(임무 성공) (4번째 실 ML).

코퍼스(mission_context/posture/threat_event/confidence, outcome)로 로지스틱 회귀(numpy)를 학습해
"이 임무 프로필의 과거 성공확률"을 예측한다. confidence 캘리브레이션(#353)이 confidence 한 축을
보정한다면, 이건 **여러 피처를 종합한 결과 예측** — 운용 계획 advisory.

SCC-1(CLAUDE.md CRITICAL): 병렬 advisory(계획 참고)일 뿐 결정론 RAC/판정을 바꾸지 않는다.
학습표본 부족/피처 부재/numpy 미설치 시 미학습(predict → None, 하위호환).

numpy 는 선택 의존(pyproject `[ml]` extra). 미설치면 embedding.py 와 동일하게 자동 하향 —
`fit_outcome_predictor` 가 항상 미학습 예측기를 반환하고 코어 파이프라인은 영향받지 않는다.
"""

from __future__ import annotations

from typing import Any

from weight_advisor import outcome_label

try:
    import numpy as np

    _NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover - 선택 의존 미설치 경로
    np = None
    _NUMPY_AVAILABLE = False

_MIN_SAMPLES = 8
_NUMERIC = ("defcon", "watchcon", "infocon")  # posture 하위 필드
_CATEGORICAL = ("mission_context", "threat_event")
_L2 = 0.01
_ITERS = 800
_LR = 0.3


def _has_features(record: dict[str, Any]) -> bool:
    """예측 피처가 하나라도 있는가. 전부 없으면 절편-only 학습(무의미) 방지 → 표본 제외."""
    posture = record.get("posture") or {}
    if any(posture.get(k) is not None for k in _NUMERIC):
        return True
    if record.get("confidence") is not None:
        return True
    return any(record.get(c) is not None for c in _CATEGORICAL)


def _numeric_row(record: dict[str, Any]) -> list[float]:
    posture = record.get("posture") or {}
    row = [float(posture.get(k)) if posture.get(k) is not None else 0.0 for k in _NUMERIC]
    row.append(float(record.get("confidence")) if record.get("confidence") is not None else 0.0)
    return row


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


class OutcomePredictor:
    """학습된 로지스틱 모델. `predict(record)` → P(성공). 미학습 시 None."""

    def __init__(self, state: dict | None):
        self._s = state  # {w, b, mean, std, vocab}

    @property
    def fitted(self) -> bool:
        return self._s is not None

    def _vectorize(self, record: dict[str, Any]) -> np.ndarray:
        s = self._s
        num = np.array(_numeric_row(record), dtype=float)
        num = (num - s["mean"]) / s["std"]
        cats: list[float] = []
        for c in _CATEGORICAL:
            val = record.get(c)
            cats.extend(1.0 if val == v else 0.0 for v in s["vocab"][c])
        return np.concatenate([num, np.array(cats, dtype=float)])

    def predict(self, record: dict[str, Any]) -> float | None:
        """임무 레코드 피처 → 성공확률 [0,1]. 미학습/피처 전무 시 None."""
        if self._s is None or not _has_features(record):
            return None
        x = self._vectorize(record)
        p = _sigmoid(x @ self._s["w"] + self._s["b"])
        return round(float(p), 4)


def fit_outcome_predictor(records: list[dict[str, Any]]) -> OutcomePredictor:
    """코퍼스 → 로지스틱 회귀 학습. outcome 분류 가능 레코드만 표본. 표본부족/numpy부재 시 미학습."""
    if not _NUMPY_AVAILABLE:
        return OutcomePredictor(None)
    labeled = [(r, outcome_label(r.get("outcome"))) for r in records]
    # outcome 분류 가능 + 예측 피처 보유 레코드만. 피처 전무면 절편-only(무신호) 학습 방지.
    labeled = [(r, y) for r, y in labeled if y is not None and _has_features(r)]
    if len(labeled) < _MIN_SAMPLES:
        return OutcomePredictor(None)

    # 카테고리 vocab(등장 순서 고정) + 수치 표준화 파라미터.
    vocab: dict[str, list[str]] = {c: [] for c in _CATEGORICAL}
    for r, _ in labeled:
        for c in _CATEGORICAL:
            val = r.get(c)
            if val is not None and val not in vocab[c]:
                vocab[c].append(val)
    num_matrix = np.array([_numeric_row(r) for r, _ in labeled], dtype=float)
    mean = num_matrix.mean(axis=0)
    std = num_matrix.std(axis=0)
    std[std == 0] = 1.0  # 상수 피처 div0 방지

    state = {"w": None, "b": 0.0, "mean": mean, "std": std, "vocab": vocab}
    predictor = OutcomePredictor(state)
    X = np.array([predictor._vectorize(r) for r, _ in labeled], dtype=float)
    y = np.array([float(v) for _, v in labeled], dtype=float)

    # 로지스틱 회귀 경사하강(L2). numpy only.
    w = np.zeros(X.shape[1])
    b = 0.0
    n = len(y)
    for _ in range(_ITERS):
        p = _sigmoid(X @ w + b)
        grad_w = X.T @ (p - y) / n + _L2 * w
        grad_b = float((p - y).mean())
        w -= _LR * grad_w
        b -= _LR * grad_b
    state["w"] = w
    state["b"] = b
    return predictor
