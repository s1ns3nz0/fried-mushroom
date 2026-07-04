"""layer_05_risk.severity 단위 테스트.

potential_outcome → severity 라벨 매핑 + 예비기체/강제격상 override 검증
(D4D `05. Risk Assessment` §S, `D-1` §4).
"""

import pytest

from onboard.layer_05_risk import severity


class TestSeverityLabel:
    def test_catastrophic_override_is_noop(self):
        # T2 → hull_loss → Catastrophic(1). 이미 최상위라 예비기체 없어도 격상 무효.
        label, num = severity.severity_label("T2", spare_asset_available=False)
        assert (label, num) == ("Catastrophic", 1)
        label2, num2 = severity.severity_label("T2", spare_asset_available=True)
        assert (label2, num2) == ("Catastrophic", 1)

    def test_spare_absent_escalates_one_step(self):
        # T1 → mission_abort → Marginal(3). 예비기체 없음 → Critical(2).
        assert severity.severity_label("T1", spare_asset_available=True) == ("Marginal", 3)
        assert severity.severity_label("T1", spare_asset_available=False) == ("Critical", 2)

    def test_forced_override_escalates_even_with_spare(self):
        # forced_override=True 면 예비기체 있어도 한 단계 격상.
        assert severity.severity_label(
            "T1", spare_asset_available=True, forced_override=True
        ) == ("Critical", 2)

    def test_attrition_kill_baseline(self):
        # T3 → attrition_kill → Critical(2), 예비기체 있으면 그대로.
        assert severity.severity_label("T3", spare_asset_available=True) == ("Critical", 2)
        # 예비기체 없음 → Catastrophic(1).
        assert severity.severity_label("T3", spare_asset_available=False) == ("Catastrophic", 1)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
