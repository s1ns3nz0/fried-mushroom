"""onboard.run orchestrator 하니스 통합 테스트 (TDD).

레이어 02~07 이 아직 미구현이므로 orchestrator 는 passthrough 로 체이닝하고,
실제 run() 이 생기면 자동 배선(try-import)된다.
"""

import importlib
import json
import pathlib
import types

import pytest

from onboard.run import main, run_pipeline
from onboard.shared.schemas import (
    AbstractionOutput,
    FlightPlanOutput,
    ResponseOutput,
    RiskAssessmentOutput,
    ThreatModelingOutput,
)

from tests.helpers.contracts import assert_json_serializable, assert_matches_schema

LAYER_SCHEMA = {
    "03": AbstractionOutput,
    "04": ThreatModelingOutput,
    "05": RiskAssessmentOutput,
    "06": ResponseOutput,
    "07": FlightPlanOutput,
}

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"

CHAIN = ("02", "03", "04", "05", "06", "07")


def _brief() -> dict:
    return json.loads((EXAMPLES / "mission_brief_t3.json").read_text(encoding="utf-8"))


def _scenario(n_frames: int = 1) -> dict:
    return {
        "mission_brief": _brief(),
        "sensor_frames": [{"frame": i, "raw": {"gps": "ok"}} for i in range(n_frames)],
    }


class TestRunPipeline:
    def test_single_frame_yields_one_cycle_with_all_layers(self) -> None:
        results = run_pipeline(_scenario(1))
        assert len(results) == 1
        assert set(results[0]["layers"]) == set(CHAIN)

    def test_passthrough_outputs_match_layer_schema(self) -> None:
        cycle = run_pipeline(_scenario(1))[0]
        for layer, schema in LAYER_SCHEMA.items():
            assert_matches_schema(cycle["layers"][layer], schema)
            assert_json_serializable(cycle["layers"][layer])

    def test_multi_frame_yields_cycle_per_frame(self) -> None:
        results = run_pipeline(_scenario(3))
        assert [r["cycle"] for r in results] == [0, 1, 2]

    def test_shipped_scenario_t3_runs_and_conforms(self) -> None:
        scenario = json.loads(
            (EXAMPLES / "scenario_t3.json").read_text(encoding="utf-8")
        )
        results = run_pipeline(scenario)
        assert len(results) == 2  # 2 sensor_frames
        for cycle in results:
            for layer, schema in LAYER_SCHEMA.items():
                assert_matches_schema(cycle["layers"][layer], schema)


def _inject_layer(monkeypatch, module_name: str, run_fn) -> None:
    """monkeypatch: 해당 레이어 모듈이 run() 을 갖는 것처럼 import 를 가로챈다."""
    fake = types.ModuleType(module_name)
    fake.run = run_fn
    real_import = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == module_name:
            return fake
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)


class TestLayerWiring:
    def test_real_layer_run_used_when_present(self, monkeypatch) -> None:
        sentinel = {"schema_version": "real", "id": "x", "ts": 1, "channels": []}

        def real_run(input, *, mission_brief, previous_state):
            return sentinel

        _inject_layer(monkeypatch, "onboard.layer_03_abstraction.run", real_run)
        cycle = run_pipeline(_scenario(1))[0]
        assert cycle["layers"]["03"] is sentinel

    def test_previous_state_carries_prior_cycle_outputs(self, monkeypatch) -> None:
        seen: list[dict] = []

        def spy(input, *, mission_brief, previous_state):
            seen.append(previous_state)
            return {"schema_version": "s", "id": "i", "ts": 0, "channels": []}

        _inject_layer(monkeypatch, "onboard.layer_03_abstraction.run", spy)
        results = run_pipeline(_scenario(2))
        assert seen[0] == {}  # cycle 0: 이전 상태 없음
        assert seen[1] == results[0]["layers"]  # cycle 1: cycle 0 출력 전부

    def test_mission_brief_passed_readonly_to_layers(self, monkeypatch) -> None:
        seen: list[dict] = []

        def spy(input, *, mission_brief, previous_state):
            seen.append(mission_brief)
            return {"declared_phase": "x", "mission_phase_confidence": 0.0,
                    "candidates": [], "primary": None, "background_exposure_score": 0.0}

        _inject_layer(monkeypatch, "onboard.layer_04_threat.run", spy)
        run_pipeline(_scenario(1))
        assert seen[0] == _brief()


class TestMainCli:
    def test_main_writes_jsonl_and_prints_final(self, tmp_path, capsys) -> None:
        scn = tmp_path / "scn.json"
        scn.write_text(json.dumps(_scenario(2)), encoding="utf-8")
        log = tmp_path / "out.jsonl"

        rc = main([str(scn), "--log", str(log)])

        assert rc == 0
        lines = log.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2 * len(CHAIN)  # 2 사이클 × 6 레이어
        first = json.loads(lines[0])
        assert first["cycle"] == 0 and first["layer"] == "02"
        assert "replan_scope" in capsys.readouterr().out  # 최종 07 출력
