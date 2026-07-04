"""layer_04_threat 테스트 공용 fixture.

layer 03(11채널)이 완전 구현되었으므로, 04 테스트 fixture 는 D4D 문서 예시 값을
손으로 옮긴 mock 대신 실제 layer_03_abstraction.run() 출력을 그대로 소비한다
(정본화 — 손복사 값과 실측 출력 간 drift 제거, Refs #41). raw 정본은
examples/raw_*.json 과 mock_source.build_normal_envelope 이다.

- t3: raw_t3 (근접 소화기, LOITER_ROI) → proximity_object(무기형상) + acoustic(총성) → T3
- t4: raw_t4 (물리 포획, WAYPOINT mismatch) → proximity closing + phase mismatch + link 열화 → T4
- t7: raw_t7 (지형충돌/CFIT, LAND) → obstacle_proximity TTC<3초 → T7
- normal: build_normal_envelope → 이상 신호 없음
- stub: orchestrator 가 03 실패/degrade 시 넘기는 빈 출력(합성 유지 — 실패 경로 계약)
"""

from __future__ import annotations

import json
import pathlib

import pytest

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction import run as layer_03
from onboard.shared.schemas import AbstractionOutput

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _abstraction_from_raw(name: str) -> AbstractionOutput:
    raw = json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))
    return layer_03.run(raw)


@pytest.fixture
def abstraction_t3() -> AbstractionOutput:
    """raw_t3 → 실측 03 출력 (proximity_object 무기형상 + acoustic gunshot → T3)."""
    return _abstraction_from_raw("raw_t3.json")


@pytest.fixture
def abstraction_t4() -> AbstractionOutput:
    """raw_t4 → 실측 03 출력 (proximity closing + mission_phase mismatch + link_status 열화 → T4)."""
    return _abstraction_from_raw("raw_t4.json")


@pytest.fixture
def abstraction_t7() -> AbstractionOutput:
    """raw_t7 → 실측 03 출력 (obstacle_proximity 충돌예상시간<3초, LAND → T7)."""
    return _abstraction_from_raw("raw_t7.json")


@pytest.fixture
def abstraction_stub() -> AbstractionOutput:
    """orchestrator 가 03 실패/degrade 시 넘기는 stub (mission_phase 채널 없음)."""
    return {
        "schema_version": "0.0-stub",
        "id": "stub",
        "ts": 0,
        "channels": [],
    }


@pytest.fixture
def abstraction_normal() -> AbstractionOutput:
    """build_normal_envelope → 실측 03 출력 (이상 신호 없음 → 매칭 없음)."""
    return layer_03.run(build_normal_envelope("NORMAL", 0, 0))
