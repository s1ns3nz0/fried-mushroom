"""onboard.run run_cycle 오케스트레이터 하니스 통합 테스트 (TDD).

step9.md 의 run_cycle 계약을 따른다. 레이어 03~07 이 아직 미구현이므로
orchestrator 는 passthrough(스키마 적합 canned)로 체이닝하고,
실제 run() 이 생기면 자동 배선(try-import)된다.
구조·배선·인자 스레딩만 검증한다(종단 골든/시맨틱은 실제 레이어 구현 후 step9).
"""

import importlib
import json
import types

import pytest

from onboard import __main__ as cli
from onboard.run import run_cycle
from onboard.shared.schemas import (
    AbstractionOutput,
    FlightPlanOutput,
    ResponseOutput,
    RiskAssessmentOutput,
    ThreatModelingOutput,
)

from tests.helpers.contracts import assert_json_serializable, assert_matches_schema

RESULT_SCHEMA = {
    "abstraction": AbstractionOutput,
    "threat": ThreatModelingOutput,
    "risk": RiskAssessmentOutput,
    "response": ResponseOutput,
    "flight_plan": FlightPlanOutput,
}


def _raw() -> dict:
    return {"ts": 1720000000, "gps": {"fix": "3d"}, "acoustic": {"rms": 0.1}}


def _brief() -> dict:
    return {
        "sortie_id": "TEST-01",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
    }


def _inject(monkeypatch, mapping: dict) -> None:
    """monkeypatch: mapping(모듈명→run 함수) 의 모듈이 run() 을 갖는 것처럼 import 가로채기."""
    real_import = importlib.import_module
    fakes = {}
    for name, fn in mapping.items():
        mod = types.ModuleType(name)
        mod.run = fn
        fakes[name] = mod

    def fake_import(name, *args, **kwargs):
        if name in fakes:
            return fakes[name]
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)


class TestRunCycleShape:
    def test_returns_five_named_layer_outputs(self) -> None:
        result = run_cycle(_raw(), _brief())
        assert set(result) == set(RESULT_SCHEMA)

    def test_passthrough_outputs_match_layer_schema(self) -> None:
        result = run_cycle(_raw(), _brief())
        for key, schema in RESULT_SCHEMA.items():
            assert_matches_schema(result[key], schema)
            assert_json_serializable(result[key])


class TestLayerWiring:
    def test_real_layer03_run_used_with_raw_and_previous_qualities(self, monkeypatch) -> None:
        seen: dict = {}
        sentinel = {"schema_version": "real", "id": "x", "ts": 1, "channels": []}

        def abstraction_run(raw, previous_qualities):
            seen["raw"] = raw
            seen["prev_q"] = previous_qualities
            return sentinel

        _inject(monkeypatch, {"onboard.layer_03_abstraction.run": abstraction_run})
        prev_q = {"gps": 0.9}
        result = run_cycle(_raw(), _brief(), previous_qualities=prev_q)
        assert result["abstraction"] is sentinel
        assert seen["raw"] == _raw()
        assert seen["prev_q"] == prev_q

    def test_mission_brief_passed_to_layer06(self, monkeypatch) -> None:
        seen: dict = {}

        def response_run(risk, mission_brief):
            seen["brief"] = mission_brief
            return _canned_response()

        _inject(monkeypatch, {"onboard.layer_06_response.run": response_run})
        run_cycle(_raw(), _brief())
        assert seen["brief"] == _brief()

    def test_cycle_context_defaults_and_reaches_layer04(self, monkeypatch) -> None:
        seen: dict = {}

        def threat_run(abstraction, cycle_context):
            seen["ctx"] = cycle_context
            return _canned_threat(primary=None)

        _inject(monkeypatch, {"onboard.layer_04_threat.run": threat_run})
        run_cycle(_raw(), _brief())
        assert "optimal_terrain_bearing_deg" in seen["ctx"]
        assert "lowest_exposure_bearing_deg" in seen["ctx"]

    def test_link_quality_extracted_from_abstraction_to_layer05(self, monkeypatch) -> None:
        seen: dict = {}

        def abstraction_run(raw, previous_qualities):
            return {
                "schema_version": "s", "id": "i", "ts": 0,
                "channels": [{
                    "channel": "link_status", "state": "anomaly",
                    "quality": 0.7, "quality_delta": 0.0, "payload": {"rssi_dbm": -95},
                }],
            }

        def risk_run(threat, mission_brief, *, link_quality):
            seen["link_q"] = link_quality
            return {"candidates": []}

        _inject(monkeypatch, {
            "onboard.layer_03_abstraction.run": abstraction_run,
            "onboard.layer_05_risk.run": risk_run,
        })
        run_cycle(_raw(), _brief())
        assert seen["link_q"] == 0.7

    def test_primary_context_threaded_to_layer07(self, monkeypatch) -> None:
        seen: dict = {}
        ctx = {"bearing_deg": 35.0, "bearing_source": "acoustic_event"}

        def threat_run(abstraction, cycle_context):
            return _canned_threat(primary={"threat_event": "T3", "context": ctx})

        def plan_run(response, primary_context, cycle_context):
            seen["primary_context"] = primary_context
            return _canned_flight_plan()

        _inject(monkeypatch, {
            "onboard.layer_04_threat.run": threat_run,
            "onboard.layer_07_planning.run": plan_run,
        })
        run_cycle(_raw(), _brief())
        assert seen["primary_context"] == ctx

    def test_primary_context_none_when_no_primary(self, monkeypatch) -> None:
        seen: dict = {}

        def plan_run(response, primary_context, cycle_context):
            seen["primary_context"] = primary_context
            return _canned_flight_plan()

        # 04 는 passthrough(primary=None) → 07 primary_context 는 None
        _inject(monkeypatch, {"onboard.layer_07_planning.run": plan_run})
        run_cycle(_raw(), _brief())
        assert seen["primary_context"] is None


class TestCli:
    def test_main_prints_result_json_with_five_keys(self, tmp_path, capsys) -> None:
        raw_p = tmp_path / "raw.json"
        brief_p = tmp_path / "brief.json"
        raw_p.write_text(json.dumps(_raw()), encoding="utf-8")
        brief_p.write_text(json.dumps(_brief()), encoding="utf-8")

        rc = cli.main([str(raw_p), str(brief_p)])

        assert rc == 0
        printed = json.loads(capsys.readouterr().out)
        assert set(printed) == set(RESULT_SCHEMA)

    def test_main_usage_error_without_args(self, capsys) -> None:
        rc = cli.main([])
        assert rc == 2
        assert "usage" in capsys.readouterr().err


# --- canned 참고 구조 (실제 레이어 미구현 시 passthrough 가 내는 최소 형태) ---


def _canned_threat(primary) -> dict:
    return {
        "declared_phase": "unknown", "mission_phase_confidence": 0.0,
        "candidates": [], "primary": primary, "background_exposure_score": 0.0,
    }


def _canned_response() -> dict:
    return {
        "primary_threat_event": None, "rac": "Low", "kill_chain_stage": None,
        "threat_category": None, "flight_action": "CONTINUE", "comms_level": "NORMAL",
        "payload_action": [], "nav_mode": None, "special_action": None,
        "secondary_threats": [], "ai_reliability": "normal",
    }


def _canned_flight_plan() -> dict:
    return {
        "flight_action": "CONTINUE", "target_bearing_deg": None,
        "altitude_delta_m": 0, "replan_scope": "NONE", "reroute_anchor": None,
    }
