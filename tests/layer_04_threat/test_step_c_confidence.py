"""Step C (확신도·킬체인 산출) 검증.

matched 포맷:
  [{"threat_event": str,
    "matched_channels": [{"name", "base_weight", "quality", "state"}, ...]}, ...]
"""

from __future__ import annotations

from onboard.layer_04_threat import step_c_confidence


def _mc(name: str, base_weight: float, quality: float, state: str = "anomaly") -> dict:
    return {"name": name, "base_weight": base_weight, "quality": quality, "state": state}


class TestSingleChannel:
    def test_one_channel_q09_loiter_t3(self) -> None:
        # det=0.7. ai=sigmoid(0.40*logit(0.9))≈0.707, |ai-det|≈0.007≤0.15 → ai.
        # (LOITER_ROI, T3) 배수 1.1 → 0.707*1.1 ≈ 0.777
        matched = [
            {
                "threat_event": "T3",
                "matched_channels": [_mc("proximity_object", 0.40, 0.90)],
            }
        ]
        scored = step_c_confidence.run(matched, "LOITER_ROI")
        assert len(scored) == 1
        t3 = scored[0]
        assert t3["match_count"] == 1
        assert t3["kill_chain_stage"] == "중기"
        assert t3["confidence_source"] == "ai"
        assert t3["confidence"] == 0.777


class TestTwoChannels:
    def test_two_channels_q09_q08(self) -> None:
        # det=0.9. ai=sigmoid(0.40*logit(0.9)+0.30*logit(0.8))≈0.785.
        # |0.785-0.9|=0.115≤0.15 → ai. WAYPOINT → 배수 없음.
        matched = [
            {
                "threat_event": "T3",
                "matched_channels": [
                    _mc("proximity_object", 0.40, 0.90),
                    _mc("acoustic_event", 0.30, 0.80),
                ],
            }
        ]
        scored = step_c_confidence.run(matched, "WAYPOINT")
        t3 = scored[0]
        assert t3["match_count"] == 2
        assert t3["kill_chain_stage"] == "후기"  # avg_weight=0.35, count>=2
        assert t3["confidence_source"] == "ai"
        assert t3["confidence"] == 0.785


class TestQualityExclusion:
    def test_low_quality_channel_excluded(self) -> None:
        # acoustic_event quality 0.5 < Q_min(0.65) → 이 채널만 제외, match_count=1
        matched = [
            {
                "threat_event": "T3",
                "matched_channels": [
                    _mc("proximity_object", 0.40, 0.90),
                    _mc("acoustic_event", 0.30, 0.50),
                ],
            }
        ]
        scored = step_c_confidence.run(matched, "WAYPOINT")
        assert len(scored) == 1
        assert scored[0]["match_count"] == 1


class TestWeightExclusion:
    def test_only_low_weight_channel_drops_threat(self) -> None:
        # link_status base_weight 0.15 < W_min(0.20) → 유일 채널 제외 → threat 탈락
        matched = [
            {
                "threat_event": "T4",
                "matched_channels": [_mc("link_status", 0.15, 0.70)],
            }
        ]
        scored = step_c_confidence.run(matched, "WAYPOINT")
        assert scored == []


class TestEmpty:
    def test_empty_matched(self) -> None:
        assert step_c_confidence.run([], "WAYPOINT") == []
