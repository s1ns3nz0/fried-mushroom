"""Tests for envelope.py — synthesizes a RawSensorEnvelope (02 Sensor Layer
input) from a world.World snapshot + route bbox, reusing
onboard.layer_02_sensor.mock_source's deterministic normal/scenario values so
04 Threat Modeling thresholds trip exactly as mock_source's fixtures do.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra"))       # vizsim 패키지
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "log"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from vizsim import envelope  # noqa: E402
from vizsim import route  # noqa: E402
from vizsim import world  # noqa: E402

BRIEF_PATH = Path(__file__).resolve().parents[2] / "examples" / "mission_brief_t3.json"


def _load_t3_brief():
    with open(BRIEF_PATH) as f:
        return json.load(f)


def _make_world(events_list):
    brief = _load_t3_brief()
    rt = route.generate_route(brief)
    return world.World(rt, events_list, brief), brief, rt


def test_synthesize_no_active_event_has_all_required_keys_and_geo_position():
    w, brief, rt = _make_world([])
    bbox = route.compute_bbox(brief["corridor"]["waypoints"])
    snap = w.snapshot()

    env = envelope.synthesize(snap, "sortie-test", bbox)

    for key in envelope.REQUIRED_KEYS:
        assert key in env

    expected_lat, expected_lon = route.to_geo(snap["x"], snap["y"], bbox)
    assert env["navigation"]["gps"]["lat"] == expected_lat
    assert env["navigation"]["gps"]["lon"] == expected_lon
    assert env["imagery"]["object_label"]["class"] == "none"


def test_synthesize_no_active_event_carries_world_state():
    w, brief, rt = _make_world([])
    bbox = route.compute_bbox(brief["corridor"]["waypoints"])
    w.tick(1.0)
    snap = w.snapshot()

    env = envelope.synthesize(snap, "sortie-test", bbox)

    assert env["navigation"]["gps"]["alt_m"] == snap["alt_m"]
    assert env["navigation"]["baro"]["alt_m"] == snap["alt_m"]
    assert env["environment"]["alt_agl_m"] == snap["alt_m"] - snap["terrain_m"]
    assert env["mission_status"]["ground_speed_mps"] == snap["speed_mps"]
    assert env["health"]["battery"]["pct"] == snap["battery_pct"]
    assert env["navigation"]["imu"]["heading_deg"] == snap["heading_deg"]


def test_synthesize_t3_ambush_active_trips_imagery_and_acoustic_thresholds():
    total_s = 1.0
    t3_event = {
        "type": "T3_ambush",
        "s_start": 0.0,
        "s_end": total_s,
        "params": {"bearing_deg": 142.3, "intensity": 1.0},
    }
    w, brief, rt = _make_world([t3_event])
    bbox = route.compute_bbox(brief["corridor"]["waypoints"])
    snap = w.snapshot()
    assert any(e["type"] == "T3_ambush" for e in snap["active_events"])

    env = envelope.synthesize(snap, "sortie-test", bbox)

    assert env["imagery"]["object_label"]["class"] == "person"
    assert env["imagery"]["object_label"]["weapon_shape"] is True
    assert env["acoustic"]["peak_db"] == 118.0
    assert env["acoustic"]["rise_time_ms"] == 1.5
