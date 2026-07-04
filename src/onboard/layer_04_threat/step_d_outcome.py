"""Step D — potential_outcome 매핑.

각 후보에 POTENTIAL_OUTCOME_MAP[threat_event] 를 붙여 ThreatCandidate 로 만든다.
"""

from __future__ import annotations

from onboard.shared.constants import POTENTIAL_OUTCOME_MAP
from onboard.shared.schemas import ThreatCandidate


def run(scored: list[dict]) -> list[ThreatCandidate]:
    candidates: list[ThreatCandidate] = []
    for c in scored:
        candidate = dict(c)  # scored 내부 필드(_avg_weight 등)는 그대로 보존
        candidate["potential_outcome"] = POTENTIAL_OUTCOME_MAP.get(
            c["threat_event"], "unknown"
        )
        candidates.append(candidate)  # type: ignore[arg-type]
    return candidates
