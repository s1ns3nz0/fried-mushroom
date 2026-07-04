"""sensor_health advisory run_cycle 배선 계약 — TDD (#400).

assess_sensor_health(abstraction)가 run_cycle 결과 dict 에 "sensor_health" 키로
포함되는지 검증한다. advisory_only=True — SCC-1 준수, 결정론 판정(RAC/threat/response) 불변.
"""

import json
import pathlib
import copy

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import run_cycle

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name):
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _brief():
    return _load("mission_brief_t3.json")


def _raw():
    return build_normal_envelope("sh", 0, 0)


# 1. run_cycle 결과에 sensor_health 키
def test_run_cycle_result_contains_sensor_health_key():
    out = run_cycle(_raw(), _brief())
    assert "sensor_health" in out


# 2. 필수 필드 존재
def test_sensor_health_has_required_fields():
    out = run_cycle(_raw(), _brief())
    sh = out["sensor_health"]
    assert isinstance(sh, dict)
    assert "assessable" in sh
    assert "health" in sh
    assert "advisory_only" in sh
    assert sh["advisory_only"] is True


# 3. health 값은 NOMINAL/DEGRADED/CRITICAL/UNKNOWN 중 하나
def test_sensor_health_health_is_valid():
    out = run_cycle(_raw(), _brief())
    assert out["sensor_health"]["health"] in ("NOMINAL", "DEGRADED", "CRITICAL", "UNKNOWN")


# 4. SCC-1: sensor_health 추가가 결정론 판정에 영향 없음
def test_sensor_health_does_not_change_risk_rac():
    out1 = run_cycle(_raw(), _brief())
    out2 = run_cycle(_raw(), _brief())
    assert out1["risk"] == out2["risk"]
    assert out1["threat"] == out2["threat"]
    assert out1["response"] == out2["response"]


def test_sensor_health_does_not_change_flight_plan():
    out1 = run_cycle(_raw(), _brief())
    out2 = run_cycle(_raw(), _brief())
    assert out1["flight_plan"] == out2["flight_plan"]


# 5. 결과 JSON 직렬화 가능
def test_sensor_health_json_serializable():
    out = run_cycle(_raw(), _brief())
    dumped = json.dumps(out, ensure_ascii=False)
    assert json.loads(dumped)["sensor_health"]["advisory_only"] is True


# 6. sensor_health가 추가된 후에도 기존 키 전부 존재
def test_existing_keys_still_present():
    out = run_cycle(_raw(), _brief())
    for key in ("abstraction", "threat", "risk", "response", "flight_plan", "flight_plan_state", "endurance"):
        assert key in out


# 7. 키셋 = 기존 7키 + sensor_health
def test_run_cycle_keyset_with_sensor_health():
    out = run_cycle(_raw(), _brief())
    expected = {"abstraction", "threat", "risk", "response",
                "flight_plan", "flight_plan_state", "endurance", "corridor", "sensor_health"}
    assert set(out) == expected


# 8. sensor_health는 abstraction에서 파생 (assessable은 채널 있을 때 True)
def test_sensor_health_assessable_when_channels_present():
    out = run_cycle(_raw(), _brief())
    sh = out["sensor_health"]
    if sh["assessable"]:
        assert sh["channel_count"] > 0


# 9. sensor_health는 raw/mission_brief를 변이하지 않음
def test_sensor_health_no_mutation():
    raw = _raw()
    brief = _load("mission_brief_t3.json")
    raw_copy = copy.deepcopy(raw)
    brief_copy = copy.deepcopy(brief)
    run_cycle(raw, brief)
    assert raw == raw_copy
    assert brief == brief_copy
