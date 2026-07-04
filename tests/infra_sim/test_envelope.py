"""infra/sim envelope.py — world state → RawSensorEnvelope 합성. TDD.

온보드 build_normal_envelope 재사용 + world 위치/헤딩/속도 주입. 적 조우 시
object_label 로 위협 주입. gps/imu est 를 동일 위치로 맞춰 T1 오탐 방지.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "infra" / "sim"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from envelope import world_to_envelope  # noqa: E402
from onboard.layer_02_sensor.schema import REQUIRED_KEYS  # noqa: E402
from onboard.layer_03_abstraction.run import run as run03  # noqa: E402


def _state(lat=37.5, lon=127.0, alt=120.0, heading=90.0, speed=17.0, phase="TRANSIT"):
    return {"pos": {"lat": lat, "lon": lon, "alt_m": alt}, "heading_deg": heading,
            "speed_mps": speed, "phase": phase}


def test_envelope_schema_valid():
    env = world_to_envelope("SIM", 0, 0, _state())
    assert set(REQUIRED_KEYS).issubset(env.keys())


def test_world_pos_heading_speed_injected():
    env = world_to_envelope("SIM", 3, 3000, _state(lat=37.55, lon=127.05, heading=210.0, speed=8.0))
    assert env["navigation"]["gps"]["lat"] == 37.55
    assert env["navigation"]["gps"]["lon"] == 127.05
    assert env["navigation"]["imu"]["heading_deg"] == 210.0
    assert env["mission_status"]["ground_speed_mps"] == 8.0
    assert env["seq"] == 3 and env["ts_ms"] == 3000


def test_gps_imu_consistent_no_false_t1():
    # gps 와 imu est 를 동일 위치로 → position_consistency anomaly 없음(T1 오탐 방지).
    env = world_to_envelope("SIM", 0, 0, _state(lat=37.6, lon=127.1))
    ch = next(c for c in run03(env)["channels"] if c["channel"] == "position_consistency")
    assert ch["state"] == "normal"


def test_threat_object_triggers_proximity_anomaly():
    obj = {"class": "person", "weapon_shape": True, "closing": True,
           "closure_rate_mps": 3.0, "bearing_deg": 90.0, "degraded_reason": None}
    env = world_to_envelope("SIM", 0, 0, _state(), threat_object=obj)
    ch = next(c for c in run03(env)["channels"] if c["channel"] == "proximity_object")
    assert ch["state"] == "anomaly"
