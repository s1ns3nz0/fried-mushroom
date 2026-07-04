"""SCC-1 행위 불변식: AI 강화판은 결정론 RAC 를 절대 바꾸지 않는다.

test_matrix_immutable 은 RAC_MATRIX '객체'가 mutation 불가임을 본다.
이 파일은 한 단계 더: AI 트랙 입력(confidence, battery_pct, link_quality)을
극단으로 흔들어도 각 후보의 결정론 산출(rac / l_class_final / severity_label_final)이
불변임을 고정한다 (ADR-003 / MIL-STD-882E SCC-1). 동시에 AI 병렬지표
(continuous_L/S, compound_urgency_score)는 실제로 변함을 확인해 비자명성을 보장한다.
"""

import pytest

from onboard.layer_05_risk.run import run


def _cand(threat_event, confidence, kill_chain_stage, match_count=2):
    return {
        "threat_event": threat_event,
        "match_count": match_count,
        "confidence": confidence,
        "confidence_source": "ai",
        "kill_chain_stage": kill_chain_stage,
        "potential_outcome": "attrition_kill",
    }


def _threat(candidates):
    return {
        "declared_phase": "LOITER_ROI",
        "mission_phase_confidence": 0.9,
        "candidates": candidates,
        "primary": candidates[0] if candidates else None,
        "background_exposure_score": 0.4,
    }


def _brief(*, battery_pct, spare=False):
    # mission_context / posture / spare 는 결정론 RAC 입력 → 전 케이스에서 고정한다.
    return {
        "sortie_id": "SCC1",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 3},
        "drone_profile": {"spare_asset_available": spare, "battery_pct": battery_pct},
        "corridor": {},
        "weights": {},
    }


def _det_signature(out):
    """후보별 결정론 산출 (threat_event 키 → 순서 무관)."""
    return {
        c["threat_event"]: (c["rac"], c["l_class_final"], c["severity_label_final"])
        for c in out["candidates"]
    }


def _ai_signature(out):
    return {
        c["threat_event"]: (
            c["compound_risk_assessment"]["continuous_L"],
            c["compound_risk_assessment"]["continuous_S"],
            c["compound_urgency_score"],
        )
        for c in out["candidates"]
    }


class TestAiDoesNotChangeDeterministicRac:
    def test_confidence_battery_link_do_not_change_rac(self):
        # AI 트랙 입력만 다른 두 시나리오. 결정론 입력(threat_event/context/posture/spare) 동일.
        base = run(
            _threat([_cand("T3", 0.917, "후기"), _cand("T4", 0.70, "중기")]),
            _brief(battery_pct=65),
            link_quality=0.90,
        )
        # confidence 극단, battery 최저, link 최저 → continuous_L/S 크게 변함.
        swung = run(
            _threat([_cand("T3", 0.999, "후기"), _cand("T4", 0.50, "중기")]),
            _brief(battery_pct=10),
            link_quality=0.10,
        )

        assert _det_signature(swung) == _det_signature(base)  # 결정론 RAC 불변 (SCC-1)
        assert _ai_signature(swung) != _ai_signature(base)  # AI 트랙은 실제로 반응함 (비자명)

    def test_none_battery_and_link_still_invariant(self):
        cands = [_cand("T3", 0.917, "후기"), _cand("T4", 0.70, "중기")]
        base = run(_threat(cands), _brief(battery_pct=65), link_quality=0.90)
        # battery/link None 경로(스텁/센서 결측)도 결정론 RAC 를 바꾸지 않는다.
        nulled = run(_threat(cands), _brief(battery_pct=None), link_quality=None)
        assert _det_signature(nulled) == _det_signature(base)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
