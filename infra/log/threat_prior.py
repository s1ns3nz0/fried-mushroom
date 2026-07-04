"""위협 사전확률 모델 — 작전 맥락 → P(threat_event) 범주형 나이브베이즈 (6번째 실 ML).

코퍼스의 작전 맥락 피처(mission_context / corridor_region / posture defcon·watchcon·infocon)와
관측된 threat_event 라벨로 범주형 나이브베이즈를 학습해, "이 임무 맥락에서 과거 어떤 위협이
우세했는가"를 사전확률로 산출한다. 결과예측기(#367, outcome)·이례성(#370, 비지도)과 달리
**threat_event 자체를 라벨로 하는 지도학습** — 서로 다른 축.

SCC-1(CLAUDE.md CRITICAL): 결정론 04 SIGNAL_TO_THREAT 매핑·RAC 판정을 절대 바꾸지 않는다.
이 산출은 계획 참고용 병렬 **사전확률** — 실제 위협 판정은 언제나 결정론 파이프라인이 지배한다.

순수 파이썬(zero-dep). 표본부족/피처 전무 시 미학습(predict → None, 하위호환).
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

_MIN_SAMPLES = 8
_CATEGORICAL = ("mission_context", "corridor_region")
_POSTURE = ("defcon", "watchcon", "infocon")


def _features(record: dict[str, Any]) -> dict[str, str]:
    """맥락 레코드 → {피처명: 이산값}. 결측 피처는 생략(패널티 없음)."""
    feats: dict[str, str] = {}
    for c in _CATEGORICAL:
        val = record.get(c)
        if val is not None:
            feats[c] = str(val)
    posture = record.get("posture") or {}
    for p in _POSTURE:
        val = posture.get(p)
        if val is not None:
            feats[p] = str(val)  # 이산 레벨(1..5)로 취급
    return feats


class ThreatPrior:
    """학습된 위협 사전확률. `predict(record)` → [(threat_event, prob)] 내림차순. 미학습 시 None."""

    def __init__(self, state: dict | None):
        self._s = state  # {log_prior, log_cond, feat_vocab_size, classes}

    @property
    def fitted(self) -> bool:
        return self._s is not None

    def predict(self, record: dict[str, Any]) -> list[tuple[str, float]] | None:
        """맥락 → 위협별 사후확률 [(threat, prob)] 내림차순. 미학습/피처 전무 시 None."""
        if self._s is None:
            return None
        feats = _features(record)
        if not feats:
            return None
        s = self._s
        # 학습에서 관측된 피처명만 사용(미관측 피처명 질의는 무시 — KeyError 방지).
        feats = {k: v for k, v in feats.items() if k in s["feat_names"]}
        if not feats:
            return None
        log_scores: dict[str, float] = {}
        for cls in s["classes"]:
            lp = s["log_prior"][cls]
            for fname, fval in feats.items():
                cond = s["log_cond"][cls].get((fname, fval))
                # 미관측 (feature=value|class) → 라플라스 하한(count 0) 로그확률.
                lp += cond if cond is not None else s["log_cond_unseen"][cls][fname]
            log_scores[cls] = lp
        # 로그공간 softmax 정규화 → 확률(합=1 유지 위해 반올림하지 않음).
        top = max(log_scores.values())
        exps = {c: math.exp(v - top) for c, v in log_scores.items()}
        z = sum(exps.values())
        probs = [(c, exps[c] / z) for c in s["classes"]]
        probs.sort(key=lambda kv: (-kv[1], kv[0]))
        return probs


def fit_threat_prior(records: list[dict[str, Any]]) -> ThreatPrior:
    """코퍼스 → 범주형 나이브베이즈. threat_event 라벨 + 피처 보유 레코드만 표본."""
    labeled = [(r, r.get("threat_event")) for r in records]
    labeled = [(_features(r), t) for r, t in labeled if t is not None]
    labeled = [(f, t) for f, t in labeled if f]  # 피처 전무 제외
    if len(labeled) < _MIN_SAMPLES:
        return ThreatPrior(None)

    classes: list[str] = []
    class_count: dict[str, int] = defaultdict(int)
    # (class,feature,value) 카운트 + feature 별 관측 값 집합(라플라스 분모).
    fv_count: dict[str, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    # (class, feature) 별 "피처가 존재한" 레코드 수 — 결측 무패널티와 일관된 분모.
    present_count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    feat_values: dict[str, set[str]] = defaultdict(set)
    for feats, cls in labeled:
        if cls not in class_count:
            classes.append(cls)
        class_count[cls] += 1
        for fname, fval in feats.items():
            fv_count[cls][(fname, fval)] += 1
            present_count[cls][fname] += 1
            feat_values[fname].add(fval)

    n = len(labeled)
    n_classes = len(classes)
    log_prior = {c: math.log((class_count[c] + 1) / (n + n_classes)) for c in classes}  # 라플라스

    # 조건부확률 로그 + 미관측값 하한(class·feature 별 분모 고정).
    log_cond: dict[str, dict[tuple[str, str], float]] = {}
    log_cond_unseen: dict[str, dict[str, float]] = {}
    for cls in classes:
        log_cond[cls] = {}
        log_cond_unseen[cls] = {}
        for fname, vals in feat_values.items():
            # 분모 = 그 피처가 존재한 레코드 수 + |V_f| (결측 무패널티와 일관).
            denom = present_count[cls][fname] + len(vals)  # 라플라스: +|V_f|
            for v in vals:
                cnt = fv_count[cls].get((fname, v), 0)
                log_cond[cls][(fname, v)] = math.log((cnt + 1) / denom)
            log_cond_unseen[cls][fname] = math.log(1 / denom)  # count 0 하한

    return ThreatPrior({
        "classes": classes,
        "feat_names": set(feat_values),  # 학습 관측 피처명 — 질의 필터용
        "log_prior": log_prior,
        "log_cond": log_cond,
        "log_cond_unseen": log_cond_unseen,
    })
