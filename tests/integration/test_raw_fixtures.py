"""raw_t{3,4,7}.json 원시 센서 입력 fixture smoke 테스트.

raw 스키마는 layer 02 dev(김수지)가 확정하므로 TypedDict 검증은 하지 않는다.
여기서는 로드 가능·JSON 직렬화 가능·시나리오 구분 값만 회귀 잠금한다.
"""

import json
import pathlib

import pytest

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"

# 시나리오별 mission_phase.declared 국면 (README 추적표 기준)
DECLARED_PHASE = {
    "raw_t3.json": "LOITER_ROI",
    "raw_t4.json": "WAYPOINT",
    "raw_t7.json": "LAND",
}


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(DECLARED_PHASE))
def test_raw_fixture_loads_and_json_serializable(name: str) -> None:
    raw = _load(name)
    json.dumps(raw, allow_nan=False)  # 직렬화 가능해야 함 (레이어 간 dict 계약)
    assert raw["mission_phase"]["declared"] == DECLARED_PHASE[name]


def test_raw_t3_carries_gunshot_and_weapon_signal() -> None:
    raw = _load("raw_t3.json")
    # T3 근접 소화기: 음향 임펄스 + 무장 형상
    assert raw["acoustic"]["rms"] >= 0.7
    assert raw["camera"]["objects"][0]["weapon_shape"] is True


def test_raw_t7_time_to_collision_under_3s() -> None:
    raw = _load("raw_t7.json")
    # T7 지형충돌: 충돌예상시간(TTC) < 3.0s
    ttc = raw["obstacle"]["distance_m"] / raw["obstacle"]["closure_rate_mps"]
    assert ttc < 3.0
