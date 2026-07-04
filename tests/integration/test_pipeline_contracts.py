"""종단 파이프라인 계약 불변식 (실측 출력 기준).

golden 테스트가 '값'을, semantics 테스트가 '의미'를 잠근다면, 이 파일은
실제 시나리오 출력에 대해 세 가지 구조 계약을 강제한다:

1. 결정론 (ADR-001, 순수함수): 같은 입력 → 같은 출력. golden 재현의 전제.
2. JSON 왕복 (CLAUDE.md CRITICAL: 레이어 간 dict 는 JSON-직렬화 가능만):
   json.loads(json.dumps(out)) == out.
3. 스키마 적합: 각 레이어 출력이 선언된 TypedDict 계약과 일치.
   (기존 test_orchestrator 는 passthrough/canned 만 검증 — 실측 출력은 미검증이었음.)
"""

import json
import pathlib

import pytest

from onboard.run import run_cycle
from onboard.shared.schemas import (
    AbstractionOutput,
    FlightPlanOutput,
    ResponseOutput,
    RiskAssessmentOutput,
    ThreatModelingOutput,
)
from tests.helpers.contracts import assert_json_serializable, assert_matches_schema

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"

_LAYER_SCHEMA = {
    "abstraction": AbstractionOutput,
    "threat": ThreatModelingOutput,
    "risk": RiskAssessmentOutput,
    "response": ResponseOutput,
    "flight_plan": FlightPlanOutput,
}

# (id, raw 파일, mission_brief 파일). strike 는 raw_t3 재사용.
_SCENARIOS = [
    ("t1", "raw_t1.json", "mission_brief_t1.json"),
    ("t2", "raw_t2.json", "mission_brief_t2.json"),
    ("t3", "raw_t3.json", "mission_brief_t3.json"),
    ("t4", "raw_t4.json", "mission_brief_t4.json"),
    ("t6", "raw_t6.json", "mission_brief_t6.json"),
    ("t7", "raw_t7.json", "mission_brief_t7.json"),
    ("strike", "raw_t3.json", "mission_brief_strike.json"),
]


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _run(raw_name: str, brief_name: str) -> dict:
    return run_cycle(_load(raw_name), _load(brief_name))


@pytest.mark.parametrize("sid,raw,brief", _SCENARIOS, ids=[s[0] for s in _SCENARIOS])
def test_run_cycle_is_deterministic(sid, raw, brief) -> None:
    assert _run(raw, brief) == _run(raw, brief)


@pytest.mark.parametrize("sid,raw,brief", _SCENARIOS, ids=[s[0] for s in _SCENARIOS])
def test_output_json_roundtrips(sid, raw, brief) -> None:
    out = _run(raw, brief)
    assert_json_serializable(out)
    assert json.loads(json.dumps(out, ensure_ascii=False)) == out


@pytest.mark.parametrize("sid,raw,brief", _SCENARIOS, ids=[s[0] for s in _SCENARIOS])
def test_each_layer_output_matches_schema(sid, raw, brief) -> None:
    out = _run(raw, brief)
    # flight_plan_state: 07 RAC 완화 디바운스 상태(ADR-004 07 한정 예외) — 별도 채널이라
    # 레이어 스키마(_LAYER_SCHEMA) 검증 대상이 아니다. 존재 여부만 확인한다.
    assert set(out) == set(_LAYER_SCHEMA) | {"flight_plan_state"}
    assert isinstance(out["flight_plan_state"], dict)
    for layer, schema in _LAYER_SCHEMA.items():
        assert_matches_schema(out[layer], schema)
