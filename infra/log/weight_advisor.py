"""weight_advisor — 결과검증 신뢰도 캘리브레이션 advisory (RAG 코퍼스 라운드 3 §2).

코퍼스 학습레코드(라운드 1·2) 를 읽어 위협별 판정 confidence 가 실제 outcome 대비 과신/과소한지
**제안 리포트**만 낸다. advisory-only — `shared/constants` 를 읽지도 쓰지도 않으며 어떤 상수도
바꾸지 않는다 (MIL-STD-882E SCC-1). 상수 반영은 D4D 문서-우선 + Lead 승인 후 별도 라운드에서만.

설계 정본: docs/RAG-corpus-round3.md.
"""

from __future__ import annotations

from typing import Any

# outcome → 이진 라벨 (성공=1 / 실패=0 / 그 외·None=제외). 정본: RAG-corpus-round3.md §4.
_SUCCESS_OUTCOMES = frozenset({"rtb_success", "mission_success", "evaded", "arrived"})
_FAILURE_OUTCOMES = frozenset({"lost", "captured", "mission_abort", "shotdown"})

_LOW_SAMPLE_N = 5  # n < 5 이면 신뢰구간 넓음 경고.
_ROUND = 4


def outcome_label(outcome: Any) -> int | None:
    """outcome 문자열 → 1(성공)/0(실패)/None(미분류·제외)."""
    if outcome in _SUCCESS_OUTCOMES:
        return 1
    if outcome in _FAILURE_OUTCOMES:
        return 0
    return None


def confidence_calibration(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """위협(threat_event)별 confidence vs outcome 캘리브레이션.

    outcome 이 분류 가능한 레코드만 표본. 표본 없는 위협은 출력하지 않는다.
    반환은 threat_event 오름차순(결정론).
    """
    buckets: dict[str, list[tuple[float, int]]] = {}
    for r in records:
        label = outcome_label(r.get("outcome"))
        if label is None:
            continue
        conf = r.get("confidence")
        if conf is None:
            continue
        buckets.setdefault(r["threat_event"], []).append((float(conf), label))

    rows: list[dict[str, Any]] = []
    for threat_event in sorted(buckets):
        samples = buckets[threat_event]
        n = len(samples)
        mean_conf = sum(c for c, _ in samples) / n
        hit_rate = sum(lbl for _, lbl in samples) / n
        calib_error = mean_conf - hit_rate
        rows.append({
            "threat_event": threat_event,
            "n": n,
            "mean_confidence": round(mean_conf, _ROUND),
            "hit_rate": round(hit_rate, _ROUND),
            "calib_error": round(calib_error, _ROUND),
            "low_sample": n < _LOW_SAMPLE_N,
            "note": _calibration_note(calib_error, threat_event),
        })
    return rows


def _calibration_note(calib_error: float, threat_event: str) -> str:
    if calib_error > 0.1:
        return f"overconfident(과신) — {threat_event} 트리거 채널군 가중치 검토 권고"
    if calib_error < -0.1:
        return f"underconfident(과소) — {threat_event} confidence 표 검토 권고"
    return "well-calibrated(적정)"


def build_advisory_report(records: list[dict[str, Any]], generated_ts: int) -> dict[str, Any]:
    """전체 advisory 리포트 (RAG-corpus-round3.md §4).

    channel_weight_proposals 는 채널 귀속 스키마 확장(§1·§3) 전까지 항상 빈 리스트.
    generated_ts 는 유즈사이트 주입(파이프라인 순수성) — 시간 조회 금지.
    """
    return {
        "generated_ts": generated_ts,
        "corpus_size": len(records),
        "confidence_calibration": confidence_calibration(records),
        "channel_weight_proposals": [],
        "guardrails": {
            "advisory_only": True,
            "applied": False,
            "requires": "D4D 04.md §Step C 문서수정 + Lead 승인 후 별도 라운드",
        },
    }
