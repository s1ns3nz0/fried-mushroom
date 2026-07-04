"""07 bearing 회귀 테스트 (issue #54).

1. camera_verified vs gis_lookup 두 입력에서 07 target_bearing_deg 가 방위 필드에만 의존함.
2. lowest_exposure_bearing_deg 폴백 경로 (PHYSICAL, bearing 없음 → terrain_fallback) 종단 커버리지.
"""

import copy
import json
import pathlib

import pytest

from onboard.run import run_cycle

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _terrain_source(out: dict) -> str | None:
    for ch in out["abstraction"]["channels"]:
        if ch["channel"] == "terrain_class":
            return ch["payload"]["source"]
    return None


def test_07_bearing_independent_of_terrain_source() -> None:
    """07 target_bearing_deg 는 terrain_class.source / dominant_class 에 무관하다.

    두 입력:
    - gis_lookup  : terrain cam_class == gis_class (open_field)
    - camera_verified: cam_class != gis_class (forest vs open_field)

    두 경우 모두 bearing 필드(optimal/lowest)는 stub null → corridor heuristic 사용.
    동일한 corridor waypoints → target_bearing_deg 동일.
    """
    mb = _load("mission_brief_t3.json")

    raw_gis = _load("raw_t3.json")
    raw_gis["imagery"]["terrain_label"]["dominant_class"] = "open_field"

    raw_cam = copy.deepcopy(raw_gis)
    raw_cam["imagery"]["terrain_label"]["dominant_class"] = "forest"  # gis=open_field 불일치

    out_gis = run_cycle(raw_gis, mb)
    out_cam = run_cycle(raw_cam, mb)

    assert _terrain_source(out_gis) == "gis_lookup"
    assert _terrain_source(out_cam) == "camera_verified"

    assert out_gis["flight_plan"]["target_bearing_deg"] == pytest.approx(
        out_cam["flight_plan"]["target_bearing_deg"]
    ), "source 변경만으로 07 target_bearing_deg 가 달라지면 안 된다"


def test_07_bearing_follows_bearing_fields_not_source() -> None:
    """bearing 필드(non-null)가 있을 때도 source 교체에 target_bearing_deg 가 불변임을 확인.

    두 입력이 같은 optimal/lowest_exposure_bearing_deg 를 terrain_label 에 심었을 때,
    source(gis_lookup vs camera_verified) 만 다르면 target_bearing_deg 는 동일.
    """
    mb = _load("mission_brief_t7.json")  # NAVIGATION → optimal_terrain_bearing_deg 소비

    bearing_val = 55.0

    raw_gis = _load("raw_t7.json")
    raw_gis["imagery"]["terrain_label"]["dominant_class"] = "open_field"
    raw_gis["imagery"]["terrain_label"]["optimal_terrain_bearing_deg"] = bearing_val
    raw_gis["imagery"]["terrain_label"]["lowest_exposure_bearing_deg"] = (bearing_val + 90) % 360

    raw_cam = copy.deepcopy(raw_gis)
    raw_cam["imagery"]["terrain_label"]["dominant_class"] = "forest"  # camera_verified

    out_gis = run_cycle(raw_gis, mb)
    out_cam = run_cycle(raw_cam, mb)

    assert _terrain_source(out_gis) == "gis_lookup"
    assert _terrain_source(out_cam) == "camera_verified"

    assert out_gis["flight_plan"]["target_bearing_deg"] == pytest.approx(
        out_cam["flight_plan"]["target_bearing_deg"]
    ), "bearing 필드 동일 + source만 교체 → target_bearing_deg 동일해야 한다"
    assert out_gis["flight_plan"]["target_bearing_deg"] == pytest.approx(bearing_val), (
        "NAVIGATION + optimal_terrain_bearing_deg 주입 → target_bearing_deg 가 주입값과 일치해야 한다"
    )


def test_lowest_exposure_bearing_fallback_e2e() -> None:
    """PHYSICAL 위협 + threat bearing 없음 → lowest_exposure_bearing_deg(terrain_fallback) 종단 경로.

    t3 시나리오: T3(근접 소화기) 탐지, threat context에 bearing_deg 없음.
    07 bearing.py: PHYSICAL + bearing=None → cycle_context.lowest_exposure_bearing_deg 사용.
    """
    out = run_cycle(_load("raw_t3.json"), _load("mission_brief_t3.json"))

    assert out["response"]["threat_category"] == "PHYSICAL"

    expected_bearing = out["threat"]["cycle_context"]["lowest_exposure_bearing_deg"]
    assert expected_bearing is not None, "lowest_exposure_bearing_deg 가 None 이면 폴백 불가"
    assert out["flight_plan"]["target_bearing_deg"] == pytest.approx(expected_bearing)
    assert out["flight_plan"]["reroute_anchor"] == "terrain_fallback"
