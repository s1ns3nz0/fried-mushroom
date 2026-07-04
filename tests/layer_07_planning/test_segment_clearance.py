"""07 DEM 구간 최저 clearance 분석 헬퍼 (#341 후속) — 봉우리가 waypoint 사이일 때 포착."""

from onboard.layer_07_planning.terrain import (
    compute_bbox,
    segment_min_clearance,
    terrain_elev_m,
)

_WPS = [
    {"lat": 37.50, "lon": 127.00, "alt_m": 120},
    {"lat": 37.60, "lon": 127.10, "alt_m": 120},
]
_BBOX = compute_bbox(_WPS)


def test_returns_contract_keys():
    r = segment_min_clearance(_WPS[0], _WPS[1], _BBOX)
    assert set(r) == {"min_clearance_m", "min_at_frac", "terrain_max_m"}
    assert 0.0 <= r["min_at_frac"] <= 1.0


def test_min_clearance_not_worse_than_endpoints_only():
    # 구간 샘플 최저 clearance <= 두 끝점 중 낮은 clearance (사이 봉우리를 포착하므로).
    p1, p2 = _WPS
    end_clr = [p1["alt_m"] - terrain_elev_m(p1["lat"], p1["lon"], _BBOX),
               p2["alt_m"] - terrain_elev_m(p2["lat"], p2["lon"], _BBOX)]
    r = segment_min_clearance(p1, p2, _BBOX)
    assert r["min_clearance_m"] <= min(end_clr) + 1e-6


def test_captures_interior_peak():
    # 끝점은 봉우리 밖(정규화 [0.1,0.9] 모서리)이지만 중앙이 봉우리 쪽 → 구간 최저가
    # 끝점 clearance 보다 낮아야 한다(사이 봉우리 포착).
    p1 = {"lat": _BBOX["lat_max"], "lon": _BBOX["lon_min"], "alt_m": 120}
    p2 = {"lat": _BBOX["lat_min"], "lon": _BBOX["lon_max"], "alt_m": 120}
    r = segment_min_clearance(p1, p2, _BBOX, samples=40)
    end_min = min(120 - terrain_elev_m(p1["lat"], p1["lon"], _BBOX),
                  120 - terrain_elev_m(p2["lat"], p2["lon"], _BBOX))
    assert r["min_clearance_m"] <= end_min
    assert r["terrain_max_m"] >= 0.0


def test_deterministic():
    a = segment_min_clearance(_WPS[0], _WPS[1], _BBOX)
    b = segment_min_clearance(_WPS[0], _WPS[1], _BBOX)
    assert a == b


def test_low_altitude_negative_clearance():
    # 저고도 + 봉우리 교차 → 음수 clearance(CFIT) 포착.
    p1 = {"lat": _BBOX["lat_max"], "lon": _BBOX["lon_min"], "alt_m": 10}
    p2 = {"lat": _BBOX["lat_min"], "lon": _BBOX["lon_max"], "alt_m": 10}
    r = segment_min_clearance(p1, p2, _BBOX, samples=40)
    assert r["min_clearance_m"] < 0  # 봉우리(최대 ~100m) > alt 10m
