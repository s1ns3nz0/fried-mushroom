"""Synthesizes a RawSensorEnvelope (02 Sensor Layer input) from a live sim
World snapshot (world.py) plus a route bbox (route.py), reusing
onboard.layer_02_sensor.mock_source's deterministic normal baseline and
scenario override values so the resulting envelope trips the same 04 Threat
Modeling thresholds that mock_source's fixtures trip.
"""
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from onboard.layer_02_sensor.mock_source import build_normal_envelope  # noqa: E402
from onboard.layer_02_sensor.schema import REQUIRED_KEYS  # noqa: E402

from vizsim import route  # noqa: E402


def _apply_t1_jamming(env: dict) -> None:
    env["navigation"]["gps"].update(
        {"lat": 37.5006, "lon": 127.0006, "hdop": 1.9, "vdop": 2.4}
    )
    env["ew"].update(
        {
            "gnss_confidence": 0.32,
            "gnss_position_jump_m": 88.0,
            "satellite_count": 5,
            "cn0_avg_db": 27.0,
            "rf_wideband_scan": {"wideband_anomaly": True},
            "rf_bearing_deg": 210.0,
        }
    )
    env["mission_status"]["flight_mode"] = "AUTO"


def _apply_t2_link_degrade(env: dict) -> None:
    env["c2_link"].update(
        {
            "encryption_mode": "NONE",
            "downgrade_detected": True,
            "checksum_fail_rate": 0.12,
            "seq_gap_count": 3,
            "packet_loss_rate": 0.08,
            "latency_ms": 260,
        }
    )
    env["mission_status"]["flight_mode"] = "AUTO"


def _apply_t3_ambush(env: dict) -> None:
    env["imagery"]["object_label"] = {
        "class": "person",
        "weapon_shape": True,
        "closing": True,
        "closure_rate_mps": 3.2,
        "bearing_deg": 142.3,
        "degraded_reason": None,
    }
    env["acoustic"].update(
        {
            "mic_waveform_ref": "buf://mic/gunshot",
            "peak_db": 118.0,
            "rise_time_ms": 1.5,
            "bandwidth_hz": 6000.0,
            "bearing_deg": 139.8,
        }
    )
    env["mission_status"]["flight_mode"] = "LOITER"
    env["mission_status"]["ground_speed_mps"] = 0.5
    env["navigation"]["imu"]["est_speed_mps"] = 0.5


def _apply_t4_capture(env: dict) -> None:
    env["imagery"]["object_label"] = {
        "class": "person",
        "weapon_shape": False,
        "closing": True,
        "closure_rate_mps": 2.5,
        "bearing_deg": 95.0,
        "degraded_reason": None,
    }
    env["mission_status"]["flight_mode"] = "AUTO"
    env["mission_status"]["ground_speed_mps"] = 1.5
    env["navigation"]["imu"].update({"est_speed_mps": 1.5, "gyro_dps": [0.0, 0.0, 25.0]})
    env["c2_link"].update({"rssi_dbm": -98, "packet_loss_rate": 0.25, "latency_ms": 320})


def _apply_t7_obstacle(env: dict) -> None:
    env["lidar"] = {"distance_m": 15.0, "closure_rate_mps": 8.0}
    env["mission_status"]["flight_mode"] = "LAND"
    env["mission_status"]["ground_speed_mps"] = 4.0
    env["environment"]["alt_agl_m"] = 20.0
    env["navigation"]["gps"]["alt_m"] = 40.0
    env["navigation"]["imu"]["est_speed_mps"] = 4.0


_EVENT_APPLIERS = {
    "T1_jamming": _apply_t1_jamming,
    "T2_link_degrade": _apply_t2_link_degrade,
    "T3_ambush": _apply_t3_ambush,
    "T4_capture": _apply_t4_capture,
    "T7_obstacle": _apply_t7_obstacle,
}


def synthesize(snapshot: dict, sortie_id: str, bbox: dict) -> dict:
    """Build a RawSensorEnvelope for one sim tick.

    `bbox` is the lat/lon bounding box dict produced by route.compute_bbox()
    (the same one used to build the route via route.generate_route) — it is
    the piece of route state needed to convert snapshot["x"]/["y"] (normalized
    plane coords) back to lat/lon via route.to_geo(x, y, bbox).
    """
    env = build_normal_envelope(sortie_id, snapshot["seq"], snapshot["ts_ms"])

    lat, lon = route.to_geo(snapshot["x"], snapshot["y"], bbox)
    env["navigation"]["gps"]["lat"] = lat
    env["navigation"]["gps"]["lon"] = lon
    # Keep the imu inertial estimate aligned with gps so world movement alone
    # leaves position_consistency's gps_imu_residual_m at 0 (no phantom T1
    # GPS-spoofing). T1_jamming's applier still trips T1 via its explicit gps
    # jump + rf anomaly.
    env["navigation"]["imu"]["est_lat"] = lat
    env["navigation"]["imu"]["est_lon"] = lon
    env["navigation"]["gps"]["alt_m"] = snapshot["alt_m"]
    env["navigation"]["baro"]["alt_m"] = snapshot["alt_m"]
    env["environment"]["alt_agl_m"] = snapshot["alt_m"] - snapshot["terrain_m"]
    env["mission_status"]["ground_speed_mps"] = snapshot["speed_mps"]
    env["health"]["battery"]["pct"] = snapshot["battery_pct"]
    env["navigation"]["imu"]["heading_deg"] = snapshot["heading_deg"]

    for event in snapshot["active_events"]:
        applier = _EVENT_APPLIERS.get(event["type"])
        if applier is not None:
            applier(env)

    return env
