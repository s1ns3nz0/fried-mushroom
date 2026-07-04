"""온보드 파이프라인 오케스트레이터 (하니스).

레이어 02~07 을 순서대로 체이닝한다. 각 레이어는
`src/onboard/layer_XX_*/run.py` 의 `run(input, *, mission_brief, previous_state) -> dict`
순수 함수 (ADR-001). 아직 미구현인 레이어는 passthrough 로 대체한다 (try-import 배선).

파이프라인은 순수(IO 없음). 파일 read / JSONL 로그 / stdout 은 main() 이 담당.
"""

from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import sys

CHAIN = ("02", "03", "04", "05", "06", "07")

_LAYER_MODULE = {
    "02": "onboard.layer_02_sensor.run",
    "03": "onboard.layer_03_abstraction.run",
    "04": "onboard.layer_04_threat.run",
    "05": "onboard.layer_05_risk.run",
    "06": "onboard.layer_06_response.run",
    "07": "onboard.layer_07_planning.run",
}


def run_pipeline(scenario: dict) -> list[dict]:
    """scenario({mission_brief, sensor_frames[]}) 를 사이클마다 실행.

    반환: [{"cycle": i, "layers": {"02": out, ..., "07": out}}, ...]
    """
    brief = scenario["mission_brief"]
    frames = scenario["sensor_frames"]

    resolved = {layer: _resolve(layer) for layer in CHAIN}

    results: list[dict] = []
    previous_state: dict = {}
    for i, frame in enumerate(frames):
        data = frame
        layers: dict = {}
        for layer in CHAIN:
            data = resolved[layer](data, mission_brief=brief, previous_state=previous_state)
            layers[layer] = data
        results.append({"cycle": i, "layers": layers})
        previous_state = layers

    return results


def main(argv: list[str] | None = None) -> int:
    """CLI: scenario JSON 을 읽어 파이프라인 실행, JSONL 로그 append, 최종 07 출력."""
    parser = argparse.ArgumentParser(prog="onboard.run", description="D4D 온보드 파이프라인 실행")
    parser.add_argument("scenario", help="scenario JSON ({mission_brief, sensor_frames[]})")
    parser.add_argument("--log", help="사이클×레이어 출력을 append 할 JSONL 경로")
    ns = parser.parse_args(argv)

    scenario = json.loads(pathlib.Path(ns.scenario).read_text(encoding="utf-8"))
    results = run_pipeline(scenario)

    if ns.log:
        with open(ns.log, "w", encoding="utf-8") as fh:
            for cycle in results:
                for layer, output in cycle["layers"].items():
                    record = {"cycle": cycle["cycle"], "layer": layer, "output": output}
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    final = results[-1]["layers"]["07"] if results else {}
    print(json.dumps(final, ensure_ascii=False))
    return 0


def _resolve(layer: str):
    """레이어 run() 을 반환. layer_XX/run.py 의 run() 이 있으면 그것을, 없으면 passthrough."""
    try:
        module = importlib.import_module(_LAYER_MODULE[layer])
    except ModuleNotFoundError:
        module = None
    fn = getattr(module, "run", None)
    if callable(fn):
        return fn

    def passthrough(data, *, mission_brief, previous_state):
        return _STUB_OUTPUT[layer](data)

    return passthrough


# 미구현 레이어용 최소 스키마 적합 고정 출력.
# 02 는 raw sensor 를 그대로 흘려보낸다(스키마 없음). 03~07 은 각 OutputSchema 의 최소 인스턴스.
_STUB_OUTPUT = {
    "02": lambda data: data,
    "03": lambda data: {
        "schema_version": "0.0-stub",
        "id": "stub",
        "ts": 0,
        "channels": [],
    },
    "04": lambda data: {
        "declared_phase": "unknown",
        "mission_phase_confidence": 0.0,
        "candidates": [],
        "primary": None,
        "background_exposure_score": 0.0,
    },
    "05": lambda data: {
        "candidates": [],
    },
    "06": lambda data: {
        "primary_threat_event": None,
        "rac": "Low",
        "kill_chain_stage": None,
        "threat_category": None,
        "flight_action": "CONTINUE",
        "comms_level": "NORMAL",
        "payload_action": [],
        "nav_mode": None,
        "special_action": None,
        "secondary_threats": [],
        "ai_reliability": "normal",
    },
    "07": lambda data: {
        "flight_action": "CONTINUE",
        "target_bearing_deg": None,
        "altitude_delta_m": 0,
        "replan_scope": "NONE",
        "reroute_anchor": None,
    },
}


if __name__ == "__main__":
    sys.exit(main())
