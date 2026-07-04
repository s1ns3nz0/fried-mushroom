"""layer_05_risk.run 종단 골든 테스트.

두 축으로 검증한다:
1. `D-1. Risk Assessment Spec` §9~12 의 손계산 시나리오(정확한 숫자가 문서에 박혀 있음)를
   인라인 입력으로 그대로 재현 — 회귀 시 스펙 회귀.
2. `examples/mission_brief_*.json` 실제 브리핑 파일 + 합성 04 candidate 로,
   해당 입력에 대해 손계산한 기대값 — 실제 mission_brief 스키마(drone_profile 중첩) 대응 확인.
"""

import json
from pathlib import Path

import pytest

from onboard.layer_05_risk.run import run

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _threat(candidates: list, background: float = 0.4) -> dict:
    primary = candidates[0] if candidates else None
    return {
        "declared_phase": "LOITER_ROI",
        "mission_phase_confidence": 0.9,
        "candidates": candidates,
        "primary": primary,
        "background_exposure_score": background,
    }


def _cand(threat_event, confidence, kill_chain_stage, potential_outcome, match_count=2):
    return {
        "threat_event": threat_event,
        "match_count": match_count,
        "confidence": confidence,
        "confidence_source": "ai",
        "kill_chain_stage": kill_chain_stage,
        "potential_outcome": potential_outcome,
    }


# ---------------------------------------------------------------------------
# 1. D-1 손계산 시나리오 (정확한 숫자 재현)
# ---------------------------------------------------------------------------


class TestD1HandCalcScenarios:
    def test_scenario1_t3_solo(self):
        # D-1 §9: 정찰, posture 평시(4/4/5), 예비기체 없음, battery 65, link 0.90.
        brief = {
            "sortie_id": "S1",
            "mission_context": "정찰",
            "posture": {"watchcon": 4, "defcon": 4, "infocon": 5},
            "drone_profile": {"spare_asset_available": False, "battery_pct": 65},
            "corridor": {},
            "weights": {},
        }
        threat = _threat([_cand("T3", 0.917, "후기", "attrition_kill")])
        out = run(threat, brief, link_quality=0.90)

        assert out["ambient_rac"] is None
        c = out["candidates"][0]
        assert c["rac"] == "Serious"
        assert c["l_class_final"] == "C"
        assert c["severity_label_final"] == "Catastrophic"
        assert c["priority_rank"] == 1
        cra = c["compound_risk_assessment"]
        assert cra["continuous_L"] == pytest.approx(0.1965, abs=1e-4)
        assert cra["continuous_S"] == pytest.approx(0.95, abs=1e-4)
        assert cra["rac_ai_equivalent"] == "Serious"
        assert cra["ai_reliability"] == "normal"
        assert c["compound_urgency_score"] == pytest.approx(0.2867, abs=1e-4)

    def test_scenario2_t4_solo_posture_elevated(self):
        # D-1 §10: 타격, posture 격상(wc2/dc3), 예비기체 있음, battery 25, link 0.70.
        brief = {
            "sortie_id": "S2",
            "mission_context": "타격",
            "posture": {"watchcon": 2, "defcon": 3, "infocon": 5},
            "drone_profile": {"spare_asset_available": True, "battery_pct": 25},
            "corridor": {},
            "weights": {},
        }
        threat = _threat([_cand("T4", 0.758, "중기", "hull_loss")])
        out = run(threat, brief, link_quality=0.70)

        c = out["candidates"][0]
        assert c["rac"] == "High"
        assert c["l_class_final"] == "A"
        assert c["severity_label_final"] == "Catastrophic"
        cra = c["compound_risk_assessment"]
        assert cra["continuous_L"] == pytest.approx(0.2166, abs=1e-4)
        assert cra["continuous_S"] == pytest.approx(0.95, abs=1e-4)
        assert cra["rac_ai_equivalent"] == "High"
        assert cra["ai_reliability"] == "normal"
        assert c["compound_urgency_score"] == pytest.approx(0.2057, abs=1e-4)

    def test_scenario3_t3_and_t4_sorting(self):
        # D-1 §11: 정찰, 평시, 예비기체 없음, battery 65, link 0.70. T3+T4 동시.
        brief = {
            "sortie_id": "S3",
            "mission_context": "정찰",
            "posture": {"watchcon": 4, "defcon": 4, "infocon": 5},
            "drone_profile": {"spare_asset_available": False, "battery_pct": 65},
            "corridor": {},
            "weights": {},
        }
        threat = _threat(
            [
                _cand("T3", 0.917, "후기", "attrition_kill"),
                _cand("T4", 0.888, "중기", "hull_loss"),
            ]
        )
        out = run(threat, brief, link_quality=0.70)

        events = [c["threat_event"] for c in out["candidates"]]
        assert events == ["T3", "T4"]  # urgency 내림차순
        t3, t4 = out["candidates"]
        assert t3["priority_rank"] == 1 and t4["priority_rank"] == 2
        assert t3["rac"] == "Serious" and t4["rac"] == "Serious"
        assert t3["compound_urgency_score"] == pytest.approx(0.2867, abs=1e-4)
        assert t4["compound_urgency_score"] == pytest.approx(0.0964, abs=1e-4)
        assert t4["l_class_final"] == "D"


