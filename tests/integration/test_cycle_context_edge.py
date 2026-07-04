"""cycle_context 방어 경로 커버리지 (issue #88).

1. terrain_class 방위 필드 부분 null:
   - optimal 있고 lowest 없음 → optimal만 03 오버라이드, lowest는 corridor 값 유지
   - optimal 없고 lowest 있음 → lowest만 03 오버라이드, optimal은 corridor 값 유지
2. obstacle_ttc_s=None 명시적 → CFIT override 미발동, 07 정상 동작
3. cycle_context 키 부재 → NAVIGATION/PHYSICAL에서 target_bearing_deg=None 방어
"""

import json
import pathlib

import pytest

from onboard.run import _compute_terrain_bearings, _extract_terrain_bearings, run_cycle
from onboard.layer_07_planning.run import run as plan_run

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _make_abstraction_with_terrain(optimal, lowest):
    return {
        "schema_version": "real",
        "id": "x",
        "ts": 1,
        "channels": [{
            "channel": "terrain_class",
            "state": "normal",
            "quality": 0.9,
            "payload": {
                "optimal_terrain_bearing_deg": optimal,
                "lowest_exposure_bearing_deg": lowest,
            },
        }],
    }


def _make_response(flight_action, threat_category=None):
    return {
        "primary_threat_event": None,
        "rac": "Low",
        "kill_chain_stage": None,
        "threat_category": threat_category,
        "flight_action": flight_action,
        "comms_level": "L0",
        "payload_action": [],
        "nav_mode": None,
        "special_action": None,
        "secondary_threats": [],
        "ai_reliability": "normal",
    }


# --- 1. 부분 null: _extract_terrain_bearings 단위 ---

def test_extract_terrain_bearings_partial_optimal_only():
    """optimal만 non-null → optimal만 추출, lowest 키 없음 (corridor 보존)."""
    abstraction = _make_abstraction_with_terrain(optimal=111.0, lowest=None)
    result = _extract_terrain_bearings(abstraction)
    assert result == {"optimal_terrain_bearing_deg": 111.0}
    assert "lowest_exposure_bearing_deg" not in result


def test_extract_terrain_bearings_partial_lowest_only():
    """lowest만 non-null → lowest만 추출, optimal 키 없음 (corridor 보존)."""
    abstraction = _make_abstraction_with_terrain(optimal=None, lowest=222.0)
    result = _extract_terrain_bearings(abstraction)
    assert result == {"lowest_exposure_bearing_deg": 222.0}
    assert "optimal_terrain_bearing_deg" not in result


# --- 2. 부분 null: run_cycle 종단 통합 ---

def test_cycle_context_partial_null_optimal_overrides_corridor(monkeypatch):
    """03 terrain_class: optimal=111, lowest=None → cycle_context_07.optimal=111, lowest=corridor."""
    import onboard.run as run_mod

    captured = {}

    original_run_layer = run_mod._run_layer

    def patched_run_layer(num, invoke):
        if num == "03":
            return _make_abstraction_with_terrain(111.0, None)
        if num == "07":
            def capture_invoke(run_fn):
                def wrapped(response, primary_context, ctx):
                    captured["ctx"] = ctx
                    return {
                        "flight_action": "MAINTAIN",
                        "target_bearing_deg": None,
                        "altitude_delta_m": 0,
                        "replan_scope": "NONE",
                        "reroute_anchor": None,
                    }
                return wrapped(run_fn)
            return invoke(lambda resp, pc, ctx: (captured.update({"ctx": ctx}) or {
                "flight_action": "MAINTAIN",
                "target_bearing_deg": None,
                "altitude_delta_m": 0,
                "replan_scope": "NONE",
                "reroute_anchor": None,
            }))
        return original_run_layer(num, invoke)

    monkeypatch.setattr(run_mod, "_run_layer", patched_run_layer)

    mb = _load("mission_brief_t3.json")
    run_cycle(_load("raw_t3.json"), mb)

    corridor = _compute_terrain_bearings(mb)
    assert captured["ctx"]["optimal_terrain_bearing_deg"] == 111.0
    assert captured["ctx"]["lowest_exposure_bearing_deg"] == corridor["lowest_exposure_bearing_deg"]


def test_cycle_context_partial_null_lowest_overrides_corridor(monkeypatch):
    """03 terrain_class: optimal=None, lowest=222 → cycle_context_07.optimal=corridor, lowest=222."""
    import onboard.run as run_mod

    captured = {}
    original_run_layer = run_mod._run_layer

    def patched_run_layer(num, invoke):
        if num == "03":
            return _make_abstraction_with_terrain(None, 222.0)
        if num == "07":
            return invoke(lambda resp, pc, ctx: (captured.update({"ctx": ctx}) or {
                "flight_action": "MAINTAIN",
                "target_bearing_deg": None,
                "altitude_delta_m": 0,
                "replan_scope": "NONE",
                "reroute_anchor": None,
            }))
        return original_run_layer(num, invoke)

    monkeypatch.setattr(run_mod, "_run_layer", patched_run_layer)

    mb = _load("mission_brief_t3.json")
    run_cycle(_load("raw_t3.json"), mb)

    corridor = _compute_terrain_bearings(mb)
    assert captured["ctx"]["optimal_terrain_bearing_deg"] == corridor["optimal_terrain_bearing_deg"]
    assert captured["ctx"]["lowest_exposure_bearing_deg"] == 222.0


# --- 3. obstacle_ttc_s=None 명시적 → CFIT override 미발동 ---

def test_obstacle_ttc_none_no_cfit_override():
    """cycle_context에 obstacle_ttc_s=None 명시 → CFIT override 없이 원래 action 유지."""
    response = _make_response("MAINTAIN", None)
    ctx = {
        "optimal_terrain_bearing_deg": 180.0,
        "lowest_exposure_bearing_deg": 270.0,
        "obstacle_ttc_s": None,
    }
    out = plan_run(response, None, ctx)
    assert out["flight_action"] == "MAINTAIN"
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "NONE"


def test_obstacle_ttc_key_absent_no_cfit_override():
    """cycle_context에 obstacle_ttc_s 키 자체 없음 → CFIT override 없이 원래 action 유지."""
    response = _make_response("MAINTAIN", None)
    ctx = {
        "optimal_terrain_bearing_deg": 180.0,
        "lowest_exposure_bearing_deg": 270.0,
    }
    out = plan_run(response, None, ctx)
    assert out["flight_action"] == "MAINTAIN"
    assert out["altitude_delta_m"] == 0
    assert out["replan_scope"] == "NONE"


# --- 4. cycle_context 키 부재 → 07 target_bearing_deg=None 방어 ---

def test_07_navigation_missing_optimal_bearing_key():
    """NAVIGATION + cycle_context에 optimal_terrain_bearing_deg 키 없음 → target_bearing_deg=None."""
    response = _make_response("REROUTE", "NAVIGATION")
    out = plan_run(response, None, {})
    assert out["target_bearing_deg"] is None
    assert out["replan_scope"] == "FULL"


def test_07_physical_missing_lowest_bearing_key():
    """PHYSICAL + bearing=None + cycle_context에 lowest_exposure_bearing_deg 키 없음 → target_bearing_deg=None."""
    response = _make_response("REROUTE", "PHYSICAL")
    out = plan_run(response, None, {})
    assert out["target_bearing_deg"] is None
    assert out["reroute_anchor"] == "terrain_fallback"
