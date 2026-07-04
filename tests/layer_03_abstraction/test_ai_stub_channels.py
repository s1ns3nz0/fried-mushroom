"""step4 — AI stub 채널(proximity_object, terrain_class) 테스트."""

import json
from pathlib import Path

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction.run import run

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def _channel(out, name):
    return next(c for c in out["channels"] if c["channel"] == name)


def _load_raw(scenario):
    return json.loads((EXAMPLES_DIR / f"raw_{scenario}.json").read_text("utf-8"))


def test_t3_proximity_weapon_anomaly():
    ch = _channel(run(_load_raw("t3")), "proximity_object")
    assert ch["payload"]["weapon_shape"] is True
    assert ch["state"] == "anomaly"


def test_t4_proximity_person_closing_anomaly():
    ch = _channel(run(_load_raw("t4")), "proximity_object")
    assert ch["payload"]["class"] == "person"
    assert ch["payload"]["closing"] is True
    assert ch["state"] == "anomaly"


def test_t7_terrain_defined_and_proximity_normal():
    out = run(_load_raw("t7"))
    terrain = _channel(out, "terrain_class")
    assert terrain["payload"]["dominant_class"]
    assert isinstance(terrain["payload"]["exposure_score"], (int, float))
    # T7 은 지형이 위협이지 근접객체가 아님.
    assert _channel(out, "proximity_object")["state"] == "normal"


def test_terrain_class_always_normal():
    for scenario in ("t3", "t4", "t7"):
        assert _channel(run(_load_raw(scenario)), "terrain_class")["state"] == "normal"
    assert _channel(run(build_normal_envelope("s", 0, 0)), "terrain_class")["state"] == "normal"
