"""compound_urgency_score 후기 보너스 · 상한(0.95) 경계 단위 테스트.

as-implemented 공식(compound.py:94-97, D-1 §6 line 148-150 와 동일):

    bonus = KILL_CHAIN_LATE_BONUS(0.10) if kill_chain_stage == "후기" else 0.0
    return min(continuous_L × continuous_S + bonus, COMPOUND_UPPER_BOUND(0.95))

보너스는 "후기" 라벨에만 붙는 무조건 가산(합성 AND 조건 없음)이고, 상한 클램프는
min() 이라 경계값(정확히 0.95)에서 0.95 를 돌려준다. 모든 기대값은 손계산(주석) 기준.
"""

import pytest

from onboard.layer_05_risk import compound
from onboard.shared.constants import COMPOUND_UPPER_BOUND, KILL_CHAIN_LATE_BONUS


class TestLateBonusDelta:
    """동일 L·S, kill_chain_stage 만 다를 때 보너스 델타가 정확히 0.10 인지."""

    def test_late_vs_mid_bonus_delta_is_exactly_010(self):
        # L=0.5, S=0.6 → L×S=0.30 (상한 여유 충분, 클램프 비활성).
        #   후기: 0.30 + 0.10 = 0.40
        #   중기: 0.30 + 0.00 = 0.30
        #   델타: 0.40 - 0.30 = 0.10 == KILL_CHAIN_LATE_BONUS
        late = compound.urgency_score(0.5, 0.6, "후기")
        mid = compound.urgency_score(0.5, 0.6, "중기")
        assert late == pytest.approx(0.40, abs=1e-9)
        assert mid == pytest.approx(0.30, abs=1e-9)
        assert late - mid == pytest.approx(KILL_CHAIN_LATE_BONUS, abs=1e-9)

    def test_bonus_only_on_late_label_no_compound_condition(self):
        # 보너스는 "후기" 라벨 단독 조건 — 초기/중기/None/미지 라벨은 모두 보너스 없음.
        # L×S=0.30 이 그대로 나오면 보너스 미가산 확인.
        for stage in ("초기", "중기", None, "unknown"):
            assert compound.urgency_score(0.5, 0.6, stage) == pytest.approx(0.30, abs=1e-9)


class TestUpperBoundClamp:
    """min(..., 0.95) 상한 경계 — 비활성 / 활성 / 정확히 경계."""

    def test_clamp_inactive_just_below_cap(self):
        # 후기 경로로 보너스까지 포함해도 상한 미만 → 클램프 미적용, 원값 그대로.
        # L=0.9, S=0.94 → 0.846; + 0.10(후기) = 0.946 < 0.95.
        val = compound.urgency_score(0.9, 0.94, "후기")
        assert val == pytest.approx(0.946, abs=1e-9)
        assert val < COMPOUND_UPPER_BOUND

    def test_clamp_active_pushed_above_cap(self):
        # L=0.9, S=0.95 → 0.855; + 0.10(후기) = 0.955 > 0.95 → 0.95 로 클램프.
        val = compound.urgency_score(0.9, 0.95, "후기")
        assert val == pytest.approx(COMPOUND_UPPER_BOUND, abs=1e-9)  # 0.95

    def test_clamp_boundary_exactly_cap_no_bonus(self):
        # L×S 가 정확히 0.95(=상한)이고 보너스 없음(중기) → min(0.95, 0.95) = 0.95.
        # L=0.95, S=1.0 → 0.95.
        assert compound.urgency_score(0.95, 1.0, "중기") == pytest.approx(
            COMPOUND_UPPER_BOUND, abs=1e-9
        )

    def test_clamp_boundary_exactly_cap_with_late_bonus(self):
        # L×S + 후기보너스 가 정확히 0.95 에 안착 → min() 은 0.95 반환(경계 포함).
        # L=0.85, S=1.0 → 0.85; + 0.10 = 0.95.
        assert compound.urgency_score(0.85, 1.0, "후기") == pytest.approx(
            COMPOUND_UPPER_BOUND, abs=1e-9
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
