"""layer_05_risk.likelihood 단위 테스트.

base_rate 조회, l_value_to_class 등급화, posture_shift_steps, shift_class 를
D4D `05. Risk Assessment` / `D-1. Risk Assessment Spec` 손계산 기준으로 검증.
"""

import pytest

from onboard.layer_05_risk import likelihood


class TestBaseRate:
    def test_physical_context_sensitive(self):
        # PHYSICAL(T3/T4) 은 (event, mission_context) 로 조회.
        assert likelihood.base_rate("T3", "정찰") == 0.15
        assert likelihood.base_rate("T3", "타격") == 0.35
        assert likelihood.base_rate("T3", "호송") == 0.20
        assert likelihood.base_rate("T4", "정찰") == 0.08
        assert likelihood.base_rate("T4", "타격") == 0.20

    def test_remote_navigation_context_invariant(self):
        # REMOTE/NAVIGATION 은 컨텍스트 무관 단일값 (context 인자 무시).
        assert likelihood.base_rate("T1", "정찰") == 0.12
        assert likelihood.base_rate("T1", "타격") == 0.12
        assert likelihood.base_rate("T2", "정찰") == 0.10
        assert likelihood.base_rate("T5", "호송") == 0.08
        assert likelihood.base_rate("T7", "수송") == 0.10


class TestLValueToClass:
    def test_boundaries(self):
        assert likelihood.l_value_to_class(0.6) == "A"
        assert likelihood.l_value_to_class(0.5) == "A"
        assert likelihood.l_value_to_class(0.4) == "B"
        assert likelihood.l_value_to_class(0.3) == "B"
        assert likelihood.l_value_to_class(0.15) == "C"
        assert likelihood.l_value_to_class(0.05) == "D"
        assert likelihood.l_value_to_class(0.01) == "E"

    def test_below_all_thresholds_is_f(self):
        # 0.005 < 0.01 → F (constants.L_VALUE_TO_CLASS_THRESHOLDS 최하 0.01="E").
        assert likelihood.l_value_to_class(0.005) == "F"
        assert likelihood.l_value_to_class(0.0) == "F"


class TestPostureShiftSteps:
    def test_kinetic_ew_uses_min_watchcon_defcon(self):
        # 물리·EW계(T1/T3/T4/T5/T7) 는 min(watchcon, defcon) 기준.
        posture = {"watchcon": 2, "defcon": 3, "infocon": 5}
        assert likelihood.posture_shift_steps(posture, "T4") == 2  # level=2 → 2
        assert likelihood.posture_shift_steps(posture, "T3") == 2

    def test_cyber_uses_infocon(self):
        # 사이버계(T2) 는 infocon 기준 (다른 축).
        posture = {"watchcon": 2, "defcon": 2, "infocon": 4}
        assert likelihood.posture_shift_steps(posture, "T2") == 0  # infocon 4 → 0
        posture2 = {"watchcon": 5, "defcon": 5, "infocon": 3}
        assert likelihood.posture_shift_steps(posture2, "T2") == 1  # infocon 3 → 1

    def test_level_thresholds(self):
        # level>=4 → 0, level==3 → 1, level<=2 → 2 (D-1 §3).
        assert likelihood.posture_shift_steps({"watchcon": 5, "defcon": 5}, "T3") == 0
        assert likelihood.posture_shift_steps({"watchcon": 4, "defcon": 4}, "T3") == 0
        assert likelihood.posture_shift_steps({"watchcon": 3, "defcon": 3}, "T3") == 1
        assert likelihood.posture_shift_steps({"watchcon": 2, "defcon": 1}, "T3") == 2

    def test_missing_keys_default_to_peacetime(self):
        # 키 누락 시 평시(5) 로 보수적 처리 → steps 0.
        assert likelihood.posture_shift_steps({}, "T3") == 0
        assert likelihood.posture_shift_steps({}, "T2") == 0


class TestShiftClass:
    def test_shift_toward_a(self):
        assert likelihood.shift_class("C", 2) == "A"
        assert likelihood.shift_class("C", 1) == "B"
        assert likelihood.shift_class("D", 2) == "B"
        assert likelihood.shift_class("C", 0) == "C"

    def test_upper_bound_clamped_at_a(self):
        assert likelihood.shift_class("A", 2) == "A"
        assert likelihood.shift_class("B", 5) == "A"

    def test_lower_bound_clamped_at_f(self):
        # 음수 steps (하향) 는 F 아래로 내려가지 않음.
        assert likelihood.shift_class("F", -1) == "F"
        assert likelihood.shift_class("E", -3) == "F"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
