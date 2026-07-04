"""step3 — 03 결정론 채널 동작 테스트."""

import json
from pathlib import Path

import pytest

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.layer_03_abstraction.run import run

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def _channel(out, name):
    return next(c for c in out["channels"] if c["channel"] == name)


def _load_raw(scenario):
    return json.loads((EXAMPLES_DIR / f"raw_{scenario}.json").read_text("utf-8"))


def test_normal_envelope_all_channels_normal():
    out = run(build_normal_envelope("s", 0, 0))
    assert len(out["channels"]) == 9
    assert all(c["state"] == "normal" for c in out["channels"])


def test_t3_acoustic_gunshot():
    ch = _channel(run(_load_raw("t3")), "acoustic_event")
    assert ch["payload"]["event_type"] == "gunshot"
    assert ch["state"] == "anomaly"


def test_t4_link_and_mission_phase():
    out = run(_load_raw("t4"))
    assert _channel(out, "link_status")["state"] in {"anomaly", "degraded"}
    assert _channel(out, "mission_phase")["payload"]["match"] is False


def test_t7_obstacle_proximity_anomaly():
    ch = _channel(run(_load_raw("t7")), "obstacle_proximity")
    assert ch["state"] == "anomaly"
    ttc = ch["payload"]["distance_m"] / ch["payload"]["closure_rate_mps"]
    assert ttc < 3.0


def test_quality_delta_from_previous_quality():
    raw = build_normal_envelope("s", 0, 0)
    baseline = _channel(run(raw), "link_status")["quality"]
    # 이전 quality 를 이번보다 0.4 높게 주면 quality_delta = -0.4.
    out = run(raw, previous_qualities={"link_status": baseline + 0.4})
    assert _channel(out, "link_status")["quality_delta"] == pytest.approx(-0.4)


def test_quality_delta_zero_when_no_previous():
    out = run(build_normal_envelope("s", 0, 0))
    assert all(c["quality_delta"] == 0.0 for c in out["channels"])
