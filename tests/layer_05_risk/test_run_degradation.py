"""layer_05_risk.run 스키마 적합성 + graceful degradation 테스트.

오케스트레이터가 STUB abstraction 에서 나온 04 출력(candidates=[], primary=None,
declared_phase="unknown") 과 link_quality=None 을 넘겨도 예외 없이 스키마 적합
최소 출력을 내야 한다 (step5 CI 실패 교훈). 출력은 RiskAssessmentOutput 정확 일치
(contracts helper 가 extra 키 reject).
"""

import pytest

from onboard.layer_05_risk.run import run
from onboard.shared.schemas import RiskAssessmentOutput
from tests.helpers.contracts import assert_json_serializable, assert_matches_schema

_BRIEF = {
    "sortie_id": "DEG-01",
    "mission_context": "정찰",
    "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
    "drone_profile": {"spare_asset_available": True, "battery_pct": 65},
    "corridor": {},
    "weights": {},
}


def _cand(threat_event, potential_outcome="attrition_kill"):
    return {
        "threat_event": threat_event,
        "match_count": 2,
        "confidence": 0.90,
        "confidence_source": "deterministic",
        "kill_chain_stage": "후기",
        "potential_outcome": potential_outcome,
    }


class TestGracefulDegradation:
    def test_empty_candidates_stub_shape(self):
        # 오케스트레이터 STUB 04 출력 + link_quality=None → 예외 없이 ambient 하한.
        threat = {
            "declared_phase": "unknown",
            "mission_phase_confidence": 0.0,
            "candidates": [],
            "primary": None,
            "background_exposure_score": 0.0,
        }
        out = run(threat, _BRIEF, link_quality=None)
        assert out["candidates"] == []
        assert out["ambient_rac"] == "Low"
        assert_matches_schema(out, RiskAssessmentOutput)
        assert_json_serializable(out)

    def test_ambient_low_even_when_high_exposure(self):
        # issue #24 Lead 결정: exposure 기반 Medium 승격 폐기 → candidates 비면 항상 Low.
        threat = {
            "declared_phase": "unknown",
            "mission_phase_confidence": 0.0,
            "candidates": [],
            "primary": None,
            "background_exposure_score": 0.8,
        }
        out = run(threat, _BRIEF, link_quality=None)
        assert out["ambient_rac"] == "Low"

    def test_ambient_threshold_boundary(self):
        threat = {"candidates": [], "primary": None, "background_exposure_score": 0.7}
        assert run(threat, _BRIEF, link_quality=None)["ambient_rac"] == "Low"

    def test_missing_background_key_defaults_low(self):
        # background_exposure_score 키 자체가 없어도 예외 없이 Low.
        out = run({"candidates": []}, _BRIEF, link_quality=None)
        assert out["ambient_rac"] == "Low"

    def test_link_quality_none_no_penalty_no_exception(self):
        threat = {
            "candidates": [_cand("T3")],
            "primary": _cand("T3"),
            "background_exposure_score": 0.0,
        }
        out = run(threat, _BRIEF, link_quality=None)
        # link penalty 미적용 → continuous_S 는 base_score 만 (Critical=0.60).
        assert out["candidates"][0]["compound_risk_assessment"]["continuous_S"] == pytest.approx(
            0.60, abs=1e-4
        )

    def test_default_link_quality_arg_is_none(self):
        # 오케스트레이터가 키워드로 넘기지만, 기본값 None 이어야 한다.
        threat = {"candidates": [], "background_exposure_score": 0.0}
        out = run(threat, _BRIEF)
        assert out["ambient_rac"] == "Low"


class TestSchemaConformance:
    def test_populated_output_matches_schema(self):
        threat = {
            "candidates": [_cand("T3"), _cand("T7")],
            "primary": _cand("T3"),
            "background_exposure_score": 0.4,
        }
        out = run(threat, _BRIEF, link_quality=0.9)
        assert_matches_schema(out, RiskAssessmentOutput)
        assert_json_serializable(out)

    def test_original_04_fields_preserved(self):
        # RiskCandidate 는 ThreatCandidate 상속 → 04 필드 보존 필수.
        threat = {
            "candidates": [_cand("T3")],
            "primary": _cand("T3"),
            "background_exposure_score": 0.4,
        }
        c = run(threat, _BRIEF, link_quality=0.9)["candidates"][0]
        for key in ("threat_event", "match_count", "confidence", "confidence_source",
                    "kill_chain_stage", "potential_outcome"):
            assert key in c

    def test_context_field_passthrough(self):
        # NotRequired context 가 있으면 그대로 통과, extra 키로 취급되지 않음.
        cand = _cand("T3")
        cand["context"] = {"bearing_deg": 35.0, "bearing_source": "acoustic_event", "class": "x"}
        threat = {"candidates": [cand], "primary": cand, "background_exposure_score": 0.4}
        out = run(threat, _BRIEF, link_quality=0.9)
        assert out["candidates"][0]["context"]["bearing_deg"] == 35.0
        assert_matches_schema(out, RiskAssessmentOutput)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
