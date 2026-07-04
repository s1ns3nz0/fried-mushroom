"""실 DEM clearance 종단 통합 (#341/#382) — 저고도 시나리오가 파이프라인에서 실 지형
clearance/CFIT 를 반영하는지 검증. 머지된 terrain_elev_m/segment_min_clearance 만 사용.
test-only, 골든 무변경.
"""

import json
from pathlib import Path

from onboard.layer_07_planning.terrain import (
    compute_bbox,
    segment_min_clearance,
    terrain_elev_m,
)
from onboard.run import run_cycle

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _load(n):
    return json.loads((_EXAMPLES / n).read_text(encoding="utf-8"))


def _route(scenario):
    raw = _load(f"raw_{scenario}.json")
    brief = _load(f"mission_brief_{scenario}.json")
    return run_cycle(raw, brief)["flight_plan"].get("route") or [], brief


def test_route_waypoints_carry_terrain_and_clearance():
    # #341: route waypoint 는 terrain_elev_m + clearance_m 을 노출한다.
    route, _ = _route("t3")
    assert route, "t3 route 없음(재계획 필요 시나리오)"
    for wp in route:
        assert "terrain_elev_m" in wp and "clearance_m" in wp
        # clearance = alt - terrain (부동소수 오차 허용).
        assert abs(wp["clearance_m"] - (wp["alt_m"] - wp["terrain_elev_m"])) < 1e-3


def test_clearance_varies_with_terrain():
    # 봉우리 교차 구간에서 clearance 가 waypoint 마다 달라진다(평지 stub 이 아님).
    route, _ = _route("t3")
    clrs = [wp["clearance_m"] for wp in route]
    assert len(set(clrs)) > 1, "clearance 가 전부 동일 — DEM 반영 안 됨(flat stub 회귀)"


def test_low_altitude_scenario_has_reduced_clearance():
    # 저고도(t4=80m)는 t3(120m)보다 봉우리 근처 최저 clearance 가 낮다.
    r_t4, _ = _route("t4")
    r_t3, _ = _route("t3")
    if r_t4 and r_t3:
        assert min(wp["clearance_m"] for wp in r_t4) < min(wp["clearance_m"] for wp in r_t3) + 1e-6


def test_segment_min_clearance_catches_subwaypoint():
    # merged segment_min_clearance: 구간 최저 clearance ≤ 끝점 최저(사이 봉우리 포착).
    route, brief = _route("t3")
    bbox = compute_bbox(brief["corridor"]["waypoints"])
    for i in range(len(route) - 1):
        p1, p2 = route[i], route[i + 1]
        seg = segment_min_clearance(p1, p2, bbox)
        end_min = min(p1["clearance_m"], p2["clearance_m"])
        assert seg["min_clearance_m"] <= end_min + 1e-6


def test_terrain_elev_matches_route_frame():
    # route 의 terrain_elev_m 이 코리더 bbox 프레임 기준 terrain_elev_m 과 일치.
    route, brief = _route("t3")
    bbox = compute_bbox(brief["corridor"]["waypoints"])
    for wp in route:
        assert abs(wp["terrain_elev_m"] - terrain_elev_m(wp["lat"], wp["lon"], bbox)) < 1e-3


def test_deterministic_route_clearance():
    a = [wp["clearance_m"] for wp in _route("t3")[0]]
    b = [wp["clearance_m"] for wp in _route("t3")[0]]
    assert a == b
