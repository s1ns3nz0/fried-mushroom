"""Step B (신호→위협 매핑) 검증."""

from __future__ import annotations

from onboard.layer_04_threat import step_b_mapping


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
        assert exposure == 0.4


class TestT4:
    def test_t4_multi_channel(self, abstraction_t4) -> None:
        matched, _ = step_b_mapping.run(abstraction_t4)
        assert "T4" in _threats(matched)
        names = {c["name"] for c in _by_threat(matched, "T4")["matched_channels"]}
        assert names == {"proximity_object", "mission_phase", "link_status"}

    def test_t4_t2_companion(self, abstraction_t4) -> None:
        # link_integrity anomaly → T2 동반 매칭
        matched, _ = step_b_mapping.run(abstraction_t4)
        assert "T2" in _threats(matched)


class TestT7:
    def test_t7_matched(self, abstraction_t7) -> None:
        matched, _ = step_b_mapping.run(abstraction_t7)
        assert "T7" in _threats(matched)
        names = {c["name"] for c in _by_threat(matched, "T7")["matched_channels"]}
        assert names == {"obstacle_proximity"}


class TestNormal:
    def test_normal_no_match(self, abstraction_normal) -> None:
        matched, exposure = step_b_mapping.run(abstraction_normal)
        assert matched == []
        assert exposure == 0.2
