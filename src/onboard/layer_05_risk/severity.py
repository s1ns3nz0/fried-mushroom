"""05 Risk Assessment — S(심각도) 결정론 계산 + override.

potential_outcome(04 에서 확정) → MIL-STD-882E 심각도 라벨/순위.
예비기체 없음 또는 강제격상(자폭드론 조우 등) 이면 한 단계 격상.
이미 Catastrophic(1) 이면 격상 무효 (D4D `05. Risk Assessment` / `D-1` §4).
"""

from __future__ import annotations

from ..shared.constants import (
    OUTCOME_TO_SEVERITY,
    POTENTIAL_OUTCOME_MAP,
    SEVERITY_ORDER,
)

# severity_num → label 역매핑 (격상 후 라벨 복원용).
_LABEL_BY_NUM: dict[int, str] = {num: label for label, num in SEVERITY_ORDER.items()}


def severity_label(
    threat_event: str,
    spare_asset_available: bool,
    forced_override: bool = False,
) -> tuple[str, int]:
    """(severity_label_final, severity_num_final) 반환.

    label = OUTCOME_TO_SEVERITY[POTENTIAL_OUTCOME_MAP[threat_event]].
    예비기체 없음 또는 forced_override → max(1, num-1) (1=Catastrophic 은 이미 최상위).
    """
    label = OUTCOME_TO_SEVERITY[POTENTIAL_OUTCOME_MAP[threat_event]]
    num = SEVERITY_ORDER[label]
    if (not spare_asset_available) or forced_override:
        num_final = max(1, num - 1)
    else:
        num_final = num
    return _LABEL_BY_NUM[num_final], num_final
