"""sim envelope → 02..07 파이프라인 계약 라운드트립 회귀 (#170).

sim envelope.py(#154)가 합성하는 RawSensorEnvelope 가 온보드 파이프라인을 계약 위반
없이 통과하는지, 스키마에 적합한지, 결정론적인지 자동 검증한다. sim↔onboard 계약
드리프트(필드명/타입/누락)를 CI 에서 조기 포착.

**test-only** — src/onboard·infra/sim 앱 코드 무변경. sim 은 sys.path 로 임포트한다.
"""

import json
import sys
from pathlib import Path

# infra/sim (flat sim modules), infra/log (pipeline_feeder), src (onboard)
# on sys.path so bare imports resolve when run from tests/.
_REPO = Path(__file__).resolve().parents[2]
for _p in (_REPO / "infra" / "sim", _REPO / "infra" / "log", _REPO / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from onboard.layer_02_sensor.schema import REQUIRED_KEYS, RawSensorEnvelope  # noqa: E402
from onboard.run import run_cycle  # noqa: E402

import route  # noqa: E402
import world  # noqa: E402
from envelope import synthesize  # noqa: E402
from runner import build_scenario, run_ticks  # noqa: E402

from tests.helpers.contracts import (  # noqa: E402
    assert_json_serializable,
    assert_matches_schema,
)

_EXAMPLES = _REPO / "examples"


def _brief():
    return json.loads((_EXAMPLES / "mission_brief_t3.json").read_text(encoding="utf-8"))


def _sim_envelopes(n, seed=42):
    """sim world 를 굴려 n개의 RawSensorEnvelope 합성(직접 envelope.py 경로)."""
    brief = _brief()
    scen = build_scenario(seed, brief)
    bbox = scen["bbox"]
    w = world.World(scen["route"], scen["events"], brief, enemies=scen["all_enemies"])
    sortie_id = brief.get("sortie_id", "SIM")
    envs = []
    for _ in range(n):
        w.tick(1.0)
        envs.append(synthesize(w.snapshot(), sortie_id, bbox))
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
    frames = run_ticks(42, _brief(), 10, 1.0)
    assert len(frames) == 10
    for f in frames:
        assert "flight_action" in f["result"]["flight_plan"]


def test_pipeline_decisions_deterministic_same_seed():
    def decisions(seed):
        return [(f["result"]["flight_plan"]["flight_action"],
                 f["result"]["flight_plan"]["replan_scope"])
                for f in run_ticks(seed, _brief(), 10, 1.0)]
    assert decisions(42) == decisions(42)


def test_threat_encounter_envelope_produces_primary():
    # 근접위협 주입 envelope → 04 primary 위협 산출(계약 흐름 확인).
    # T3_ambush active event 를 실은 snapshot 을 synthesize 하면 envelope 의
    # object_label(person/weapon_shape/closing)이 채워져 04 primary 가 나온다.
    brief = _brief()
    bbox = route.compute_bbox(brief["corridor"]["waypoints"])
    rt = route.generate_route(brief)
    w = world.World(rt, [], brief)
    w.tick(1.0)
    snap = w.snapshot()
    snap["active_events"] = [{"type": "T3_ambush", "s_start": snap["s"],
                              "s_end": snap["s"], "params": {}}]
    env = synthesize(snap, "SIM", bbox)
    result = run_cycle(env, brief)
    assert (result["threat"].get("primary") or {}).get("threat_event") is not None
