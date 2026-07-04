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

_KEYS = {"abstraction", "threat", "risk", "response", "flight_plan"}


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
