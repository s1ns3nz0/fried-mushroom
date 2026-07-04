"""종단 골든 케이스 (C-1 8·9절 + T7/normal)."""

from __future__ import annotations

from onboard.layer_04_threat import run


class TestT3Golden:
    def test_t3_end_to_end(self, abstraction_t3) -> None:
        out = run.run(abstraction_t3)
        assert out["declared_phase"] == "LOITER_ROI"
        assert out["mission_phase_confidence"] == 0.9
        # 실측 03 terrain_class(open_field) exposure_score=0.8 (Refs #41)
        assert out["background_exposure_score"] == 0.8
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
        # 실측 03 기준(Refs #41): match_count=2 (link_status q=0.04<Q_min & w<W_min 제외),
        # 중기(avg_weight=0.325<0.35). confidence 유도:
        #   log_odds = 0.4*logit(0.9)+0.25*logit(0.9) = 0.65*2.1972 = 1.4282
        #   ai = sigmoid(1.4282) = 0.807, |0.807-det(0.9)|=0.093≤0.15 → ai, WAYPOINT 배수 없음
        assert primary["match_count"] == 2
        assert primary["confidence"] == 0.807
        assert primary["kill_chain_stage"] == "중기"


class TestT5Golden:
    def test_t5_end_to_end(self, abstraction_t5) -> None:
        out = run.run(abstraction_t5)
        assert out["declared_phase"] == "WAYPOINT"
        primary = out["primary"]
        assert primary is not None
        assert primary["threat_event"] == "T5"
        assert primary["potential_outcome"] == "mission_abort"
        # 실측 03 기준: 단일채널 terrain_class(w=0.25, q=0.65) 만 매칭 → match_count=1.
        #   det = 0.70(match_count 1)
        #   log_odds = 0.25*logit(0.65) = 0.25*0.6190 = 0.1548
        #   ai = sigmoid(0.1548) = 0.5386, |0.5386-0.70|=0.161 > 0.15 → 결정론 폴백
        #   (WAYPOINT,T5) 배수 없음 → confidence = 0.70
        assert primary["match_count"] == 1
        assert primary["confidence"] == 0.7
        assert primary["confidence_source"] == "deterministic"
        assert primary["kill_chain_stage"] == "중기"
        assert "_avg_weight" not in primary


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
        # 실측 03 terrain_class(open_field) exposure_score=0.8 (Refs #41)
        assert out["background_exposure_score"] == 0.8

    def test_cycle_context_passthrough(self, abstraction_normal) -> None:
        ctx = {"optimal_terrain_bearing_deg": 0.0}
        out = run.run(abstraction_normal, cycle_context=ctx)
        assert out["cycle_context"] == ctx
