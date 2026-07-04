"""07 route.py — terrain-aware 경로 생성 단위 테스트 (issue #102).

수용 기준:
- 07 출력에 terrain-aware 경로(좌표+고도 배열) 포함
- 지형에 대해 최소 안전 clearance 보장
- 물리적 상승/하강률 내
"""

import pytest

from onboard.layer_07_planning.route import generate_route
from onboard.shared.constants import ROUTE_MAX_CLIMB_RATE_M_PER_WP, ROUTE_MIN_CLEARANCE_M

_WPS = [
    {"id": "wp1", "lat": 37.50, "lon": 127.00, "alt_m": 120},
    {"id": "wp2", "lat": 37.51, "lon": 127.01, "alt_m": 120},
    {"id": "wp3", "lat": 37.52, "lon": 127.02, "alt_m": 120},
]

_BASES = {
    "emergency": {"id": "base_emergency", "lat": 37.49, "lon": 127.00, "alt_m": 50},
    "alternate": {"id": "base_alternate", "lat": 37.48, "lon": 127.005, "alt_m": 50},
}

_CTX = {"corridor_waypoints": _WPS, "corridor_bases": _BASES}


# ---------------------------------------------------------------------------
# 기본 계약
# ---------------------------------------------------------------------------


def test_maintain_returns_empty_route():
    route = generate_route("MAINTAIN", 0, "NONE", _CTX)
    assert route == [], "MAINTAIN(replan_scope=NONE) 는 빈 경로를 반환해야 함"


def test_no_corridor_returns_empty_route():
    route = generate_route("ALTITUDE_CHANGE", 15, "LOCAL", {})
    assert route == [], "corridor_waypoints 없으면 빈 경로를 반환해야 함"


def test_route_waypoints_have_required_fields():
    route = generate_route("ALTITUDE_CHANGE", 15, "LOCAL", _CTX)
    assert route, "ALTITUDE_CHANGE 는 비어 있지 않은 경로를 반환해야 함"
    for wp in route:
        assert "lat" in wp, "lat 필드 누락"
        assert "lon" in wp, "lon 필드 누락"
        assert "alt_m" in wp, "alt_m 필드 누락"
        assert "clearance_m" in wp, "clearance_m 필드 누락"


def test_route_is_json_serializable():
    import json
    route = generate_route("ALTITUDE_CHANGE", 15, "LOCAL", _CTX)
    assert json.dumps(route)  # 직렬화 가능해야 함


# ---------------------------------------------------------------------------
# 고도 delta 적용
# ---------------------------------------------------------------------------


def test_altitude_change_applies_delta_to_all_waypoints():
    route = generate_route("ALTITUDE_CHANGE", 15, "LOCAL", _CTX)
    assert len(route) == len(_WPS), "waypoint 수 일치해야 함"
    for i, wp in enumerate(route):
        expected_alt = _WPS[i]["alt_m"] + 15
        assert wp["alt_m"] == pytest.approx(expected_alt), (
            f"wp[{i}] alt_m={wp['alt_m']} — 예상 {expected_alt}"
        )


def test_posture_elevate_applies_larger_delta():
    from onboard.shared.constants import POSTURE_ELEVATE_ALTITUDE_M

    route = generate_route("POSTURE_ELEVATE", POSTURE_ELEVATE_ALTITUDE_M, "LOCAL", _CTX)
    assert len(route) == len(_WPS)
    for i, wp in enumerate(route):
        assert wp["alt_m"] == pytest.approx(_WPS[i]["alt_m"] + POSTURE_ELEVATE_ALTITUDE_M)


def test_full_replan_applies_delta():
    route = generate_route("ALTITUDE_CHANGE_REROUTE", 50, "FULL", _CTX)
    assert route, "ALTITUDE_CHANGE_REROUTE 는 비어 있지 않은 경로를 반환해야 함"
    for i, wp in enumerate(route):
        assert wp["alt_m"] == pytest.approx(_WPS[i]["alt_m"] + 50)


# ---------------------------------------------------------------------------
# 최소 clearance
# ---------------------------------------------------------------------------


def test_min_clearance_enforced_when_alt_too_low():
    """현재 고도 + delta < ROUTE_MIN_CLEARANCE_M 이면 ROUTE_MIN_CLEARANCE_M 로 clamp."""
    low_wps = [{"id": "wp1", "lat": 37.50, "lon": 127.00, "alt_m": 30}]
    ctx = {"corridor_waypoints": low_wps}
    route = generate_route("ALTITUDE_CHANGE", -20, "LOCAL", ctx)
    assert route[0]["alt_m"] >= ROUTE_MIN_CLEARANCE_M, (
        f"alt_m={route[0]['alt_m']} < ROUTE_MIN_CLEARANCE_M={ROUTE_MIN_CLEARANCE_M}"
    )


