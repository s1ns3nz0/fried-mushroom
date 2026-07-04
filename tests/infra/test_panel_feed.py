"""infra/log/panel_feed 어댑터 단위 테스트 (순수 함수, 네트워크 없음).

실 파이프라인 출력(02 raw / 03 abstraction)을 대시보드 tick/signal 계약으로
변환하는지 검증한다. panel_feed 는 표준 라이브러리만 쓰므로 httpx/fastapi 불필요.

이 테스트는 루트 CI(`python -m pytest`, testpaths=["tests"])가 수집하도록 tests/
아래에 둔다 — infra/log 의 panel_feed 는 sys.path 로 임포트한다(파이프라인 무변경).
"""

from pathlib import Path

from onboard.layer_02_sensor.mock_source import (  # noqa: E402
    build_normal_envelope,
    build_scenario_envelope,
)
from onboard.layer_03_abstraction.run import run as run03  # noqa: E402
from onboard.run import run_cycle  # noqa: E402

from panel_feed import (  # noqa: E402
    SIGNAL_CHANNEL_ORDER,
    abstraction_to_signals,
    cycle_to_panel_messages,
    envelope_to_tick,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _channel(msgs, name):
    return next(m for m in msgs if m["channel"] == name)


# --- #106 abstraction.channels → signal ---


def test_signals_one_message_per_real_channel():
    abstraction = run03(build_normal_envelope("s", 0, 0))
    msgs = abstraction_to_signals("CID-1", 7, abstraction)
    assert len(msgs) == len(abstraction["channels"]) == 11
    assert {m["channel"] for m in msgs} == set(SIGNAL_CHANNEL_ORDER)


def test_signal_message_shape_and_passthrough():
    abstraction = run03(build_normal_envelope("s", 0, 0))
    msg = abstraction_to_signals("CID-1", 7, abstraction)[0]
    assert msg["type"] == "signal"
    assert msg["correlation_id"] == "CID-1"
    assert msg["seq"] == 7
    for key in ("channel", "state", "quality", "quality_delta", "payload"):
        assert key in msg
    src = abstraction["channels"][0]
    assert msg["channel"] == src["channel"]
    assert msg["state"] == src["state"]
    assert msg["quality"] == src["quality"]


def test_signal_reflects_t5_quality_delta_drop():
    raw = build_normal_envelope("s", 0, 0)
    raw["imagery"]["terrain_label"] = {"dominant_class": "open_field", "camera_confidence": 0.65}
    abstraction = run03(raw, previous_qualities={"terrain_class": 1.0})
    tc = _channel(abstraction_to_signals("CID-1", 1, abstraction), "terrain_class")
    assert tc["quality"] == 0.65
    assert tc["quality_delta"] < -0.3


def test_signals_skip_malformed_channels():
    abstraction = {"channels": [{"channel": "x", "state": "normal", "quality": 0.9},
                                 "not-a-dict", {"no_channel_key": True}]}
    msgs = abstraction_to_signals("CID", 0, abstraction)
    assert [m["channel"] for m in msgs] == ["x"]


def test_signals_empty_abstraction_yields_no_messages():
    assert abstraction_to_signals("CID", 0, {"channels": []}) == []
    assert abstraction_to_signals("CID", 0, {}) == []


# --- #107 RawSensorEnvelope → tick(platform_state) ---


def test_tick_message_shape():
    tick = envelope_to_tick("CID-2", 3, build_normal_envelope("s", 0, 0))
    assert tick["type"] == "tick"
    assert tick["correlation_id"] == "CID-2"
    assert tick["seq"] == 3
    ps = tick["platform_state"]
    for block in ("attitude", "angular_rates", "battery", "gps", "baro",
                  "speed", "esc", "link", "nav"):
        assert block in ps, f"telemetry 블록 누락: {block}"


def test_tick_carries_real_sensor_values():
    ps = envelope_to_tick("CID", 0, build_normal_envelope("s", 0, 0))["platform_state"]
    assert ps["battery"]["pct"] == 78
    assert ps["battery"]["voltage_v"] == 25.0
    assert ps["gps"]["satellites"] == 12
    assert ps["gps"]["hdop"] == 0.8
    assert ps["link"]["rssi_dbm"] == -60
    assert ps["speed"]["ground_mps"] == 18.0
    assert ps["esc"]["motor_rpm"] == [8200, 8150, 8190, 8175]


def test_tick_attitude_source_defined_and_derived():
    ps = envelope_to_tick("CID", 0, build_normal_envelope("s", 0, 0))["platform_state"]
    att = ps["attitude"]
    assert att["roll_deg"] == 0.0
    assert att["pitch_deg"] == 0.0
    assert att["yaw_deg"] == 90.0
    assert "source" in att
    assert ps["angular_rates"] == {"p_dps": 0.0, "q_dps": 0.0, "r_dps": 0.0}


def test_tick_roll_pitch_from_tilted_accel():
    raw = build_normal_envelope("s", 0, 0)
    raw["navigation"]["imu"]["accel_ms2"] = [0.0, 4.9, 8.5]
    att = envelope_to_tick("CID", 0, raw)["platform_state"]["attitude"]
    assert att["roll_deg"] > 0
    assert att["pitch_deg"] == 0.0


def test_tick_t1_gps_degradation_reflected():
    ps = envelope_to_tick("CID", 0, build_scenario_envelope("t1", 0, 0))["platform_state"]
    assert ps["gps"]["satellites"] == 5
    assert ps["gps"]["hdop"] == 1.9
    assert ps["gps"]["fix_confidence"] == 0.32


# --- 통합 헬퍼: 한 사이클 → tick + signals ---


def _load_example(name):
    import json
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def test_cycle_to_panel_messages_tick_first_then_signals():
    raw = _load_example("raw_t3.json")
    brief = _load_example("mission_brief_t3.json")
    result = run_cycle(raw, brief)
    msgs = cycle_to_panel_messages("CID-9", 4, raw, result)
    assert msgs[0]["type"] == "tick"
    assert all(m["type"] == "signal" for m in msgs[1:])
    assert len(msgs) == 1 + len(result["abstraction"]["channels"])
    assert all(m["seq"] == 4 and m["correlation_id"] == "CID-9" for m in msgs)
