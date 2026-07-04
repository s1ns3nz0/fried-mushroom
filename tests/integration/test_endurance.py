"""assess_endurance — 에너지/내구 기반 RTL(bingo-fuel) 조기권고.

현재 위치·배터리·내구로 "지금 예비를 남기고 홈까지 돌아갈 수 있는가"를 계산해 RTL 권고를
낸다. 03 operational_margin 은 배터리를 밴딩만 할 뿐 **귀환 가능성(거리×에너지)**은 보지 않는다.
CRITICAL: advisory — 결정론 RTL 판정(06)을 대체하지 않고 병렬 안전지표로만.
"""

import copy
import math

import pytest

from onboard.endurance import assess_endurance


def _raw(lat=37.5, lon=127.0, battery_pct=78):
    return {
        "navigation": {"gps": {"lat": lat, "lon": lon, "alt_m": 150.0}},
        "health": {"battery": {"pct": battery_pct, "voltage_v": 25.0, "current_a": 30.0}},
    }


def _brief(bases=None, endurance_rated_s=1800):
    return {
        "drone_profile": {"endurance_rated_s": endurance_rated_s},
        "corridor": {"bases": bases if bases is not None else {
            "home": {"id": "base_home", "lat": 37.50, "lon": 127.00, "alt_m": 50}}},
    }


# ── 기본 계약 ────────────────────────────────────────────────────────────────

def test_advisory_only_and_no_mutation():
    raw, brief = _raw(), _brief()
    rs, bs = copy.deepcopy(raw), copy.deepcopy(brief)
    out = assess_endurance(raw, brief)
    assert out["advisory_only"] is True
    assert raw == rs and brief == bs


def test_sufficient_energy_near_home_continue():
    # 홈 바로 위(거리≈0), 배터리 78% → 여유 충분 → CONTINUE
    out = assess_endurance(_raw(37.50, 127.00, 78), _brief(endurance_rated_s=1800))
    assert out["assessable"] is True
    assert out["recommended_action"] == "CONTINUE"
    assert out["rtl_required"] is False
    assert out["margin_s"] > 0


def test_low_battery_far_from_home_requires_rtl():
    # 홈에서 멀리(~5km) + 배터리 12% → 귀환 에너지 부족 → RTL
    far = _raw(37.545, 127.00, 12)  # ~5km 북
    out = assess_endurance(far, _brief(endurance_rated_s=1800))
    assert out["rtl_required"] is True
    assert out["recommended_action"] == "RTL"
    assert out["margin_s"] <= 0
    assert out["dist_home_m"] > 4000


# ── 데이터 견고성 ────────────────────────────────────────────────────────────

def test_missing_gps_not_assessable():
    raw = {"health": {"battery": {"pct": 50}}}
    out = assess_endurance(raw, _brief())
    assert out["assessable"] is False
    assert out["recommended_action"] == "UNKNOWN"


def test_missing_endurance_not_assessable_but_reports_distance():
    out = assess_endurance(_raw(37.52, 127.0), _brief(endurance_rated_s=None))
    assert out["assessable"] is False
    assert out["dist_home_m"] is not None and out["dist_home_m"] > 0


# ── 베이스 선택 ──────────────────────────────────────────────────────────────

def test_base_priority_home_over_emergency():
    bases = {"emergency": {"id": "em", "lat": 37.40, "lon": 127.0},
             "home": {"id": "hm", "lat": 37.50, "lon": 127.0}}
    out = assess_endurance(_raw(37.50, 127.0), _brief(bases=bases))
    assert out["home_base_id"] == "hm"


def test_emergency_used_when_no_home():
    bases = {"emergency": {"id": "em", "lat": 37.49, "lon": 127.0},
             "alternate": {"id": "alt", "lat": 37.48, "lon": 127.0}}
    out = assess_endurance(_raw(37.50, 127.0), _brief(bases=bases))
    assert out["home_base_id"] in ("em", "alt")


# ── 계산 정확도 ──────────────────────────────────────────────────────────────

def test_haversine_distance_reasonable():
    # 0.01도 위도차 ≈ 1.11km
    out = assess_endurance(_raw(37.51, 127.0), _brief())
    assert out["dist_home_m"] == pytest.approx(1112, abs=60)


def test_reserve_and_speed_overrides_affect_margin():
    base = assess_endurance(_raw(37.52, 127.0, 40), _brief(endurance_rated_s=1800))
    slower = assess_endurance(_raw(37.52, 127.0, 40), _brief(endurance_rated_s=1800),
                              cruise_speed_mps=8.0)  # 느리면 rtl_time↑ → margin↓
    assert slower["rtl_time_s"] > base["rtl_time_s"]
    assert slower["margin_s"] < base["margin_s"]


def test_note_present():
    out = assess_endurance(_raw(), _brief())
    assert out["note"]
