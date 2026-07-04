"""stub abstraction(mission_phase 채널 없음) degrade 처리.

orchestrator(src/onboard/run.py)가 layer 03 미구현 시 넘기는
stub {"channels": []} 에서 예외 없이 unknown phase 로 격하되는지 검증한다.
_STUB_OUTPUT["04"] 어휘(declared_phase="unknown", confidence 0.0)와 정렬.
"""

from __future__ import annotations

from onboard.layer_04_threat import run, step_a_phase


class TestStepAMissingMissionPhase:
    def test_returns_unknown_when_channel_absent(self, abstraction_stub) -> None:
        assert step_a_phase.run(abstraction_stub) == ("unknown", 0.0)

    def test_returns_unknown_when_payload_keys_missing(self) -> None:
        # mission_phase 채널은 있으나 declared/mission_phase_confidence 키가 없음
        abstraction = {
            "schema_version": "1.0",
            "id": "x",
            "ts": 0,
            "channels": [
                {
                    "channel": "mission_phase",
                    "state": "normal",
                    "quality": 0.9,
                    "quality_delta": 0.0,
                    "payload": {},
                }
            ],
        }
        assert step_a_phase.run(abstraction) == ("unknown", 0.0)


class TestRunStubDegrade:
    def test_run_degrades_without_exception(self, abstraction_stub) -> None:
        out = run.run(abstraction_stub, {"optimal_terrain_bearing_deg": 0.0})
        assert out["declared_phase"] == "unknown"
        assert out["mission_phase_confidence"] == 0.0
        assert out["candidates"] == []
        assert out["primary"] is None
        assert out["background_exposure_score"] == 0.0
