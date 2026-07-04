"""07 지형표고(DEM) — 결정론 heightmap (flat DEM=0 stub 대체, #341).

`infra/vizsim/terrain.py`(대시보드 app.js PEAKS/heightAt 포트)의 **지형 형상**을 온보드로
포팅한다. **무-외부의존**(stdlib math) — PEAKS/height_at 를 데이터·함수로 내장한다.

스케일 정합(중요): vizsim 의 시각용 표고 elev_m=190+h*650(≈255~840m)를 그대로 쓰면
코리더 고도(60~150m)가 전부 지형 아래가 되어 clearance 가 전부 음수가 된다. 온보드는
경로 clearance/CFIT 판정이 목적이므로, 지형 형상(height_at, 정규화 h∈[0.1,1.0])은
그대로 재사용하되 **표고를 온보드 고도대에 맞춰 [0, TERRAIN_ELEV_MAX_M] 로 매핑**한다.
이로써 계곡은 clearance≈alt, 봉우리 교차·저고도(t4/t7) 구간은 clearance 가 급감/음수가
되어 지형충돌(CFIT) 위험이 실제 값으로 드러난다.

lat/lon → 정규화 (x,y): route 코리더의 bbox 를 캔버스 [MARGIN, 1-MARGIN] 에 매핑
(vizsim route.to_norm 과 동일 규약 — sim/대시보드 지형 프레임과 일치).
"""

from __future__ import annotations

import math

# 지형 봉우리(정규화 좌표) — vizsim/terrain.PEAKS, app.js PEAKS 와 동일.
PEAKS = [
    {"x": 0.28, "y": 0.30, "h": 0.95, "r": 0.17},
    {"x": 0.66, "y": 0.58, "h": 0.80, "r": 0.15},
    {"x": 0.48, "y": 0.14, "h": 0.62, "r": 0.13},
    {"x": 0.82, "y": 0.74, "h": 0.58, "r": 0.13},
    {"x": 0.14, "y": 0.62, "h": 0.45, "r": 0.12},
]

# 정규화 매핑 상수 — vizsim/route.MARGIN/SPAN 과 동일.
_MARGIN = 0.1
_SPAN = 1.0 - 2 * _MARGIN  # 0.8

# 온보드 DEM 표고 스케일(m). height_at h∈[0.1,1.0] → 표고 [_BASE, _BASE+_RANGE].
# 저고도 임무(t4 80m, t7 5~60m)에서 봉우리 교차 시 clearance 가 음수가 되도록 보정.
TERRAIN_ELEV_MAX_M = 100.0
TERRAIN_ELEV_BASE_M = 0.0


def height_at(x: float, y: float) -> float:
    """정규화 (x,y) 의 gaussian 봉우리 합 (<=1.0 clamp). vizsim/app.js heightAt 동일."""
    h = 0.10
    for p in PEAKS:
        dx = x - p["x"]
        dy = y - p["y"]
        h += p["h"] * math.exp(-(dx * dx + dy * dy) / (2 * p["r"] * p["r"]))
    return 1.0 if h > 1.0 else h


def to_norm(lat: float, lon: float, bbox: dict) -> tuple[float, float]:
    """lat/lon → 캔버스 정규화 (x,y). vizsim/route.to_norm 규약(bbox→[MARGIN,1-MARGIN])."""
    lat_range = (bbox["lat_max"] - bbox["lat_min"]) or 1.0
    lon_range = (bbox["lon_max"] - bbox["lon_min"]) or 1.0
    x = _MARGIN + (lon - bbox["lon_min"]) / lon_range * _SPAN
    y = _MARGIN + (bbox["lat_max"] - lat) / lat_range * _SPAN
    return x, y


def compute_bbox(waypoints: list[dict]) -> dict:
    """코리더 waypoints 의 lat/lon 경계상자. vizsim/route.compute_bbox 동일."""
    lats = [float(wp["lat"]) for wp in waypoints]
    lons = [float(wp["lon"]) for wp in waypoints]
    return {
        "lat_min": min(lats), "lat_max": max(lats),
        "lon_min": min(lons), "lon_max": max(lons),
    }


def terrain_elev_m(lat: float, lon: float, bbox: dict) -> float:
    """(lat, lon) 지형표고(m) — 결정론. bbox 는 코리더 프레임(compute_bbox).

    height_at 정규화 h∈[0.1,1.0] 를 [BASE, BASE+MAX] 로 선형 매핑(h=0.1→BASE,
    h=1.0→BASE+MAX). 6자리 반올림(atan2/exp ULP 이식성 — bearing 골든 교훈과 동일).
    """
    x, y = to_norm(lat, lon, bbox)
    h = height_at(x, y)
    elev = TERRAIN_ELEV_BASE_M + (h - 0.1) / 0.9 * TERRAIN_ELEV_MAX_M
    return round(elev, 6)


def segment_min_clearance(
    p1: dict, p2: dict, bbox: dict, *, samples: int = 20
) -> dict:
    """선분 p1→p2 를 따라 지형표고를 샘플링해 **구간 최저 clearance** 를 찾는다 (#341 후속).

    route.py 의 waypoint별 clearance 는 끝점만 보므로, 봉우리가 두 waypoint **사이**에
    있으면 놓친다(CFIT 위험 과소평가). 이 함수는 선분을 samples 등분해 lat/lon·alt 를
    선형 보간하며 각 지점의 clearance(=alt - terrain_elev)를 계산, 최저값을 반환한다.
    경로 출력을 바꾸지 않는 **분석 헬퍼**(골든 불변) — CFIT 판정/프로파일에서 소비.

    p1/p2: {lat, lon, alt_m}. 반환: {min_clearance_m, min_at_frac, terrain_max_m}.
    """
    n = max(2, int(samples))
    lat1, lon1, alt1 = float(p1["lat"]), float(p1["lon"]), float(p1.get("alt_m", 0.0))
    lat2, lon2, alt2 = float(p2["lat"]), float(p2["lon"]), float(p2.get("alt_m", 0.0))
    min_clr = float("inf")
    min_frac = 0.0
    terrain_max = float("-inf")
    for i in range(n + 1):
        t = i / n
        lat = lat1 + t * (lat2 - lat1)
        lon = lon1 + t * (lon2 - lon1)
        alt = alt1 + t * (alt2 - alt1)
        elev = terrain_elev_m(lat, lon, bbox)
        clr = alt - elev
        if clr < min_clr:
            min_clr = clr
            min_frac = t
        if elev > terrain_max:
            terrain_max = elev
    return {
        "min_clearance_m": round(min_clr, 6),
        "min_at_frac": round(min_frac, 6),
        "terrain_max_m": round(terrain_max, 6),
    }
