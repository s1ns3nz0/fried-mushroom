"""infra/sim envelope 합성 — world 상태 → RawSensorEnvelope.

온보드 `build_normal_envelope`(02) 를 baseline 으로 재사용하고, world 의 위치/헤딩/
속도를 주입한다. 적 조우 시 `threat_object`(imagery.object_label)를 실어 03/04 위협
판정을 유발한다. **src/onboard 무수정** — import 재사용만.

주의: gps 와 imu 관성추정(est_lat/est_lon)을 **동일 위치**로 맞춰 position_consistency
잔차를 0 으로 둔다(월드 이동이 T1 GPS-스푸핑 오탐을 내지 않도록).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from onboard.layer_02_sensor.mock_source import build_normal_envelope  # noqa: E402


def world_to_envelope(
    sortie_id: str,
    seq: int,
    ts_ms: int,
    world_state: dict,
    *,
    threat_object: dict | None = None,
) -> dict:
    """world 상태 → RawSensorEnvelope. threat_object 지정 시 근접 위협 주입."""
    env = build_normal_envelope(sortie_id, seq, ts_ms)
    pos = world_state["pos"]
    heading = world_state.get("heading_deg", 90.0)
    speed = world_state.get("speed_mps", 17.0)

    gps = env["navigation"]["gps"]
    gps["lat"], gps["lon"], gps["alt_m"] = pos["lat"], pos["lon"], pos["alt_m"]
    imu = env["navigation"]["imu"]
    # 관성추정을 gps 와 일치시켜 잔차 0 (T1 오탐 방지).
    imu["est_lat"], imu["est_lon"] = pos["lat"], pos["lon"]
    imu["heading_deg"] = heading
    imu["est_speed_mps"] = speed
    env["navigation"]["magnetometer"]["heading_deg"] = heading
    env["navigation"]["baro"]["alt_m"] = pos["alt_m"]
    env["mission_status"]["ground_speed_mps"] = speed

    if threat_object is not None:
        env["imagery"]["object_label"] = dict(threat_object)
    return env
