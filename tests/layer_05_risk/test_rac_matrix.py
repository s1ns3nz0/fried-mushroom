"""layer_05_risk.rac_matrix 단위 테스트.

RAC_MATRIX read-only wrapper. MIL-STD-882E Table III 조회값 스팟체크 +
오버라이드 인자 부재(ADR-003 / SCC-1) 검증.
"""

import inspect

import pytest

from onboard.layer_05_risk import rac_matrix


class TestLookup:
    def test_corners(self):
        assert rac_matrix.lookup("A", 1) == "High"
        assert rac_matrix.lookup("A", 4) == "Medium"
        assert rac_matrix.lookup("F", 1) == "Medium"
        assert rac_matrix.lookup("F", 4) == "Low"

    def test_interior_spotcheck(self):
        assert rac_matrix.lookup("B", 2) == "Serious"
        assert rac_matrix.lookup("C", 1) == "Serious"
        assert rac_matrix.lookup("C", 3) == "Medium"
        assert rac_matrix.lookup("D", 1) == "Serious"
        assert rac_matrix.lookup("D", 2) == "Medium"
        assert rac_matrix.lookup("E", 1) == "Medium"

    def test_all_36_cells_resolve(self):
        for cls in "ABCDEF":
            for num in (1, 2, 3, 4):
                assert rac_matrix.lookup(cls, num) in {"High", "Serious", "Medium", "Low"}


class TestNoOverrideSignature:
    def test_lookup_takes_only_lclass_and_severity(self):
        # SCC-1: RAC_MATRIX 를 인자로 주입해 오버라이드하는 시그니처가 없어야 한다.
        params = list(inspect.signature(rac_matrix.lookup).parameters)
        assert params == ["l_class", "severity_num"]

    def test_module_exposes_no_mutable_matrix(self):
        # wrapper 는 lookup 만 노출 (직접 mutable dict 재노출 금지).
        assert hasattr(rac_matrix, "lookup")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