def test_all_waypoints_meet_min_clearance():
    route = generate_route("ALTITUDE_CHANGE", 15, "LOCAL", _CTX)
    for wp in route:
        assert wp["alt_m"] >= ROUTE_MIN_CLEARANCE_M, (
            f"alt_m={wp['alt_m']} < 최소 clearance={ROUTE_MIN_CLEARANCE_M}"
        )


def test_clearance_field_reflects_real_dem():
    """실 DEM(#341): clearance_m = alt_m - terrain_elev_m. 지형표고 필드 노출 + 여유고도
    가 표고를 반영(계곡≈alt, 봉우리 급감)."""
    from onboard.layer_07_planning.terrain import compute_bbox, terrain_elev_m

    bbox = compute_bbox(_CTX["corridor_waypoints"])
    route = generate_route("ALTITUDE_CHANGE", 15, "LOCAL", _CTX)
    for wp in route:
        assert "terrain_elev_m" in wp
        expected_elev = terrain_elev_m(wp["lat"], wp["lon"], bbox)
        assert wp["terrain_elev_m"] == pytest.approx(expected_elev)
        assert wp["clearance_m"] == pytest.approx(wp["alt_m"] - expected_elev)
    # 지형 변동이 있으면 clearance 가 모두 alt 와 동일하진 않다(stub 이 아님).
    assert any(wp["clearance_m"] != pytest.approx(wp["alt_m"]) for wp in route)


# ---------------------------------------------------------------------------
# 물리적 상승/하강률
# ---------------------------------------------------------------------------


def test_consecutive_altitude_diff_within_max_rate_uniform_delta():
    """동일 delta 적용 시 연속 waypoint 간 고도 차이가 0 → 상승률 제한 내."""
    route = generate_route("ALTITUDE_CHANGE", 15, "LOCAL", _CTX)
    for i in range(len(route) - 1):
        diff = abs(route[i + 1]["alt_m"] - route[i]["alt_m"])
        assert diff <= ROUTE_MAX_CLIMB_RATE_M_PER_WP, (
            f"연속 고도 차이 {diff}m > 제한 {ROUTE_MAX_CLIMB_RATE_M_PER_WP}m"
        )


# ---------------------------------------------------------------------------
# RTL
# ---------------------------------------------------------------------------


def test_rtl_reverses_waypoints():
    """RTL 은 corridor 역순으로 경로를 생성한다."""
    route = generate_route("RTL", 0, "LOCAL", _CTX)
    assert route, "RTL 은 비어 있지 않은 경로를 반환해야 함"
    # 역순: 마지막 corridor wp 가 첫 번째 route wp
    assert route[0]["lat"] == pytest.approx(_WPS[-1]["lat"])
    assert route[0]["lon"] == pytest.approx(_WPS[-1]["lon"])


def test_rtl_route_ends_near_emergency_base():
    """RTL 경로의 마지막 waypoint 는 emergency base 위치에 가깝다."""
    route = generate_route("RTL", 0, "LOCAL", _CTX)
    base = _BASES["emergency"]
    last = route[-1]
    assert last["lat"] == pytest.approx(base["lat"])
    assert last["lon"] == pytest.approx(base["lon"])


def test_rtl_all_waypoints_meet_min_clearance():
    """RTL 경로의 모든 waypoint 도 최소 clearance 를 보장한다."""
    route = generate_route("RTL", 0, "LOCAL", _CTX)
    for wp in route:
        assert wp["alt_m"] >= ROUTE_MIN_CLEARANCE_M


# ---------------------------------------------------------------------------
# 비균일 고도 보간 (rate-limiting 실제 발동 케이스)
# ---------------------------------------------------------------------------


