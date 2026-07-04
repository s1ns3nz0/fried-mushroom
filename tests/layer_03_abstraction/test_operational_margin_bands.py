"""operational_margin worst-case 밴드 커버 + bearing 방어분기 커버.

fixture 는 sufficient(정상) 만 훑어 limited/critical 밴드(operational_margin
higher_is_worse=False 경로)와 bearing 의 미지 카테고리 폴백이 미검증(coverage gap).
배터리 저하 상태와 잘못된 threat_category 를 직접 친다.
"""

import copy

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction import operational_margin
from onboard.layer_07_planning.bearing import compute_bearing


def _merge(base: dict, overrides: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in overrides.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _env(overrides: dict) -> dict:
    return _merge(build_normal_envelope("M", 0, 0), overrides)


class TestOperationalMarginBands:
    def test_sufficient_is_normal(self) -> None:
        out = operational_margin.run(_env({}))
        assert out["state"] == "normal"
        assert out["payload"]["overall"] == "sufficient"

    def test_battery_limited_is_degraded(self) -> None:
        # pct <= 40 → limited (higher_is_worse=False 경로).
        out = operational_margin.run(_env({"health": {"battery": {"pct": 35}}}))
        assert out["payload"]["battery_state"] == "limited"
        assert out["state"] == "degraded"

    def test_battery_critical_is_anomaly(self) -> None:
        # pct <= 20 → critical.
        out = operational_margin.run(_env({"health": {"battery": {"pct": 15}}}))
        assert out["payload"]["battery_state"] == "critical"
        assert out["payload"]["overall"] == "critical"
        assert out["state"] == "anomaly"
        assert out["payload"]["worst_factor"] == "battery"

    def test_cold_temp_limited(self) -> None:
        # temp_c <= 0 → limited (higher_is_worse=False).
        out = operational_margin.run(_env({"environment": {"temp_c": -5.0}}))
        assert out["payload"]["weather_state"] in ("limited", "critical")


class TestBearingDefensiveFallback:
    def test_unknown_category_returns_none(self) -> None:
        # None/PHYSICAL/REMOTE/NAVIGATION 외 카테고리 → (None, None) 방어 폴백.
        assert compute_bearing("UNKNOWN", 40.0, {}) == (None, None)
