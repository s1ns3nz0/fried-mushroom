"""04. Threat Modeling 오케스트레이터.

Step A(국면) → B(신호→위협) → C(확신도·킬체인) → D(potential_outcome).
RAC 산출·candidates 정렬은 여기 없음 (05 소관). primary 선택만 한다.
"""

from __future__ import annotations

from onboard.layer_04_threat import (
    step_a_phase,
    step_b_mapping,
    step_c_confidence,
    step_d_outcome,
)
from onboard.shared.schemas import ThreatCandidate, ThreatModelingOutput


def _pick_primary(
    candidates: list[ThreatCandidate],
) -> ThreatCandidate | None:
    """match_count 최다, 동률이면 avg_weight 높은 쪽. 정렬은 하지 않는다."""
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda c: (c["match_count"], c.get("_avg_weight", 0.0)),  # type: ignore[typeddict-item]
    )


def _strip_internal(candidate: ThreatCandidate) -> ThreatCandidate:
    return {k: v for k, v in candidate.items() if k != "_avg_weight"}  # type: ignore[return-value]


def run(
    abstraction: "dict",
    cycle_context: dict | None = None,
) -> ThreatModelingOutput:
    declared_phase, phase_conf = step_a_phase.run(abstraction)  # type: ignore[arg-type]
    matched, exposure = step_b_mapping.run(abstraction)  # type: ignore[arg-type]
    scored = step_c_confidence.run(matched, declared_phase)
    candidates = step_d_outcome.run(scored)

    primary = _pick_primary(candidates)
    if primary is not None:
        primary = _strip_internal(primary)
    clean_candidates = [_strip_internal(c) for c in candidates]

    return {
        "declared_phase": declared_phase,
        "mission_phase_confidence": phase_conf,
        "candidates": clean_candidates,
        "primary": primary,
        "background_exposure_score": exposure,
        "cycle_context": cycle_context or {},
    }