def test_rate_limiting_inserts_intermediate_waypoints():
    """고도 차이가 ROUTE_MAX_CLIMB_RATE_M_PER_WP 초과 시 중간 waypoint 가 삽입된다."""
    import math

    # 150→60 = 90m 하강 (min clearance=50 이상이라 clamp 없음)
    steep_wps = [
        {"id": "wp1", "lat": 37.50, "lon": 127.00, "alt_m": 150},
        {"id": "wp2", "lat": 37.51, "lon": 127.01, "alt_m": 60},
    ]
    ctx = {"corridor_waypoints": steep_wps}
    route = generate_route("ALTITUDE_CHANGE", 0, "LOCAL", ctx)

    # 고도차 90m → ceil(90/10)=9 스텝 → 8 중간 waypoint 삽입 → 총 10개
    expected_count = 1 + math.ceil(90 / ROUTE_MAX_CLIMB_RATE_M_PER_WP) - 1 + 1
    assert len(route) == expected_count, (
        f"중간 waypoint 삽입 후 총 {expected_count}개 예상, 실제 {len(route)}개"
    )
    # 모든 연속 차이가 제한 이내
    for i in range(len(route) - 1):
        diff = abs(route[i + 1]["alt_m"] - route[i]["alt_m"])
        assert diff <= ROUTE_MAX_CLIMB_RATE_M_PER_WP + 1e-9, (
            f"연속 고도 차이 {diff}m > 제한 {ROUTE_MAX_CLIMB_RATE_M_PER_WP}m"
        )


def test_all_consecutive_diffs_within_max_rate_nonuniform():
    """비균일 고도 코리더에서도 모든 연속 고도 차이가 상한 이내."""
    nonuniform_wps = [
        {"id": "wp1", "lat": 37.50, "lon": 127.00, "alt_m": 60},
        {"id": "wp2", "lat": 37.51, "lon": 127.01, "alt_m": 60},
        {"id": "wp3", "lat": 37.52, "lon": 127.02, "alt_m": 5},
    ]
    ctx = {"corridor_waypoints": nonuniform_wps}
    route = generate_route("ALTITUDE_CHANGE", 15, "LOCAL", ctx)
    for i in range(len(route) - 1):
        diff = abs(route[i + 1]["alt_m"] - route[i]["alt_m"])
        assert diff <= ROUTE_MAX_CLIMB_RATE_M_PER_WP + 1e-9, (
            f"연속 고도 차이 {diff}m > 제한 {ROUTE_MAX_CLIMB_RATE_M_PER_WP}m"
        )


def test_rtl_altitude_profile_rate_limited():
    """RTL 에서 base 고도가 코리더보다 크게 낮을 때 하강률이 제한 이내."""
    rtl_wps = [
        {"id": "wp1", "lat": 37.50, "lon": 127.00, "alt_m": 120},
        {"id": "wp2", "lat": 37.51, "lon": 127.01, "alt_m": 120},
    ]
    bases = {"emergency": {"id": "base", "lat": 37.49, "lon": 126.99, "alt_m": 50}}
    ctx = {"corridor_waypoints": rtl_wps, "corridor_bases": bases}
    route = generate_route("RTL", 0, "LOCAL", ctx)
    # 마지막 구간 120→50=70m 하강 — 중간 waypoint 삽입으로 제한 강제
    assert len(route) > len(rtl_wps) + 1, "70m 하강 시 중간 waypoint 가 삽입되어야 함"
    for i in range(len(route) - 1):
        diff = abs(route[i + 1]["alt_m"] - route[i]["alt_m"])
        assert diff <= ROUTE_MAX_CLIMB_RATE_M_PER_WP + 1e-9, (
            f"RTL 연속 고도 차이 {diff}m > 제한 {ROUTE_MAX_CLIMB_RATE_M_PER_WP}m"
        )


# ---------------------------------------------------------------------------
# 수평 회피 궤적 — bearing offset (issue #132)
# ---------------------------------------------------------------------------

_BEAR_WPS = [
    {"id": "wp1", "lat": 37.500, "lon": 127.000, "alt_m": 120},
    {"id": "wp2", "lat": 37.510, "lon": 127.010, "alt_m": 120},
    {"id": "wp3", "lat": 37.520, "lon": 127.020, "alt_m": 120},
]
_BEAR_CTX = {"corridor_waypoints": _BEAR_WPS, "corridor_bases": _BASES}


def test_reroute_bearing_offset_north():
    """REROUTE + bearing=0°(북향) → 모든 waypoint lat 증가, lon 불변."""
    route = generate_route("REROUTE", 0, "FULL", _BEAR_CTX, target_bearing_deg=0.0)
    assert len(route) == len(_BEAR_WPS)
    for i, wp in enumerate(route):
        assert wp["lat"] > _BEAR_WPS[i]["lat"], f"wp[{i}] lat이 북쪽으로 이동해야 함"
        assert abs(wp["lon"] - _BEAR_WPS[i]["lon"]) < 1e-9, f"wp[{i}] lon이 변하면 안 됨"


