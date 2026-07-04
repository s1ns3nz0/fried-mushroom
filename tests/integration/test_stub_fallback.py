"""오케스트레이터 stub-fallback 복원력 계약.

run.py 는 레이어 모듈이 없거나(ModuleNotFoundError) run() 이 호출가능하지 않으면
크래시 대신 스키마 적합 canned _STUB_OUTPUT 으로 대체해 사이클을 완주한다
(자동 배선 계약, run.py:_run_layer/_import_layer_run). 모든 레이어가 구현된
현재 이 경로는 실측 테스트가 없어(coverage gap) 여기서 강제 재현한다.
"""

import importlib
import types

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import _STUB_OUTPUT, run_cycle

_KEYS = {"abstraction", "threat", "risk", "response", "flight_plan", "flight_plan_state", "endurance", "corridor", "sensor_health"}


def _raw() -> dict:
    return build_normal_envelope("STUB", 0, 0)


def _brief() -> dict:
    return {
        "sortie_id": "STUB-01",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
    }


def test_missing_layer_module_falls_back_to_stub(monkeypatch) -> None:
    real = importlib.import_module

    def fake(name, *a, **k):
        if name == "onboard.layer_05_risk.run":
            raise ModuleNotFoundError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", fake)
    out = run_cycle(_raw(), _brief())

    assert set(out) == _KEYS  # 사이클 완주 (크래시 없음)
    assert out["risk"] == _STUB_OUTPUT["05"]()  # 05 부재 → canned stub


def test_non_callable_run_falls_back_to_stub(monkeypatch) -> None:
    real = importlib.import_module

    def fake(name, *a, **k):
        if name == "onboard.layer_06_response.run":
            mod = types.ModuleType(name)
            mod.run = "not-callable"  # run 속성이 있으나 호출 불가
            return mod
        return real(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", fake)
    out = run_cycle(_raw(), _brief())

    assert set(out) == _KEYS
    assert out["response"] == _STUB_OUTPUT["06"]()  # 06 run 비호출가능 → canned stub


def test_layer07_fallback_stub_includes_route_field() -> None:
    """07 fallback stub 이 FlightPlanOutput required 필드 route 를 포함해야 한다."""
    stub = _STUB_OUTPUT["07"]()
    assert "route" in stub, "07 fallback stub 에 route 필드 누락 — 스키마 위반"
    assert stub["route"] == [], f"route 는 빈 리스트여야 함, 실제: {stub['route']}"


def test_layer07_fallback_stub_includes_speed_mode_field() -> None:
    """07 fallback stub 이 FlightPlanOutput required 필드 speed_mode 를 포함해야 한다."""
    stub = _STUB_OUTPUT["07"]()
    assert "speed_mode" in stub, "07 fallback stub 에 speed_mode 필드 누락 — 스키마 위반"
    assert stub["speed_mode"] == "NORMAL", f"MAINTAIN 기준 NORMAL 이어야 함, 실제: {stub['speed_mode']}"


def test_layer07_fallback_stub_reroute_anchor_is_mission_corridor_resume() -> None:
    """07 fallback stub 은 MAINTAIN 모양이므로 reroute_anchor=mission_corridor_resume 이어야 한다(신규 확정)."""
    stub = _STUB_OUTPUT["07"]()
    assert stub["reroute_anchor"] == "mission_corridor_resume"


def test_missing_layer07_module_falls_back_with_flight_plan_state(monkeypatch) -> None:
    """07 자체가 fallback 되어도 flight_plan_state 는 항상 존재해야 한다(디바운스 상태 채널, 신규)."""
    real = importlib.import_module

    def fake(name, *a, **k):
        if name == "onboard.layer_07_planning.run":
            raise ModuleNotFoundError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", fake)
    out = run_cycle(_raw(), _brief())

    assert set(out) == _KEYS
    assert out["flight_plan"] == _STUB_OUTPUT["07"]()
    assert "committed_flight_action" in out["flight_plan_state"]
