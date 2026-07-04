"""05 run() 다중후보 우선순위 정렬 타이브레이크 커버리지 (issue #53, Task 2).

정렬 키 (src/onboard/layer_05_risk/run.py:60-66):
    (-compound_urgency_score, severity_num_final, +?)  실제로는
    key = (-urgency, severity_num_final, -match_count)
즉 3단계:
  1) compound_urgency_score 내림차순  (가장 급한 위협 먼저)
  2) 동률이면 severity_num_final 오름차순 (num 낮을수록 더 심각 → 먼저)
  3) 그래도 동률이면 match_count 내림차순 (증거 많은 쪽 먼저)

레벨 1(서로 다른 urgency) 은 test_run_golden.py::test_scenario3_t3_and_t4_sorting 이 이미 커버
(T3 urgency 0.2867 > T4 0.0964). 여기서는 **레벨 2·3** 을 합성 후보로 잠근다 — 동률 urgency 를
정확히 만들어야 타이브레이크가 실제로 발동하기 때문에, 각 후보의 값을 손계산으로 유도한다.

모든 후보는 실제 run() 을 통과시킨다 (합성 dict → 실 계산 경로). posture 는 평시(4/4/5) 로
두어 shift_steps=0 (l_class/rac 결정론에만 영향, urgency 는 continuous_l 이 base 를 직접 쓰므로
posture 무관).
"""

from __future__ import annotations

import pytest

from onboard.layer_05_risk.run import run

# 배터리 충분(≥30)·예비기체 있음·링크 양호(≥0.5) → margin_penalty=0 (continuous_S 순수 base_score).
_BRIEF = {
    "sortie_id": "S-sort",
    "mission_context": "정찰",
    "posture": {"watchcon": 4, "defcon": 4, "infocon": 5},
    "drone_profile": {"spare_asset_available": True, "battery_pct": 65},
    "corridor": {},
    "weights": {},
}
_LINK = 0.90


def _cand(threat_event, confidence, match_count, kill_chain_stage="중기"):
    """합성 04 후보. severity 는 threat_event→POTENTIAL_OUTCOME_MAP 로 05 가 재계산하므로
    potential_outcome 필드값 자체는 정렬에 영향 없음(형식상만 채움)."""
    return {
        "threat_event": threat_event,
        "match_count": match_count,
        "confidence": confidence,
        "confidence_source": "ai",
        "kill_chain_stage": kill_chain_stage,
        "potential_outcome": "n/a",
    }


def _threat(candidates: list) -> dict:
    return {
        "declared_phase": "LOITER_ROI",
        "mission_phase_confidence": 0.9,
        "candidates": candidates,
        "primary": candidates[0] if candidates else None,
        "background_exposure_score": 0.4,
    }


class TestTieBreakSeverity:
    """레벨 2 — urgency 동률, severity_num_final 다름 → 더 심각한(num 작은) 쪽 먼저."""

    def test_equal_urgency_orders_by_severity(self) -> None:
        # 정찰·평시·예비기체 있음·battery 65·link 0.90 → 두 후보 모두 margin_penalty=0.
        #
        # A = T4(hull_loss→Catastrophic, num=1, base_S=0.90), base_rate(T4,정찰)=0.08
        #   conf=0.875 → continuous_L = 0.08 × (0.875/0.7) = 0.08 × 1.25 = 0.10 (cap 0.24 무관)
        #   continuous_S = 0.90 ; urgency = 0.10 × 0.90 = 0.0900
        # B = T3(attrition_kill→Critical, num=2, base_S=0.60), base_rate(T3,정찰)=0.15
        #   conf=0.70  → continuous_L = 0.15 × (0.70/0.7) = 0.15 (cap 0.45 무관)
        #   continuous_S = 0.60 ; urgency = 0.15 × 0.60 = 0.0900
        # → urgency 동률(0.0900). 타이브레이크 severity: A(num1) < B(num2) → A 먼저.
        #
        # 입력 순서는 일부러 덜 심각한 B(T3) 를 먼저 넣어, 정렬이 실제로 재배치하는지 확인.
        threat = _threat([_cand("T3", 0.70, match_count=2), _cand("T4", 0.875, match_count=2)])
        out = run(threat, _BRIEF, link_quality=_LINK)

        cands = out["candidates"]
        urg = [c["compound_urgency_score"] for c in cands]
        assert urg[0] == pytest.approx(0.09, abs=1e-9)
        assert urg[1] == pytest.approx(0.09, abs=1e-9)  # 동률 전제 확인

        events = [c["threat_event"] for c in cands]
        assert events == ["T4", "T3"]  # num1(Catastrophic) → num2(Critical)
        assert cands[0]["severity_label_final"] == "Catastrophic"
        assert cands[1]["severity_label_final"] == "Critical"
        assert [c["priority_rank"] for c in cands] == [1, 2]


