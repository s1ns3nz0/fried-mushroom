"""assess_corridor_deviation — 코리더 이탈 감시(공간 항법 무결성).

현재 위치가 계획된 코리더(웨이포인트 폴리라인)에서 얼마나 벗어났는지 cross-track 거리로
계산해 과도 이탈(표류·스푸핑·무단 이탈)을 경보한다. CRITICAL: advisory — 결정을 바꾸지 않고
입력을 변이하지 않는다.
"""

import copy

import pytest

from onboard.corridor import assess_corridor_deviation


def _raw(lat, lon):
    return {"navigation": {"gps": {"lat": lat, "lon": lon, "alt_m": 120}}}


def _brief(wps=None, half_width=None):
    corridor = {"waypoints": wps if wps is not None else [
        {"id": "wp1", "lat": 37.50, "lon": 127.00, "alt_m": 120},
        {"id": "wp2", "lat": 37.52, "lon": 127.00, "alt_m": 120},  # 정북 직선
    ]}
    if half_width is not None:
        corridor["half_width"] = half_width
    return {"corridor": corridor}


# ── 기본 계약 ────────────────────────────────────────────────────────────────

def test_advisory_only_and_no_mutation():
    raw, brief = _raw(37.51, 127.0), _brief()
    rs, bs = copy.deepcopy(raw), copy.deepcopy(brief)
    out = assess_corridor_deviation(raw, brief)
    assert out["advisory_only"] is True
    assert raw == rs and brief == bs


def test_on_corridor_zero_deviation():
    # 코리더(경도 127.0 직선) 위 → 이탈 거의 0
    out = assess_corridor_deviation(_raw(37.51, 127.00), _brief(), max_deviation_m=100)
    assert out["assessable"] is True
    assert out["deviation_m"] == pytest.approx(0, abs=5)
    assert out["within_corridor"] is True


def test_off_corridor_flags_deviation():
    # 경도 +0.005 (~440m 동쪽) → 이탈
    out = assess_corridor_deviation(_raw(37.51, 127.005), _brief(), max_deviation_m=100)
    assert out["deviation_m"] > 300
    assert out["within_corridor"] is False


# ── 임계 소스 ────────────────────────────────────────────────────────────────

def test_half_width_used_as_threshold_when_present():
    brief = _brief(half_width=600)  # 넉넉한 반폭
    out = assess_corridor_deviation(_raw(37.51, 127.005), brief)  # ~440m 이탈
    assert out["within_corridor"] is True  # 440 < 600
    assert out["threshold_m"] == 600


def test_explicit_max_deviation_overrides():
    out = assess_corridor_deviation(_raw(37.51, 127.005), _brief(half_width=600),
                                    max_deviation_m=100)
    assert out["threshold_m"] == 100
    assert out["within_corridor"] is False


# ── 세그먼트 / 견고성 ────────────────────────────────────────────────────────

def test_nearest_segment_reported():
    wps = [{"lat": 37.50, "lon": 127.0}, {"lat": 37.52, "lon": 127.0},
           {"lat": 37.52, "lon": 127.02}]
    out = assess_corridor_deviation(_raw(37.52, 127.01), _brief(wps=wps))
    assert out["nearest_segment_index"] == 1  # 두 번째 세그먼트(동향)에 가까움


def test_missing_gps_not_assessable():
    out = assess_corridor_deviation({"navigation": {}}, _brief())
    assert out["assessable"] is False


def test_single_waypoint_uses_point_distance():
    out = assess_corridor_deviation(_raw(37.51, 127.0),
                                    _brief(wps=[{"lat": 37.50, "lon": 127.0}]))
    assert out["assessable"] is True
    assert out["deviation_m"] > 0  # 단일 wp → 점까지 거리


def test_empty_corridor_not_assessable():
    out = assess_corridor_deviation(_raw(37.5, 127.0), _brief(wps=[]))
    assert out["assessable"] is False


def test_note_present():
    out = assess_corridor_deviation(_raw(37.51, 127.0), _brief())
    assert out["note"]


def test_threshold_source_explicit_when_default_used():
    """half_width 미포함 브리핑(투영본)에선 threshold_source=default 로 명시(silent fallback 방지)."""
    out = assess_corridor_deviation(_raw(37.51, 127.0), _brief())  # half_width 없음
    assert out["threshold_source"] == "default"
    withhw = assess_corridor_deviation(_raw(37.51, 127.0), _brief(half_width=300))
    assert withhw["threshold_source"] == "half_width"
    withmax = assess_corridor_deviation(_raw(37.51, 127.0), _brief(), max_deviation_m=50)
    assert withmax["threshold_source"] == "explicit"
