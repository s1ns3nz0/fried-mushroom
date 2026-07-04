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


def _abstraction_from_raw(
    name: str, previous_qualities_name: str | None = None
) -> AbstractionOutput:
    raw = json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))
    previous_qualities = (
        json.loads((_EXAMPLES / previous_qualities_name).read_text(encoding="utf-8"))
        if previous_qualities_name is not None
        else None
    )
    return layer_03.run(raw, previous_qualities)


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
def abstraction_t5() -> AbstractionOutput:
    """raw_t5 + qualities_t5_primed → 실측 03 출력 (terrain_class quality_delta 급락 → T5).

    #79/#97 종단 언블록. previous_qualities(terrain_class=1.0) 대비 raw_t5 의
    terrain camera_confidence=0.65 → quality_delta=-0.35<-0.3 → T5 단일채널(terrain_class) 매칭.
    proximity_object 는 previous_quality 미주입이라 delta=0.0 → 미매칭.
    """
    return _abstraction_from_raw("raw_t5.json", "qualities_t5_primed.json")


@pytest.fixture
def abstraction_t6() -> AbstractionOutput:
    """raw_t6 → 실측 03 출력 (open_field 고노출 exposure_score=0.8, 활성 위협 신호 없음 → 매칭 없음).

    #52 배경노출 종단 시나리오. terrain_class.quality_delta=0.0 (급락 아님) 이라 T5 매칭도
    없고, 나머지 채널 전부 normal → candidates=[] · primary=None 이면서 노출도만 통과된다.
    """
    return _abstraction_from_raw("raw_t6.json")


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
