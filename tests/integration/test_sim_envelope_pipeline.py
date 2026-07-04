"""sim envelope → 02..07 파이프라인 계약 라운드트립 회귀 (#170).

sim envelope.py(#154)가 합성하는 RawSensorEnvelope 가 온보드 파이프라인을 계약 위반
없이 통과하는지, 스키마에 적합한지, 결정론적인지 자동 검증한다. sim↔onboard 계약
드리프트(필드명/타입/누락)를 CI 에서 조기 포착.

**test-only** — src/onboard·infra/sim 앱 코드 무변경. sim 은 sys.path 로 임포트한다.
"""

import json
import sys
from pathlib import Path

_INFRA_SIM = Path(__file__).resolve().parents[2] / "infra" / "sim"
sys.path.insert(0, str(_INFRA_SIM))  # runner/world/envelope 임포트 (onboard 는 pythonpath=src)

from onboard.layer_02_sensor.schema import REQUIRED_KEYS, RawSensorEnvelope  # noqa: E402
from onboard.run import run_cycle  # noqa: E402

from envelope import world_to_envelope  # noqa: E402
from runner import build_scenario, run_closed_loop  # noqa: E402
from world import World  # noqa: E402

from tests.helpers.contracts import (  # noqa: E402
    assert_json_serializable,
    assert_matches_schema,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _brief():
    return json.loads((_EXAMPLES / "mission_brief_t3.json").read_text(encoding="utf-8"))


_MAINTAIN = {"flight_action": "MAINTAIN", "target_bearing_deg": None,
             "altitude_delta_m": 0, "replan_scope": "NONE", "speed_mode": "NORMAL"}


def _sim_envelopes(n, seed=42):
    """sim world 를 굴려 n개의 RawSensorEnvelope 합성(직접 envelope.py 경로)."""
    scen = build_scenario(_brief(), seed)
    world = scen["world"]
    envs = []
    for seq in range(n):
        state = world.tick(1.0, _MAINTAIN)
        envs.append(world_to_envelope("SIM", seq, seq * 1000, state))
    return envs


def test_each_sim_envelope_conforms_to_raw_schema():
    for env in _sim_envelopes(6):
        assert set(REQUIRED_KEYS).issubset(env.keys())
        assert_matches_schema(env, RawSensorEnvelope)
        assert_json_serializable(env)


def test_each_sim_envelope_passes_pipeline_to_flight_plan():
    brief = _brief()
    for env in _sim_envelopes(8):
        result = run_cycle(env, brief)  # 예외 없이 종단까지
        for layer in ("abstraction", "threat", "risk", "response", "flight_plan"):
            assert layer in result
        assert "flight_action" in result["flight_plan"]


def test_closed_loop_frames_reach_flight_plan():
    # 폐루프(되먹임)에서도 매 tick run_cycle 이 flight_plan 을 낸다.
    frames = run_closed_loop(_brief(), seed=42, ticks=10)
    assert len(frames) == 10
    for f in frames:
        assert "flight_action" in f["result"]["flight_plan"]


def test_pipeline_decisions_deterministic_same_seed():
    def decisions(seed):
        return [(f["result"]["flight_plan"]["flight_action"],
                 f["result"]["flight_plan"]["replan_scope"])
                for f in run_closed_loop(_brief(), seed=seed, ticks=10)]
    assert decisions(42) == decisions(42)


def test_threat_encounter_envelope_produces_primary():
    # 근접위협 주입 envelope → 04 primary 위협 산출(계약 흐름 확인).
    threat_obj = {"class": "person", "weapon_shape": True, "closing": True,
                  "closure_rate_mps": 3.2, "bearing_deg": 90.0, "degraded_reason": None}
    state = World(route=[{"lat": 37.5, "lon": 127.0, "alt_m": 120},
                         {"lat": 37.6, "lon": 127.1, "alt_m": 120}]).tick(1.0, _MAINTAIN)
    env = world_to_envelope("SIM", 0, 0, state, threat_object=threat_obj)
    result = run_cycle(env, _brief())
    assert (result["threat"].get("primary") or {}).get("threat_event") is not None