def test_reroute_bearing_offset_east():
    """REROUTE + bearing=90°(동향) → 모든 waypoint lon 증가, lat 불변."""
    route = generate_route("REROUTE", 0, "FULL", _BEAR_CTX, target_bearing_deg=90.0)
    assert len(route) == len(_BEAR_WPS)
    for i, wp in enumerate(route):
        assert abs(wp["lat"] - _BEAR_WPS[i]["lat"]) < 1e-9, f"wp[{i}] lat이 변하면 안 됨"
        assert wp["lon"] > _BEAR_WPS[i]["lon"], f"wp[{i}] lon이 동쪽으로 이동해야 함"


def test_altitude_change_reroute_offset_applied():
    """ALTITUDE_CHANGE_REROUTE (FULL) + bearing → bearing offset 적용."""
    route = generate_route(
        "ALTITUDE_CHANGE_REROUTE", 50, "FULL", _BEAR_CTX, target_bearing_deg=90.0
    )
    assert len(route) == len(_BEAR_WPS)
    for i, wp in enumerate(route):
        assert wp["lon"] > _BEAR_WPS[i]["lon"], f"wp[{i}] lon이 동쪽으로 이동해야 함"


def test_rtl_no_bearing_offset():
    """RTL (LOCAL scope) + bearing 전달 → offset 미적용, 결과 동일."""
    route_no_bearing = generate_route("RTL", 0, "LOCAL", _BEAR_CTX)
    route_with_bearing = generate_route("RTL", 0, "LOCAL", _BEAR_CTX, target_bearing_deg=90.0)
    assert len(route_no_bearing) == len(route_with_bearing)
    for a, b in zip(route_no_bearing, route_with_bearing):
        assert a["lat"] == pytest.approx(b["lat"])
        assert a["lon"] == pytest.approx(b["lon"])


def test_null_bearing_no_offset():
    """target_bearing_deg=None → offset 미적용, corridor 원좌표 유지."""
    route = generate_route("REROUTE", 0, "FULL", _BEAR_CTX, target_bearing_deg=None)
    assert len(route) == len(_BEAR_WPS)
    for i, wp in enumerate(route):
        assert wp["lat"] == pytest.approx(_BEAR_WPS[i]["lat"])
        assert wp["lon"] == pytest.approx(_BEAR_WPS[i]["lon"])


def test_bearing_offset_magnitude_north():
    """bearing=0° 위도 이동량이 ROUTE_EVASION_OFFSET_M / EARTH_RADIUS_M 에 대응."""
    import math
    from onboard.shared.constants import ROUTE_EVASION_OFFSET_M
    route = generate_route("REROUTE", 0, "FULL", _BEAR_CTX, target_bearing_deg=0.0)
    lat_diff = route[0]["lat"] - _BEAR_WPS[0]["lat"]
    expected = math.degrees(ROUTE_EVASION_OFFSET_M / 6_371_000.0)
    assert lat_diff == pytest.approx(expected, rel=1e-4)


def test_local_scope_no_bearing_offset():
    """ALTITUDE_CHANGE(LOCAL scope) + bearing → offset 미적용, lon 불변."""
    route = generate_route("ALTITUDE_CHANGE", 15, "LOCAL", _BEAR_CTX, target_bearing_deg=90.0)
    assert len(route) == len(_BEAR_WPS)
    for i, wp in enumerate(route):
        assert wp["lon"] == pytest.approx(_BEAR_WPS[i]["lon"])


def test_bearing_offset_preserves_alt_clearance_tracks_terrain():
    """bearing offset은 위경도만 이동, alt_m은 보존. clearance_m 은 실 DEM(#341)이라
    이동한 지점의 지형표고를 반영한다(= alt - terrain_elev at new lat/lon)."""
    from onboard.layer_07_planning.terrain import compute_bbox, terrain_elev_m

    bbox = compute_bbox(_BEAR_CTX["corridor_waypoints"])
    route = generate_route("REROUTE", 0, "FULL", _BEAR_CTX, target_bearing_deg=45.0)
    for i, wp in enumerate(route):
        assert wp["alt_m"] == pytest.approx(_BEAR_WPS[i]["alt_m"])
        assert wp["clearance_m"] == pytest.approx(
            wp["alt_m"] - terrain_elev_m(wp["lat"], wp["lon"], bbox))
