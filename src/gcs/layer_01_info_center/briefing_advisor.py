"""briefing_advisor — 🟡 AI 참고(advisory). RAG 학습루프 폐쇄.

축적된 코퍼스(infra/log, 과거 임무의 위협판정→실제 outcome)를 다음 임무 브리핑 시점에
회수해, NLP 가 뽑은 위협 신호별 **이력 캘리브레이션 advisory** 를 만든다. 코퍼스의 정본
목적 — "다음 임무 브리핑 시 NLP confidence 참고자료"(docs/RAG-corpus.md §1) — 을 실제로
소비하는 마지막 연결부다.

CRITICAL (MIL-STD-882E SCC-1, CLAUDE.md): 이 모듈은 **병렬 참고지표만** 산출한다. 결정론
판정도, NLP 신호의 confidence 도 절대 변경하지 않는다. 출력에 `advisory_only=True` 를 항상
싣고, 입력 신호를 수정하지 않는다(무변이). 운용자/GCS 가 참고용으로만 읽는다.

의존: infra/log CorpusStore.retrieve (안정 API). shared.constants.THREAT_CATALOG(설명 조회,
읽기전용). 상수를 쓰거나 바꾸지 않는다.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from onboard.shared.constants import THREAT_CATALOG

# 이력이 "충분"하다고 볼 최소 표본 수(참고 신뢰). 팀 설정값 — advisory 임계라 상수 불변 대상 아님.
ADVISORY_MIN_SAMPLES = 3


def signal_threat_events(signals: list[dict[str, Any]]) -> list[str]:
    """위협 신호에서 threat_event(T-코드)를 순서 보존·중복 제거로 추출.

    NLP 신호 중 `signal_type=="threat"` 이고 `threat` 키(T1..T7)를 가진 것만 대상.
    logistics/civil/mission_purpose 등 비-위협 신호는 무시한다.
    """
    seen: list[str] = []
    for sig in signals:
        if sig.get("signal_type") != "threat":
            continue
        t = sig.get("threat")
        if t and t not in seen:
            seen.append(t)
    return seen


def _calibration(records: list[dict[str, Any]]) -> tuple[int, float | None, dict[str, int]]:
    """회수된 레코드 → (표본수, 평균 과거 confidence, outcome 분포)."""
    n = len(records)
    if n == 0:
        return 0, None, {}
    confs = [r.get("confidence") for r in records if r.get("confidence") is not None]
    avg_conf = round(sum(confs) / len(confs), 6) if confs else None
    dist = Counter(r.get("outcome") for r in records if r.get("outcome") is not None)
    return n, avg_conf, dict(dist)


def _note(threat_event: str, desc: str, n: int, avg_conf: float | None,
          dist: dict[str, int], sufficient: bool) -> str:
    if n == 0:
        return f"{threat_event}({desc}): 유사 과거 임무 이력 없음 — 참고 없음."
    conf_txt = f"평균 과거 확신도 {avg_conf:.2f}" if avg_conf is not None else "확신도 기록 없음"
    dist_txt = ", ".join(f"{k}×{v}" for k, v in sorted(dist.items(), key=lambda x: -x[1])) or "outcome 기록 없음"
    qual = "" if sufficient else " (표본 부족 — 참고 주의)"
    return f"{threat_event}({desc}): 과거 {n}건, {conf_txt}, outcome[{dist_txt}]{qual}."


def build_briefing_advisory(
    signals: list[dict[str, Any]],
    mission_context: str | None,
    posture: dict[str, Any] | None,
    store: Any,
    *,
    generated_ts: int,
    posture_tolerance: int | None = None,
    min_samples: int = ADVISORY_MIN_SAMPLES,
    top_k: int = 50,
) -> dict[str, Any]:
    """NLP 위협 신호 + 컨텍스트 → threat_event별 이력 캘리브레이션 advisory.

    각 위협 T-코드에 대해 (mission_context, posture, threat_event) 로 코퍼스를 회수하고,
    표본수·평균 과거 confidence·outcome 분포를 요약한다. 결정에 반영하지 않는 참고용이다.

    반환: {advisory_only, mission_context, posture, generated_ts, advisories[],
           threat_events_without_history[]}
    """
    t_codes = signal_threat_events(signals)

    advisories: list[dict[str, Any]] = []
    without_history: list[str] = []

    for t in t_codes:
        records = store.retrieve(
            mission_context=mission_context,
            posture=posture,
            threat_event=t,
            top_k=top_k,
            posture_tolerance=posture_tolerance,
        )
        n, avg_conf, dist = _calibration(records)
        desc = THREAT_CATALOG.get(t, t)
        sufficient = n >= min_samples
        if n == 0:
            without_history.append(t)
        advisories.append({
            "threat_event": t,
            "threat_desc": desc,
            "sample_size": n,
            "avg_past_confidence": avg_conf,
            "outcome_distribution": dist,
            "sufficient_data": sufficient,
            "note": _note(t, desc, n, avg_conf, dist, sufficient),
        })

    return {
        "advisory_only": True,
        "mission_context": mission_context,
        "posture": posture,
        "generated_ts": generated_ts,
        "advisories": advisories,
        "threat_events_without_history": without_history,
    }
