"""layer_05_risk.compound 단위 테스트.

AI 강화판 병렬 참고지표: continuous_L/S, margin_penalty, 교차검증,
compound_urgency_score. RAC 자체엔 영향 없음 (ADR-003). 값은 D-1 §6 손계산 기준.
"""

import pytest

from onboard.layer_05_risk import compound


class TestContinuousL:
    def test_scaled_by_confidence_over_anchor(self):
        # base 0.15, confidence 0.917 → 0.15*(0.917/0.7)=0.1965.
        assert compound.continuous_l(0.15, 0.917) == pytest.approx(0.1965, abs=1e-4)

    def test_anchor_confidence_is_identity(self):
        # confidence == 앵커(0.7) → base 그대로.
        assert compound.continuous_l(0.10, 0.70) == pytest.approx(0.10, abs=1e-9)

    def test_scaled_below_base_times_three_cap(self):
        # confidence 최대(0.95) 여도 factor=0.95/0.7≈1.357 이라 base*3 cap 은 실질 미도달.
        # continuous_l(0.10, 0.95) = 0.10*1.357 ≈ 0.1357 (cap 0.30 미적용).
        assert compound.continuous_l(0.10, 0.95) == pytest.approx(0.1357, abs=1e-4)

    def test_global_cap_095(self):
        # scaled 가 0.95 를 넘으면 방어적 상한 0.95 로 캡 (실 base_rate 로는 도달 불가한 방어선).
        assert compound.continuous_l(0.80, 0.95) == pytest.approx(0.95, abs=1e-9)


class TestMarginPenalty:
    def test_no_penalty(self):
        assert compound.margin_penalty(65, True, 0.9) == pytest.approx(0.0)

    def test_battery_low(self):
        assert compound.margin_penalty(25, True, 0.9) == pytest.approx(0.10)

    def test_spare_absent(self):
        assert compound.margin_penalty(65, False, 0.9) == pytest.approx(0.05)

    def test_link_low(self):
        assert compound.margin_penalty(65, True, 0.4) == pytest.approx(0.05)

    def test_all_penalties_stack(self):
        assert compound.margin_penalty(25, False, 0.4) == pytest.approx(0.20)

    def test_none_battery_and_link_are_ignored(self):
        # 데이터 없음(None) 은 패널티 없음 (graceful degradation).
        assert compound.margin_penalty(None, True, None) == pytest.approx(0.0)
        assert compound.margin_penalty(None, False, None) == pytest.approx(0.05)


class TestContinuousS:
    def test_base_score_no_penalty(self):
        assert compound.continuous_s("Critical", 65, True, 0.9) == pytest.approx(0.60)
        assert compound.continuous_s("Marginal", 65, True, 0.9) == pytest.approx(0.30)

    def test_capped_at_095(self):
        # Catastrophic 0.90 + battery 0.10 = 1.00 → 0.95 캡.
        assert compound.continuous_s("Catastrophic", 25, True, 0.9) == pytest.approx(0.95)


class TestSNumFromContinuous:
    def test_thresholds(self):
        assert compound.s_num_from_continuous(0.95) == 1
        assert compound.s_num_from_continuous(0.75) == 1
        assert compound.s_num_from_continuous(0.60) == 2
        assert compound.s_num_from_continuous(0.45) == 2
        assert compound.s_num_from_continuous(0.30) == 3
        assert compound.s_num_from_continuous(0.20) == 3
        assert compound.s_num_from_continuous(0.10) == 4


class TestCrossCheckReliability:
    def test_normal_when_close(self):
        assert compound.cross_check_reliability("Serious", "Serious") == "normal"
        assert compound.cross_check_reliability("High", "Serious") == "normal"  # diff 1

    def test_low_when_two_or_more_apart(self):
        assert compound.cross_check_reliability("High", "Medium") == "low"  # diff 2
        assert compound.cross_check_reliability("High", "Low") == "low"  # diff 3


class TestUrgencyScore:
    def test_late_kill_chain_bonus(self):
        # 0.1965*0.95 + 0.1(후기) = 0.2867.
        assert compound.urgency_score(0.1965, 0.95, "후기") == pytest.approx(0.2867, abs=1e-4)

    def test_no_bonus_for_mid_early(self):
        assert compound.urgency_score(0.2166, 0.95, "중기") == pytest.approx(0.2057, abs=1e-4)
        assert compound.urgency_score(0.2166, 0.95, "초기") == pytest.approx(0.2057, abs=1e-4)

    def test_capped_at_095(self):
        assert compound.urgency_score(0.95, 0.95, "후기") == pytest.approx(0.95)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