class TestTieBreakMatchCount:
    """레벨 3 — urgency 동률 AND severity 동률 → match_count 큰 쪽 먼저."""

    def test_equal_urgency_and_severity_orders_by_match_count(self) -> None:
        # 두 후보 모두 attrition_kill→Critical(num=2, base_S=0.60), 예비기체 있음 → 격상 없음.
        #
        # A = T3, base_rate(T3,정찰)=0.15, conf=0.60 → continuous_L = 0.15 × (0.60/0.7) = 0.09/0.7
        # B = T7, base_rate(T7)=0.10,      conf=0.90 → continuous_L = 0.10 × (0.90/0.7) = 0.09/0.7
        #   → 두 continuous_L 이 정확히 0.09/0.7 로 동일. continuous_S 둘 다 0.60.
        #   urgency = (0.09/0.7) × 0.60 = 0.0771(round4) 동률, severity num 둘 다 2 로 동률.
        # 타이브레이크 match_count: T3(3) > T7(2) → T3 먼저.
        #
        # 입력 순서는 일부러 match_count 작은 T7 을 먼저 넣는다.
        threat = _threat([_cand("T7", 0.90, match_count=2), _cand("T3", 0.60, match_count=3)])
        out = run(threat, _BRIEF, link_quality=_LINK)

        cands = out["candidates"]
        urg = [c["compound_urgency_score"] for c in cands]
        assert urg[0] == pytest.approx(0.0771, abs=1e-9)
        assert urg[1] == pytest.approx(0.0771, abs=1e-9)  # urgency 동률
        sev = [c["severity_label_final"] for c in cands]
        assert sev == ["Critical", "Critical"]  # severity 동률

        events = [c["threat_event"] for c in cands]
        assert events == ["T3", "T7"]  # match_count 3 → 2
        assert cands[0]["match_count"] == 3 and cands[1]["match_count"] == 2
        assert [c["priority_rank"] for c in cands] == [1, 2]


class TestPriorityRankSequential:
    """정렬 후 priority_rank 는 1..N 로 연속 부여되고 리스트도 그 순서로 정렬된다."""

    def test_ranks_are_1_to_n_and_sorted(self) -> None:
        # 서로 다른 urgency 3 후보(레벨 1) 로 rank 연속성과 내림차순 정렬을 동시에 확인.
        # T3 후기(late bonus +0.10) > T4 중기 > T7 중기 순으로 urgency 가 벌어지도록 구성.
        threat = _threat(
            [
                _cand("T7", 0.70, match_count=1, kill_chain_stage="중기"),
                _cand("T3", 0.917, match_count=2, kill_chain_stage="후기"),
                _cand("T4", 0.888, match_count=2, kill_chain_stage="중기"),
            ]
        )
        out = run(threat, _BRIEF, link_quality=_LINK)
        cands = out["candidates"]

        ranks = [c["priority_rank"] for c in cands]
        assert ranks == [1, 2, 3]  # 1..N 연속

        urgencies = [c["compound_urgency_score"] for c in cands]
        assert urgencies == sorted(urgencies, reverse=True)  # 내림차순 정렬 확인
        assert cands[0]["threat_event"] == "T3"  # 후기 보너스로 최상위


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
