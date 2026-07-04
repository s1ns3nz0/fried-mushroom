"""Step B (신호→위협 매핑) 검증."""

from __future__ import annotations

from onboard.layer_04_threat import step_b_mapping
from onboard.layer_04_threat.step_b_mapping import _t7_obstacle
from onboard.shared.schemas import AbstractionOutput


def _threats(matched: list[dict]) -> set[str]:
    return {m["threat_event"] for m in matched}


def _by_threat(matched: list[dict], threat: str) -> dict:
    return next(m for m in matched if m["threat_event"] == threat)


class TestT3:
    def test_t3_matched_not_t5(self, abstraction_t3) -> None:
        matched, _ = step_b_mapping.run(abstraction_t3)
        threats = _threats(matched)
        assert "T3" in threats
        assert "T5" not in threats

    def test_t3_channels(self, abstraction_t3) -> None:
        matched, _ = step_b_mapping.run(abstraction_t3)
        names = {c["name"] for c in _by_threat(matched, "T3")["matched_channels"]}
        assert names == {"proximity_object", "acoustic_event"}

    def test_t3_exposure_passthrough(self, abstraction_t3) -> None:
        _, exposure = step_b_mapping.run(abstraction_t3)
        assert exposure == 0.8  # 실측 03 terrain_class(open_field) (Refs #41)


class TestT4:
    def test_t4_multi_channel(self, abstraction_t4) -> None:
        matched, _ = step_b_mapping.run(abstraction_t4)
        assert "T4" in _threats(matched)
        names = {c["name"] for c in _by_threat(matched, "T4")["matched_channels"]}
        assert names == {"proximity_object", "mission_phase", "link_status"}

    def test_t4_t2_companion(self) -> None:
        # link_integrity 손상(seq_gap>0) → T2 동반 매칭 규칙 단위검증.
        # raw_t4 정본은 link_integrity 정상이라, 규칙 자체는 합성 채널로 검증한다
        # (fixture 정본화 후 T2 동반 경로 커버리지 유지, Refs #41).
        abstraction: AbstractionOutput = {
            "schema_version": "1.0",
            "id": "t2-companion",
            "ts": 0,
            "channels": [
                {
                    "channel": "link_integrity",
                    "state": "anomaly",
                    "quality": 0.9,
                    "quality_delta": 0.0,
                    "payload": {"checksum_fail_rate": 0.0, "seq_gap_count": 3},
                }
            ],
        }
        matched, _ = step_b_mapping.run(abstraction)
        assert "T2" in _threats(matched)


class TestT7:
    def test_t7_matched(self, abstraction_t7) -> None:
        matched, _ = step_b_mapping.run(abstraction_t7)
        assert "T7" in _threats(matched)
        names = {c["name"] for c in _by_threat(matched, "T7")["matched_channels"]}
        assert names == {"obstacle_proximity"}


class TestT7ObstacleGuard:
    """_t7_obstacle: 충돌예상시간(distance/closure)<임계 → T7. 물리적으로 무의미한
    음수 거리는 음수 TTC 를 만들어 오탐(가짜 CFIT 회피)을 유발하므로 배제한다."""

    def _ch(self, distance_m, closure_rate_mps):
        return {"payload": {"distance_m": distance_m, "closure_rate_mps": closure_rate_mps}}

    def test_imminent_collision_matches(self) -> None:
        assert _t7_obstacle(self._ch(24.0, 12.0)) is True  # TTC 2.0s < 3.0

    def test_far_does_not_match(self) -> None:
        assert _t7_obstacle(self._ch(100.0, 1.0)) is False  # TTC 100s

    def test_non_positive_closure_does_not_match(self) -> None:
        assert _t7_obstacle(self._ch(24.0, 0.0)) is False

    def test_negative_distance_does_not_match(self) -> None:
        # 음수 거리 → 음수 TTC(-2.5) < 3.0 로 잘못 매칭되면 안 됨.
        assert _t7_obstacle(self._ch(-5.0, 2.0)) is False


class TestNormal:
    def test_normal_no_match(self, abstraction_normal) -> None:
        matched, exposure = step_b_mapping.run(abstraction_normal)
        assert matched == []
        assert exposure == 0.8  # 실측 03 terrain_class(open_field) (Refs #41)
