"""position_consistency / link_status 3-state 분류 커버 (normal/degraded/anomaly).

fixture 는 normal·anomaly 만 훑어 degraded 분기(position_consistency:elif,
link_status:elif)가 미검증(coverage gap). 세 상태 임계를 각각 직접 친다.

position_consistency: 잔차>5 → anomaly / 그 외 sat<6 or hdop>2 → degraded / else normal.
link_status: margin<15 or loss>0.05 → anomaly / margin<20 → degraded / else normal.
"""

import copy

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction import link_status, position_consistency


def _merge(base: dict, overrides: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in overrides.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _env(overrides: dict) -> dict:
    return _merge(build_normal_envelope("S", 37.5, 127.1), overrides)


class TestPositionConsistencyStates:
    def test_normal(self) -> None:
        assert position_consistency.run(_env({}))["state"] == "normal"

    def test_degraded_high_hdop(self) -> None:
        # 잔차 정상, hdop>2.0 → degraded (elif 분기).
        out = position_consistency.run(_env({"navigation": {"gps": {"hdop": 3.0}}}))
        assert out["state"] == "degraded"

    def test_degraded_low_satellites(self) -> None:
        out = position_consistency.run(_env({"ew": {"satellite_count": 4}}))
        assert out["state"] == "degraded"

    def test_anomaly_baro_residual(self) -> None:
        # gps alt 와 baro alt 차 > 5m → anomaly.
        out = position_consistency.run(_env({"navigation": {"baro": {"alt_m": 200.0}}}))
        assert out["state"] == "anomaly"


class TestLinkStatusStates:
    def test_normal(self) -> None:
        assert link_status.run(_env({}))["state"] == "normal"

    def test_degraded_margin_band(self) -> None:
        # margin = -78 - (-95) = 17 ∈ [15,20), loss 낮음 → degraded (elif 분기).
        out = link_status.run(_env({"c2_link": {"rssi_dbm": -78, "packet_loss_rate": 0.001}}))
        assert out["state"] == "degraded"

    def test_anomaly_packet_loss(self) -> None:
        out = link_status.run(_env({"c2_link": {"packet_loss_rate": 0.2}}))
        assert out["state"] == "anomaly"

    def test_anomaly_low_margin(self) -> None:
        # margin = -90 - (-95) = 5 < 15 → anomaly.
        out = link_status.run(_env({"c2_link": {"rssi_dbm": -90}}))
        assert out["state"] == "anomaly"
