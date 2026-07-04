"""trend — 🔵 파생 읽기전용. 위협 궤적 조기경보 advisory (cross-cycle).

파이프라인은 무상태(ADR-004)라 사이클마다 위협을 독립 판정한다. 그래서 "위협이 시간에
따라 악화되고 있다"는 궤적은 어떤 단일 사이클도 못 본다. 이 모듈은 파이프라인 위에 얹는
관찰자로, 최근 N 사이클 결과의 궤적을 보고 조기경보를 낸다:

  - RAC 악화(RAC_ORDER 감소)
  - 킬체인 진행(초기→중기→후기)
  - 확신도 상승(지속 위협)
  - 위협 지속(같은 threat_event 반복)

CRITICAL (SCC-1): advisory 만 산출한다. 어떤 사이클 결과도 변경하지 않고 입력을 변이하지
않는다(derived_readonly 관찰자). RAC_ORDER / KILL_CHAIN_STAGE_ORDER(읽기전용)만 참조하며
어떤 상수도 쓰거나 바꾸지 않는다. 무상태 파이프라인의 결정을 대체하지 않는다.
"""

from __future__ import annotations

from typing import Any

from onboard.shared.constants import KILL_CHAIN_STAGE_ORDER, RAC_ORDER

# 위협이 "지속"이라 볼 최소 연속 사이클 수(참고 임계). advisory라 상수 불변 대상 아님.
_MIN_PERSIST = 2


def _track(result: dict[str, Any]) -> dict[str, Any]:
    """한 사이클 결과에서 궤적 관련 값 추출.

    threat_event 와 confidence/kill_chain/rac 를 **같은 위협** 기준으로 뽑는다 — 04(match_count)
    와 05/06(risk 정렬)의 지배 위협이 다를 수 있으므로, 결정에 쓰인 primary_threat_event 를
    기준으로 그 코드에 맞는 후보(risk→threat candidates→threat.primary)에서 속성을 조회한다.
    """
    result = result or {}
    threat = result.get("threat") or {}
    risk = result.get("risk") or {}
    response = result.get("response") or {}
    plan = result.get("flight_plan") or {}
    te = response.get("primary_threat_event") or (threat.get("primary") or {}).get("threat_event")

    src: dict[str, Any] | None = None
    for pool in (risk.get("candidates") or [], threat.get("candidates") or []):
        src = next((c for c in pool if c.get("threat_event") == te), None)
        if src:
            break
    if src is None:
        p = threat.get("primary") or {}
        src = p if p.get("threat_event") == te else {}

    return {
        "threat_event": te,
        "confidence": src.get("confidence"),
        "kill_chain_stage": src.get("kill_chain_stage") or response.get("kill_chain_stage"),
        "rac": src.get("rac") or response.get("rac") or risk.get("ambient_rac"),
        "flight_action": plan.get("flight_action") or response.get("flight_action"),
    }


def _rac_rank(rac: str | None) -> int | None:
    return RAC_ORDER.get(rac) if rac else None


def _stage_rank(stage: str | None) -> int | None:
    return KILL_CHAIN_STAGE_ORDER.get(stage) if stage else None


def assess_threat_trend(
    results: list[dict[str, Any]],
    *,
    window: int | None = None,
    min_persist: int = _MIN_PERSIST,
) -> dict[str, Any]:
    """사이클 결과 시퀀스(오래된→최신) → 위협 궤적 조기경보 advisory.

    window 를 주면 최근 window 개만 본다. 반환:
    {escalating, level(none|watch|warning|critical), signals[], primary_threat_event,
     rac_from, rac_to, window_size, advisory_only, note}
    """
    seq = list(results or [])
    if window is not None and window > 0:
        seq = seq[-window:]
    tracks = [_track(r) for r in seq]

    signals: list[str] = []

    # 지배 위협 = **최신 사이클**의 threat_event. 최신 사이클이 무위협이면 위협은 해소된
    # 것이므로 궤적 경보를 내지 않는다(윈도우 내 옛 위협이 남아 있어도 stale 경보 금지).
    primary_te = tracks[-1]["threat_event"] if tracks else None

    if not primary_te:
        return _report(False, "none", [], None, None, None, len(seq))

    # 같은(최신) 위협이 연속으로 몇 사이클 지속되는지 (뒤에서부터).
    persist = 0
    for t in reversed(tracks):
        if t["threat_event"] == primary_te:
            persist += 1
        else:
            break
    if persist >= min_persist:
        signals.append("persistent_threat")

    # 궤적 신호는 **현재 연속 스트릭**(뒤에서 persist 개)의 첫→끝만 비교한다. 윈도우 앞쪽의
    # 같은 코드지만 끊겼던 옛 위협(예: T3 → T4 → T3)은 stale 이므로 포함하지 않는다.
    persist_slice = tracks[-persist:]
    first, last = persist_slice[0], persist_slice[-1]

    rac_from, rac_to = first["rac"], last["rac"]
    rf, rt = _rac_rank(rac_from), _rac_rank(rac_to)
    if rf is not None and rt is not None and rt < rf:  # 숫자 감소 = 악화
        signals.append("rac_escalating")

    sf, st = _stage_rank(first["kill_chain_stage"]), _stage_rank(last["kill_chain_stage"])
    if sf is not None and st is not None and st > sf:
        signals.append("kill_chain_advancing")

    cf, ct = first["confidence"], last["confidence"]
    if isinstance(cf, (int, float)) and isinstance(ct, (int, float)) and ct > cf + 1e-9:
        signals.append("confidence_rising")

    escalating = any(s in signals for s in ("rac_escalating", "kill_chain_advancing"))

    # 레벨: critical = 악화 + 최신 RAC High / 킬체인 후기. warning = 악화. watch = 위협 있으나 안정.
    if escalating and (rt == RAC_ORDER.get("High") or st == KILL_CHAIN_STAGE_ORDER.get("후기")):
        level = "critical"
    elif escalating:
        level = "warning"
    else:
        level = "watch"

    return _report(escalating, level, signals, primary_te, rac_from, rac_to, len(seq))


def _report(escalating, level, signals, primary_te, rac_from, rac_to, window_size):
    if level == "none":
        note = f"최근 {window_size} 사이클 내 위협 없음."
    elif escalating:
        note = (f"{primary_te} 위협 악화 궤적 감지({', '.join(signals)}) — RAC {rac_from}→{rac_to}. "
                f"조기경보 레벨={level}.")
    else:
        note = f"{primary_te} 위협 지속(안정) — RAC {rac_to}. 궤적 악화 신호 없음."
    return {
        "escalating": escalating,
        "level": level,
        "signals": signals,
        "primary_threat_event": primary_te,
        "rac_from": rac_from,
        "rac_to": rac_to,
        "window_size": window_size,
        "advisory_only": True,
        "note": note,
    }
