"""link_status — 🔵 결정론. C2 라디오 RSSI/노이즈플로어/패킷손실 판독."""

from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

_MARGIN_ANOMALY_DB = 15.0
_MARGIN_DEGRADED_DB = 20.0
_PACKET_LOSS_ANOMALY = 0.05


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    c2 = raw["c2_link"]
    rssi_dbm, noise_floor_dbm = c2["rssi_dbm"], c2["noise_floor_dbm"]
    packet_loss_rate = c2["packet_loss_rate"]
    margin = rssi_dbm - noise_floor_dbm

    if margin < _MARGIN_ANOMALY_DB or packet_loss_rate > _PACKET_LOSS_ANOMALY:
        state = "anomaly"
    elif margin < _MARGIN_DEGRADED_DB:
        state = "degraded"
    else:
        state = "normal"

    # quality: 패킷손실·링크마진 기반 (MVP proxy).
    quality = 1.0 - packet_loss_rate * 2.0 - max(0.0, _MARGIN_DEGRADED_DB - margin) * 0.02

    payload = {
        "rssi_dbm": rssi_dbm,
        "noise_floor_dbm": noise_floor_dbm,
        "freq_mhz": c2["freq_mhz"],
        "packet_loss_rate": packet_loss_rate,
        "latency_ms": c2["latency_ms"],
    }
    return make_output("link_status", state, quality, payload, previous_quality)
