"""임무 이례성(novelty) 탐지 모델 — METT+TC 피처공간 kNN 거리 (5번째 실 ML).

코퍼스의 METT+TC 피처(mission_context/posture/threat_event/confidence)를 표준화 공간에 놓고,
질의 임무가 기존 코퍼스에서 얼마나 이례적인지를 kNN 거리로 점수화한다. 결과 예측기(#367)가
outcome 라벨을 필요로 하는 지도학습이라면, 이건 **라벨 불필요 비지도** — 전 코퍼스가 표본이다.

용도(SCC-1 advisory): 이례성 높음 = "이 임무 프로필은 코퍼스 근거가 희박" → RAG 회수/advisory
신뢰도를 스스로 낮추는 게이트. 결정론 RAC/판정은 절대 바꾸지 않는다(CLAUDE.md CRITICAL).

numpy 선택 의존(pyproject `[ml]` extra). 미설치/표본부족/피처 전무 시 미학습(score → None, 하위호환).
"""

from __future__ import annotations

from typing import Any

try:
    import numpy as np

    _NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover - 선택 의존 미설치 경로
    np = None
    _NUMPY_AVAILABLE = False

_MIN_SAMPLES = 8
_NUMERIC = ("defcon", "watchcon", "infocon")  # posture 하위 필드
_CATEGORICAL = ("mission_context", "threat_event")
_K = 5  # kNN 이웃 수(표본보다 크면 fit 에서 하향)
_NOVEL_QUANTILE = 0.95  # 학습 자기거리 상위 5% 초과 → 이례


def _has_features(record: dict[str, Any]) -> bool:
    """예측 피처가 하나라도 있는가. 전무면 거리 무의미 → 표본/질의 제외."""
    posture = record.get("posture") or {}
    if any(posture.get(k) is not None for k in _NUMERIC):
        return True
    if record.get("confidence") is not None:
        return True
    return any(record.get(c) is not None for c in _CATEGORICAL)


def _numeric_row(record: dict[str, Any]) -> list[float]:
    """수치 피처행. 결측은 NaN(0 아님) — 학습평균 대치로 표준화 시 중립(z=0) 처리."""
    posture = record.get("posture") or {}
    nan = float("nan")
    row = [float(posture.get(k)) if posture.get(k) is not None else nan for k in _NUMERIC]
    conf = record.get("confidence")
    row.append(float(conf) if conf is not None else nan)
    return row


class NoveltyDetector:
    """학습된 이례성 탐지기. `score(record)` → {novelty, percentile, is_novel}. 미학습 시 None."""

    def __init__(self, state: dict | None):
        self._s = state  # {X, mean, std, vocab, k, threshold, self_dists}

    @property
    def fitted(self) -> bool:
        return self._s is not None

    def _vectorize(self, record: dict[str, Any]) -> "np.ndarray":
        s = self._s
        num = np.array(_numeric_row(record), dtype=float)
        num = np.where(np.isnan(num), s["mean"], num)  # 결측 → 학습평균 대치
        num = (num - s["mean"]) / s["std"]
        num = num * s["num_active"]  # 학습 전무 컬럼(all-NaN)은 중립(0) — 인위적 0기준 오탐 방지
        cats: list[float] = []
        for c in _CATEGORICAL:
            val = record.get(c)
            if val is None:  # 결측 카테고리 → 학습 주변빈도 대치(중립). 수치 평균대치와 대칭.
                cats.extend(s["cat_freq"][c])
            else:
                cats.extend(1.0 if val == v else 0.0 for v in s["vocab"][c])
        return np.concatenate([num, np.array(cats, dtype=float)])

    def _knn_distance(self, x: "np.ndarray", *, exclude_self: bool) -> float:
        """질의 벡터 → k 최근접 이웃 평균거리. exclude_self=True 면 최근접 1개(=자기) 제외."""
        s = self._s
        dists = np.sqrt(((s["X"] - x) ** 2).sum(axis=1))
        dists.sort()
        start = 1 if exclude_self else 0
        neighbors = dists[start : start + s["k"]]
        return float(neighbors.mean()) if neighbors.size else 0.0

    def score(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """질의 임무 → 이례성 점수. 미학습/피처 전무 시 None.

        반환: {novelty: kNN평균거리, percentile: 학습분포 내 위치[0,1], is_novel: bool}.
        """
        if self._s is None or not _has_features(record):
            return None
        x = self._vectorize(record)
        dist = self._knn_distance(x, exclude_self=False)
        self_dists = self._s["self_dists"]
        percentile = float((self_dists <= dist).mean())
        return {
            "novelty": round(dist, 4),
            "percentile": round(percentile, 4),
            "is_novel": bool(dist > self._s["threshold"]),
        }


def fit_novelty_detector(records: list[dict[str, Any]]) -> NoveltyDetector:
    """코퍼스 → kNN 이례성 탐지기. 피처 보유 레코드 전체가 표본(outcome 라벨 불필요)."""
    if not _NUMPY_AVAILABLE:
        return NoveltyDetector(None)
    samples = [r for r in records if _has_features(r)]
    if len(samples) < _MIN_SAMPLES:
        return NoveltyDetector(None)

    vocab: dict[str, list[str]] = {c: [] for c in _CATEGORICAL}
    for r in samples:
        for c in _CATEGORICAL:
            val = r.get(c)
            if val is not None and val not in vocab[c]:
                vocab[c].append(val)
    # 카테고리 주변빈도(결측 대치용). 해당 필드 보유 표본 대비 각 값의 비율.
    cat_freq: dict[str, list[float]] = {}
    for c in _CATEGORICAL:
        present = [r.get(c) for r in samples if r.get(c) is not None]
        n = len(present)
        cat_freq[c] = [present.count(v) / n if n else 0.0 for v in vocab[c]]
    num_matrix = np.array([_numeric_row(r) for r in samples], dtype=float)
    # 전열 결측인 컬럼은 0으로 채워 중립화(nanmean NaN 방지) 후 결측무시 평균/표준편차.
    all_nan = np.isnan(num_matrix).all(axis=0)
    filled = np.where(all_nan, 0.0, num_matrix)
    mean = np.nanmean(filled, axis=0)
    std = np.nanstd(filled, axis=0)
    std[std == 0] = 1.0  # 상수/전열결측 피처 div0 방지

    k = min(_K, len(samples) - 1)  # 자기 제외 후 남는 이웃 수 보장
    state = {"X": None, "mean": mean, "std": std, "num_active": (~all_nan).astype(float),
             "vocab": vocab, "cat_freq": cat_freq, "k": k, "threshold": 0.0, "self_dists": None}
    det = NoveltyDetector(state)
    X = np.array([det._vectorize(r) for r in samples], dtype=float)
    state["X"] = X

    # 학습 자기거리 분포(leave-one-out) → 이례 임계값(quantile).
    self_dists = np.array([det._knn_distance(X[i], exclude_self=True) for i in range(len(X))])
    state["self_dists"] = np.sort(self_dists)
    state["threshold"] = float(np.quantile(self_dists, _NOVEL_QUANTILE))
    return det
