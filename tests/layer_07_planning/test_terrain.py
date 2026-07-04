"""07 지형표고(DEM) 결정론·경계·스케일 테스트 (#341)."""

import math

from onboard.layer_07_planning.terrain import (
    TERRAIN_ELEV_MAX_M,
    compute_bbox,
    height_at,
    terrain_elev_m,
    to_norm,
)

_WPS = [
    {"lat": 37.50, "lon": 127.00, "alt_m": 120},
    {"lat": 37.52, "lon": 127.02, "alt_m": 120},
]
_BBOX = compute_bbox(_WPS)


def test_height_at_clamped_and_baseline():
    # 봉우리 없는 먼 지점은 baseline 0.10 근처, 봉우리 중심은 높음, 항상 <=1.
    assert height_at(0.28, 0.30) > 0.8          # PEAK1 중심(h=0.95)
    assert 0.09 < height_at(0.99, 0.01) < 0.2   # 봉우리에서 먼 구석
    assert height_at(0.28, 0.30) <= 1.0


def test_deterministic():
    assert terrain_elev_m(37.51, 127.01, _BBOX) == terrain_elev_m(37.51, 127.01, _BBOX)


def test_elev_scale_bounds():
    # 표고는 [0, TERRAIN_ELEV_MAX_M] 범위(h∈[0.1,1] 선형 매핑).
    samples = [terrain_elev_m(37.50 + i * 0.002, 127.00 + i * 0.002, _BBOX) for i in range(11)]
    for e in samples:
        assert 0.0 <= e <= TERRAIN_ELEV_MAX_M + 1e-6
        assert not math.isnan(e)


def test_peak_higher_than_valley():
    # 코리더 중앙부(봉우리 쪽)가 프레임 모서리(계곡)보다 표고 높음.
    corner = terrain_elev_m(_BBOX["lat_max"], _BBOX["lon_min"], _BBOX)  # 모서리
    # PEAK1(0.28,0.30) 근처로 매핑되는 지점을 역산 대신 중앙 인근 스캔 최대값.
    mid = max(terrain_elev_m(37.50 + i * 0.002, 127.00 + i * 0.002, _BBOX) for i in range(11))
    assert mid >= corner


def test_to_norm_maps_bbox_corners():
    # bbox 모서리는 [MARGIN, 1-MARGIN]=[0.1,0.9] 로 매핑.
    x, y = to_norm(_BBOX["lat_max"], _BBOX["lon_min"], _BBOX)
    assert abs(x - 0.1) < 1e-9 and abs(y - 0.1) < 1e-9
    x2, y2 = to_norm(_BBOX["lat_min"], _BBOX["lon_max"], _BBOX)
    assert abs(x2 - 0.9) < 1e-9 and abs(y2 - 0.9) < 1e-9


def test_degenerate_bbox_no_div_zero():
    # 단일점/동일좌표 bbox 도 예외 없이 처리.
    b = compute_bbox([{"lat": 37.5, "lon": 127.0}, {"lat": 37.5, "lon": 127.0}])
    assert isinstance(terrain_elev_m(37.5, 127.0, b), float)
