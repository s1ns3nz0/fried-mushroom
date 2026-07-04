"""constants.py 검증 — D4D 문서 표와 일치하는지 스팟체크 + 불변성."""

import pytest

from onboard.shared import constants as C


# ---------------------------------------------------------------------------
# RAC_MATRIX (6x4)
# ---------------------------------------------------------------------------


class TestRACMatrix:
    def test_has_24_entries(self) -> None:
        assert len(C.RAC_MATRIX) == 24  # 6 l_class x 4 severity

    def test_corner_A1_high(self) -> None:
        assert C.RAC_MATRIX[("A", 1)] == "High"

    def test_corner_F4_low(self) -> None:
        assert C.RAC_MATRIX[("F", 4)] == "Low"

    def test_corner_A4_medium(self) -> None:
        assert C.RAC_MATRIX[("A", 4)] == "Medium"

    def test_corner_F1_medium(self) -> None:
        assert C.RAC_MATRIX[("F", 1)] == "Medium"

    def test_all_l_classes_covered(self) -> None:
        for l_class in ("A", "B", "C", "D", "E", "F"):
            for severity in (1, 2, 3, 4):
                assert (l_class, severity) in C.RAC_MATRIX

    def test_is_immutable(self) -> None:
        with pytest.raises(TypeError):
            C.RAC_MATRIX[("A", 1)] = "Low"  # type: ignore[index]


# ---------------------------------------------------------------------------
# 위협 카탈로그 / potential_outcome / severity
# ---------------------------------------------------------------------------


class TestThreatCatalog:
    def test_t2_hull_loss(self) -> None:
        assert C.POTENTIAL_OUTCOME_MAP["T2"] == "hull_loss"

    def test_hull_loss_catastrophic(self) -> None:
        assert C.OUTCOME_TO_SEVERITY["hull_loss"] == "Catastrophic"

    def test_t4_hull_loss(self) -> None:
        assert C.POTENTIAL_OUTCOME_MAP["T4"] == "hull_loss"

    def test_t3_attrition(self) -> None:
        assert C.POTENTIAL_OUTCOME_MAP["T3"] == "attrition_kill"
        assert C.OUTCOME_TO_SEVERITY["attrition_kill"] == "Critical"

    def test_t1_mission_abort(self) -> None:
        assert C.POTENTIAL_OUTCOME_MAP["T1"] == "mission_abort"
        assert C.OUTCOME_TO_SEVERITY["mission_abort"] == "Marginal"

    def test_t6_no_potential_outcome(self) -> None:
        # T6 는 threat_event 아님, POTENTIAL_OUTCOME_MAP 에 존재하지 않음.
        assert "T6" not in C.POTENTIAL_OUTCOME_MAP

    def test_severity_order(self) -> None:
        assert C.SEVERITY_ORDER["Catastrophic"] < C.SEVERITY_ORDER["Negligible"]
        assert C.SEVERITY_ORDER["Catastrophic"] == 1
        assert C.SEVERITY_ORDER["Negligible"] == 4

    def test_threat_catalog_has_t1_to_t7(self) -> None:
        for tid in ("T1", "T2", "T3", "T4", "T5", "T6", "T7"):
            assert tid in C.THREAT_CATALOG


# ---------------------------------------------------------------------------
# 04 Step A/C — phase multiplier / channel weights
# ---------------------------------------------------------------------------


class TestPhaseAndChannelWeights:
    def test_loiter_t3_multiplier(self) -> None:
        assert C.PHASE_THREAT_MULTIPLIER.get(("LOITER_ROI", "T3"), 1.0) == 1.1

    def test_land_t4_multiplier(self) -> None:
        assert C.PHASE_THREAT_MULTIPLIER.get(("LAND", "T4"), 1.0) == 1.2

    def test_land_t7_multiplier(self) -> None:
        assert C.PHASE_THREAT_MULTIPLIER.get(("LAND", "T7"), 1.0) == 1.2

    def test_rtl_t3_multiplier(self) -> None:
        assert C.PHASE_THREAT_MULTIPLIER.get(("RTL", "T3"), 1.0) == 0.9

    def test_unknown_phase_threat_defaults_to_1(self) -> None:
        # T1/T2/T5 는 전 국면 1.0 (표에 없음, get 기본값 사용).
        assert C.PHASE_THREAT_MULTIPLIER.get(("WAYPOINT", "T1"), 1.0) == 1.0
        assert C.PHASE_THREAT_MULTIPLIER.get(("LOITER_ROI", "T2"), 1.0) == 1.0

    def test_channel_weights(self) -> None:
        assert C.CHANNEL_WEIGHTS["proximity_object"] == 0.40
        assert C.CHANNEL_WEIGHTS["link_status"] == 0.15
        assert C.CHANNEL_WEIGHTS["acoustic_event"] == 0.30

    def test_default_channel_weight(self) -> None:
        assert C.DEFAULT_CHANNEL_WEIGHT == 0.20

    def test_confidence_by_match_count(self) -> None:
        assert C.CONFIDENCE_BY_MATCH_COUNT[1] == 0.70
        assert C.CONFIDENCE_BY_MATCH_COUNT[2] == 0.90
        assert C.CONFIDENCE_BY_MATCH_COUNT[3] == 0.95

    def test_w_min_q_min(self) -> None:
        assert C.W_MIN == 0.20
        assert C.Q_MIN == 0.65
        assert C.CROSS_CHECK_TOLERANCE == 0.15


