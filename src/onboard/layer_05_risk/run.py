"""05. Risk Assessment 오케스트레이터.

04 의 candidates[] 각각에 L×S→RAC(결정론) 을 붙이고, AI 강화판(continuous_L/S)을
병렬로 계산해 compound_urgency_score 로 우선순위 정렬한다. RAC 매트릭스는 절대
오버라이드 불가 (ADR-003 / SCC-1). candidates 가 비면 background_exposure_score 로
ambient_rac 하한만 둔다.

orchestrator 배선: run(threat, mission_brief, link_quality=<float|None>).
STUB abstraction 경유의 04 출력(candidates=[], primary=None, phase="unknown") 과
link_quality=None 을 예외 없이 스키마 적합 최소 출력으로 처리한다.
"""

from __future__ import annotations

from ..shared.constants import AMBIENT_EXPOSURE_THRESHOLD, SEVERITY_ORDER
from ..shared.schemas import MissionBrief, RiskAssessmentOutput, ThreatModelingOutput
from . import compound, likelihood, severity
from .rac_matrix import lookup

# 연속값 출력 반올림 자릿수 (D-1 §7 계약 예시 표기).
_ROUND = 4


def run(
    threat: ThreatModelingOutput,
    mission_brief: MissionBrief,
    *,
    link_quality: float | None = None,
) -> RiskAssessmentOutput:
    candidates_in = threat.get("candidates") or []

    if not candidates_in:
        background = threat.get("background_exposure_score") or 0.0
        ambient = "Medium" if background >= AMBIENT_EXPOSURE_THRESHOLD else "Low"
        return {"candidates": [], "ambient_rac": ambient}

    mission_context = mission_brief["mission_context"]
    posture = mission_brief["posture"]
    profile = mission_brief.get("drone_profile", {})
    # 예비기체/배터리는 examples 상 drone_profile 에 중첩. top-level 도 폴백 허용.
    spare_available = profile.get(
        "spare_asset_available", mission_brief.get("spare_asset_available", True)
    )
    battery_pct = profile.get("battery_pct", mission_brief.get("battery_pct"))

    assessed = [
        _assess_candidate(
            candidate,
            mission_context=mission_context,
            posture=posture,
            spare_available=spare_available,
            battery_pct=battery_pct,
            link_quality=link_quality,
            profile=profile,
        )
        for candidate in candidates_in
    ]

    # 정렬: compound_urgency_score 내림차순 → severity_num_final 오름차순 → match_count 내림차순.
    assessed.sort(
        key=lambda item: (
            -item["candidate"]["compound_urgency_score"],
            item["severity_num_final"],
            -item["candidate"]["match_count"],
        )
    )

    candidates_out = []
    for rank, item in enumerate(assessed, start=1):
        out = item["candidate"]
        out["priority_rank"] = rank
        candidates_out.append(out)

    return {"candidates": candidates_out, "ambient_rac": None}


def _assess_candidate(
    candidate: dict,
    *,
    mission_context: str,
    posture: dict,
    spare_available: bool,
    battery_pct: float | None,
    link_quality: float | None,
    profile: dict,
) -> dict:
    """후보 1건의 결정론 RAC + AI 강화판 병렬지표 산출.

    반환: {"candidate": RiskCandidate dict, "severity_num_final": int}
    (severity_num_final 은 정렬 타이브레이크용 내부값 — 출력 dict 에는 넣지 않는다.)
    """
    threat_event = candidate["threat_event"]

    # --- L (결정론) ---
    base = likelihood.base_rate(threat_event, mission_context)
    steps = likelihood.posture_shift_steps(posture, threat_event)
    l_class_final = likelihood.shift_class(likelihood.l_value_to_class(base), steps)

    # --- S (결정론 + override) ---
    forced = bool(
        candidate.get("forced_severity_override")
        or profile.get("forced_severity_override")
    )
    sev_label, sev_num = severity.severity_label(threat_event, spare_available, forced)

    # --- RAC (결정론 매트릭스, AI 배제) ---
    rac = lookup(l_class_final, sev_num)

    # --- AI 강화판 (병렬 참고지표, RAC 불변) ---
    cont_l = compound.continuous_l(base, candidate["confidence"])
    l_class_ai = likelihood.shift_class(likelihood.l_value_to_class(cont_l), steps)
    cont_s = compound.continuous_s(sev_label, battery_pct, spare_available, link_quality)
    rac_ai = lookup(l_class_ai, compound.s_num_from_continuous(cont_s))
    reliability = compound.cross_check_reliability(rac, rac_ai)

    urgency = compound.urgency_score(cont_l, cont_s, candidate["kill_chain_stage"])

    risk_candidate = {
        **candidate,  # 04 필드 보존 (ThreatCandidate 상속 계약).
        "rac": rac,
        "l_class_final": l_class_final,
        "severity_label_final": sev_label,
        "compound_risk_assessment": {
            "continuous_L": round(cont_l, _ROUND),
            "continuous_S": round(cont_s, _ROUND),
            "rac_ai_equivalent": rac_ai,
            "ai_reliability": reliability,
        },
        "compound_urgency_score": round(urgency, _ROUND),
        "priority_rank": 0,  # 정렬 후 채운다.
    }
    # 04 가 내부 forced 플래그를 candidate 에 실어 보냈다면 출력에서 제거
    # (RiskCandidate 스키마에 없는 키 → contracts helper reject 방지).
    risk_candidate.pop("forced_severity_override", None)

    return {"candidate": risk_candidate, "severity_num_final": sev_num}
