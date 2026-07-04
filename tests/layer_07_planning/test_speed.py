"""07 speed.py — flight_action(+weights) → speed_mode 이산 카테고리.

(신규, grill-me) mission_brief.weights(운용자 임무 가치 가중치)가 speed_mode를
한 단계 조정한다. 적용 범위는 MAINTAIN/ALTITUDE_CHANGE/POSTURE_ELEVATE 뿐 —
RTL/REROUTE/ALTITUDE_CHANGE_REROUTE(이미 회피 진행중, 항상 MAX)는 weights와 무관.
survival - stealth 우세가 SPEED_WEIGHT_DOMINANCE_MARGIN(0.1)을 넘으면
CAUTIOUS<NORMAL<MAX 축에서 한 단계 상/하향. weights 미지정(None) 시 기존과 동일.
"""

import pytest
from onboard.layer_07_planning.speed import compute_speed_mode


def test_rtl():
    assert compute_speed_mode("RTL") == "MAX"


def test_reroute():
    assert compute_speed_mode("REROUTE") == "MAX"


def test_altitude_change_reroute():
    assert compute_speed_mode("ALTITUDE_CHANGE_REROUTE") == "MAX"


def test_posture_elevate():
    assert compute_speed_mode("POSTURE_ELEVATE") == "CAUTIOUS"


def test_altitude_change():
    assert compute_speed_mode("ALTITUDE_CHANGE") == "NORMAL"


def test_maintain():
    assert compute_speed_mode("MAINTAIN") == "NORMAL"


def test_unknown_raises():
    with pytest.raises(KeyError):
        compute_speed_mode("INVALID_ACTION")


# ---------------------------------------------------------------------------
# 신규 — weights 조정
# ---------------------------------------------------------------------------


def test_no_weights_unchanged():
    """weights=None(기본값) → 기존 순수 룩업과 동일."""
    assert compute_speed_mode("MAINTAIN", None) == "NORMAL"


def test_survival_dominant_upgrades_maintain():
    """survival-stealth > 0.1 → MAINTAIN(NORMAL) 한 단계 상향 → MAX."""
    weights = {"stealth": 0.2, "survival": 0.5, "info_value": 0.15, "timeliness": 0.15}
    assert compute_speed_mode("MAINTAIN", weights) == "MAX"


def test_stealth_dominant_downgrades_maintain():
    """stealth-survival > 0.1 → MAINTAIN(NORMAL) 한 단계 하향 → CAUTIOUS."""
    weights = {"stealth": 0.4, "survival": 0.2, "info_value": 0.3, "timeliness": 0.1}
    assert compute_speed_mode("MAINTAIN", weights) == "CAUTIOUS"


def test_within_margin_no_adjustment():
    """차이가 임계값(0.1) 이내면 조정 없음."""
    weights = {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05}
    assert compute_speed_mode("ALTITUDE_CHANGE", weights) == "NORMAL"


def test_survival_dominant_upgrades_altitude_change():
    weights = {"stealth": 0.2, "survival": 0.5, "info_value": 0.15, "timeliness": 0.15}
    assert compute_speed_mode("ALTITUDE_CHANGE", weights) == "MAX"


def test_stealth_dominant_downgrades_posture_elevate_stays_floor():
    """POSTURE_ELEVATE(CAUTIOUS)는 이미 최하단이라 stealth 우세여도 더 못 내려감(clamp)."""
    weights = {"stealth": 0.5, "survival": 0.1, "info_value": 0.3, "timeliness": 0.1}
    assert compute_speed_mode("POSTURE_ELEVATE", weights) == "CAUTIOUS"


def test_survival_dominant_upgrades_posture_elevate_one_step():
    """POSTURE_ELEVATE(CAUTIOUS) survival 우세 → 한 단계만 상향 → NORMAL(MAX까지는 안 감)."""
    weights = {"stealth": 0.1, "survival": 0.5, "info_value": 0.3, "timeliness": 0.1}
    assert compute_speed_mode("POSTURE_ELEVATE", weights) == "NORMAL"


def test_rtl_ignores_weights():
    """RTL은 이미 회피 진행중(MAX) — weights와 무관하게 항상 MAX."""
    weights = {"stealth": 0.9, "survival": 0.05, "info_value": 0.03, "timeliness": 0.02}
    assert compute_speed_mode("RTL", weights) == "MAX"


def test_reroute_ignores_weights():
    weights = {"stealth": 0.9, "survival": 0.05, "info_value": 0.03, "timeliness": 0.02}
    assert compute_speed_mode("REROUTE", weights) == "MAX"


def test_altitude_change_reroute_ignores_weights():
    weights = {"stealth": 0.9, "survival": 0.05, "info_value": 0.03, "timeliness": 0.02}
    assert compute_speed_mode("ALTITUDE_CHANGE_REROUTE", weights) == "MAX"


def test_missing_weight_keys_default_to_zero():
    """weights dict에 stealth/survival 키가 없으면 0.0 취급."""
    assert compute_speed_mode("MAINTAIN", {}) == "NORMAL"
