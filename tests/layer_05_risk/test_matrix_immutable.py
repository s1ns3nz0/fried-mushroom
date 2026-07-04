"""RAC_MATRIX 불변성 재확인 (ADR-003 / MIL-STD-882E SCC-1).

Step 1 의 MappingProxyType 보증이 05 wrapper 경유에서도 유지되는지 확인.
AI 든 코드든 매트릭스를 mutation 할 수 없어야 한다.
"""

import pytest

from onboard.layer_05_risk import rac_matrix
from onboard.shared.constants import RAC_MATRIX


def test_matrix_assignment_raises_typeerror():
    with pytest.raises(TypeError):
        RAC_MATRIX[("A", 1)] = "Low"  # type: ignore[index]


def test_lookup_reads_same_source_matrix():
    # wrapper 가 별도 복제본이 아니라 SSOT 상수를 그대로 읽는다.
    assert rac_matrix.lookup("A", 1) == RAC_MATRIX[("A", 1)]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
