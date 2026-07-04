"""종단 골든 케이스 (C-1 8·9절 + T7/normal)."""

from __future__ import annotations

from onboard.layer_04_threat import run


class TestT3Golden:
    def test_t3_end_to_end(self, abstraction_t3) -> None:
        out = run.run(abstraction_t3)
        assert out["declared_phase"] == "LOITER_ROI"
        assert out["mission_phase_confidence"] == 0.9
        assert out["background_exposure_score"] == 0.4
        primary = out["primary"]
        assert primary is not None
        assert primary["threat_event"] == "T3"
        assert primary["match_count"] >= 2
        assert primary["confidence"] >= 0.9
        assert primary["potential_outcome"] == "attrition_kill"
        assert primary["kill_chain_stage"] == "후기"
        # C-1 8절 손계산: 0.917
        assert primary["confidence"] == 0.917
        # 내부 정렬용 필드는 최종 출력에서 제거
        assert "_avg_weight" not in primary


class TestT4Golden:
    def test_t4_end_to_end(self, abstraction_t4) -> None:
        out = run.run(abstraction_t4)
        assert out["declared_phase"] == "WAYPOINT"
        primary = out["primary"]
        assert primary is not None
        assert primary["threat_event"] == "T4"
        assert primary["potential_outcome"] == "hull_loss"
        # C-1 9절 손계산: match_count=2 (link_status 는 W_min 제외), confidence 0.758, 중기
        assert primary["match_count"] == 2
        assert primary["confidence"] == 0.758
        assert primary["kill_chain_stage"] == "중기"


class TestT7Golden:
    def test_t7_end_to_end(self, abstraction_t7) -> None:
        out = run.run(abstraction_t7)
        assert out["declared_phase"] == "LAND"
        primary = out["primary"]
        assert primary is not None
        assert primary["threat_event"] == "T7"
        assert primary["potential_outcome"] == "attrition_kill"


class TestNormalGolden:
    def test_normal_end_to_end(self, abstraction_normal) -> None:
        out = run.run(abstraction_normal)
        assert out["candidates"] == []
        assert out["primary"] is None
        assert out["background_exposure_score"] == 0.2

    def test_cycle_context_passthrough(self, abstraction_normal) -> None:
        ctx = {"optimal_terrain_bearing_deg": 0.0}
        out = run.run(abstraction_normal, cycle_context=ctx)
        assert out["cycle_context"] == ctx