# ---------------------------------------------------------------------------
# 05 — base_rate / mission_context / RAC_ORDER
# ---------------------------------------------------------------------------


class TestRiskAssessmentConstants:
    def test_mission_contexts_are_four(self) -> None:
        assert C.MISSION_CONTEXTS == ("정찰", "타격", "호송", "수송")
        assert len(C.MISSION_CONTEXTS) == 4

    def test_base_rate_physical_t3(self) -> None:
        assert C.BASE_RATE_PHYSICAL[("T3", "정찰")] == 0.15
        assert C.BASE_RATE_PHYSICAL[("T3", "타격")] == 0.35
        assert C.BASE_RATE_PHYSICAL[("T3", "호송")] == 0.20
        assert C.BASE_RATE_PHYSICAL[("T3", "수송")] == 0.10

    def test_base_rate_physical_t4(self) -> None:
        assert C.BASE_RATE_PHYSICAL[("T4", "정찰")] == 0.08
        assert C.BASE_RATE_PHYSICAL[("T4", "타격")] == 0.20
        assert C.BASE_RATE_PHYSICAL[("T4", "호송")] == 0.12
        assert C.BASE_RATE_PHYSICAL[("T4", "수송")] == 0.05

    def test_base_rate_remote_nav(self) -> None:
        assert C.BASE_RATE_REMOTE_NAV["T1"] == 0.12
        assert C.BASE_RATE_REMOTE_NAV["T2"] == 0.10
        assert C.BASE_RATE_REMOTE_NAV["T5"] == 0.08
        assert C.BASE_RATE_REMOTE_NAV["T7"] == 0.10

    def test_l_value_class_thresholds(self) -> None:
        # (threshold, class) tuples in descending threshold order.
        assert C.L_VALUE_TO_CLASS_THRESHOLDS == (
            (0.50, "A"),
            (0.30, "B"),
            (0.15, "C"),
            (0.05, "D"),
            (0.01, "E"),
        )

    def test_rac_order(self) -> None:
        assert C.RAC_ORDER["High"] == 1
        assert C.RAC_ORDER["Low"] == 4
        assert C.RAC_ORDER["High"] < C.RAC_ORDER["Serious"] < C.RAC_ORDER["Medium"] < C.RAC_ORDER["Low"]

    def test_continuous_s_base_score(self) -> None:
        assert C.CONTINUOUS_S_BASE_SCORE["Catastrophic"] == 0.90
        assert C.CONTINUOUS_S_BASE_SCORE["Critical"] == 0.60
        assert C.CONTINUOUS_S_BASE_SCORE["Marginal"] == 0.30
        assert C.CONTINUOUS_S_BASE_SCORE["Negligible"] == 0.10

    def test_ambient_exposure_threshold(self) -> None:
        assert C.AMBIENT_EXPOSURE_THRESHOLD == 0.7


# ---------------------------------------------------------------------------
# 신호 매핑표
# ---------------------------------------------------------------------------


class TestSignalToThreat:
    def test_at_least_nine_entries(self) -> None:
        # 04 Step B 표: 9 mapping rows.
        assert len(C.SIGNAL_TO_THREAT) == 9

    def test_proximity_object_weapon_shape_t3(self) -> None:
        matches = [e for e in C.SIGNAL_TO_THREAT if e["channel"] == "proximity_object" and "weapon_shape" in e["condition"]]
        assert len(matches) == 1
        assert matches[0]["threat"] == "T3"

    def test_position_consistency_t1(self) -> None:
        matches = [e for e in C.SIGNAL_TO_THREAT if e["channel"] == "position_consistency"]
        assert all(e["threat"] == "T1" for e in matches)

    def test_t4_multi_channel_three_conditions(self) -> None:
        assert len(C.T4_MULTI_CHANNEL_CONDITIONS) == 3
        channels = {e["channel"] for e in C.T4_MULTI_CHANNEL_CONDITIONS}
        assert channels == {"proximity_object", "mission_phase", "link_status"}
