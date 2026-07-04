"""05 Risk Assessment — RAC 매트릭스 조회 (read-only wrapper).

RAC = RAC_MATRIX[(l_class_final, severity_num_final)]. MIL-STD-882E Table III.

CRITICAL (ADR-003 / SCC-1): 이 값은 AI 도 코드도 절대 바꾸지 않는다.
`lookup` 외에는 아무것도 노출하지 않으며, 매트릭스를 함수 인자로 받아
오버라이드하는 시그니처를 의도적으로 만들지 않는다.
"""

from __future__ import annotations

from ..shared.constants import RAC_MATRIX


def lookup(l_class: str, severity_num: int) -> str:
    """(l_class, severity_num) → RAC 등급(High/Serious/Medium/Low)."""
    return RAC_MATRIX[(l_class, severity_num)]