# ---------------------------------------------------------------------------
# 2. 실제 examples/ 브리핑 파일 기반 (해당 입력에 대한 손계산)
# ---------------------------------------------------------------------------


class TestExampleBriefGolden:
    def test_t3_recon_brief(self):
        # mission_brief_t3: 정찰, posture 3/3/4, 예비기체 있음, battery 65.
        brief = _load("mission_brief_t3.json")
        threat = _threat([_cand("T3", 0.917, "후기", "attrition_kill")])
        c = run(threat, brief, link_quality=0.90)["candidates"][0]
        # base 0.15→C, steps(min(3,3)=3)→1 → B. Critical(예비기체 있음).
        assert c["l_class_final"] == "B"
        assert c["severity_label_final"] == "Critical"
        assert c["rac"] == "Serious"
        assert c["compound_risk_assessment"]["continuous_L"] == pytest.approx(0.1965, abs=1e-4)
        assert c["compound_risk_assessment"]["continuous_S"] == pytest.approx(0.60, abs=1e-4)
        assert c["compound_urgency_score"] == pytest.approx(0.2179, abs=1e-4)
        assert c["priority_rank"] == 1

    def test_t4_convoy_brief(self):
        # mission_brief_t4: 호송, posture 3/3/3, 예비기체 없음, battery 45.
        brief = _load("mission_brief_t4.json")
        threat = _threat([_cand("T4", 0.758, "중기", "hull_loss")])
        c = run(threat, brief, link_quality=0.70)["candidates"][0]
        # base(T4,호송)=0.12→D, steps 1 → C. hull_loss Catastrophic, 예비기체 없음(무효).
        assert c["l_class_final"] == "C"
        assert c["severity_label_final"] == "Catastrophic"
        assert c["rac"] == "Serious"
        assert c["compound_risk_assessment"]["continuous_L"] == pytest.approx(0.1299, abs=1e-4)
        assert c["compound_risk_assessment"]["continuous_S"] == pytest.approx(0.95, abs=1e-4)
        assert c["compound_urgency_score"] == pytest.approx(0.1234, abs=1e-4)

    def test_t7_supply_brief(self):
        # mission_brief_t7: 수송, posture 4/4/4, 예비기체 있음, battery 55.
        brief = _load("mission_brief_t7.json")
        threat = _threat([_cand("T7", 0.70, "중기", "attrition_kill", match_count=1)])
        c = run(threat, brief, link_quality=0.90)["candidates"][0]
        # base(T7)=0.10→D, steps 0 → D. attrition_kill Critical, 예비기체 있음.
        assert c["l_class_final"] == "D"
        assert c["severity_label_final"] == "Critical"
        assert c["rac"] == "Medium"
        assert c["compound_risk_assessment"]["continuous_L"] == pytest.approx(0.10, abs=1e-4)
        assert c["compound_urgency_score"] == pytest.approx(0.06, abs=1e-4)

    def test_strike_brief_posture_elevated(self):
        # mission_brief_strike: 타격, posture 격상(2/2/3), 예비기체 있음.
        brief = _load("mission_brief_strike.json")
        threat = _threat([_cand("T3", 0.917, "후기", "attrition_kill")])
        c = run(threat, brief, link_quality=0.90)["candidates"][0]
        # base(T3,타격)=0.35→B, steps(min(2,2)=2)→2 → A. Critical.
        assert c["l_class_final"] == "A"
        assert c["severity_label_final"] == "Critical"
        assert c["rac"] == "High"
        assert c["compound_risk_assessment"]["continuous_L"] == pytest.approx(0.4585, abs=1e-4)
        assert c["compound_urgency_score"] == pytest.approx(0.3751, abs=1e-4)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
