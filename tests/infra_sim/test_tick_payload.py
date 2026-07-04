"""Tests for runner.build_tick_payload (/tick payload assembly).

Covers:
  1. Payload built from a real run_ticks record: 11 abstraction channels
     pass through, decision block has all keys, JSON-serializable, and the
     existing top-level flight_action/rac keys are kept.
  2. A cycle with no primary threat -> decision["threat"]["primary"] is None.
  3. The debug block carries 5 per-layer input/output entries chained
     raw -> abstraction -> threat -> risk -> response -> flight_plan.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Mirror runner.py's sys.path setup: repo src/ (onboard), infra/log/
# (pipeline_feeder) and infra/sim/ (flat sim modules) importable regardless
# of how this test is invoked.
_SIM_DIR = Path(__file__).resolve().parent
_INFRA_DIR = _SIM_DIR.parent
_REPO = _INFRA_DIR.parent
_SRC = _REPO / "src"

for _path in (_REPO / "infra" / "sim", _REPO / "infra" / "log", _SRC):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import runner  # noqa: E402

BRIEF_PATH = _INFRA_DIR.parent / "examples" / "mission_brief_t3.json"


def _load_brief() -> dict:
    return json.loads(BRIEF_PATH.read_text(encoding="utf-8"))


def _single_record() -> dict:
    brief = _load_brief()
    return runner.run_ticks(42, brief, 1, 1.0)[0]


def test_build_tick_payload_shape_and_serializable():
    record = _single_record()
    payload = runner.build_tick_payload(record["snapshot"], record["result"])

    # Existing top-level tick fields are kept.
    assert payload["seq"] == record["snapshot"]["seq"]
    assert payload["flight_action"] == record["result"]["response"]["flight_action"]
    assert payload["rac"] == record["result"]["response"]["rac"]

    assert len(payload["channels"]) == 11

    decision = payload["decision"]
    assert set(decision.keys()) == {"threat", "risk", "response", "flight_plan"}
    assert set(decision["response"].keys()) == {
        "flight_action",
        "comms_level",
        "rac",
        "threat_category",
    }
    assert set(decision["flight_plan"].keys()) == {
        "flight_action",
        "target_bearing_deg",
        "altitude_delta_m",
        "replan_scope",
        "speed_mode",
    }
    if decision["risk"] is not None:
        assert set(decision["risk"].keys()) == {"rac", "compound_urgency_score"}

    json.dumps(payload)


def test_debug_block_has_five_layers_with_chained_io():
    record = _single_record()
    raw = {"schema_version": "raw-mock"}
    payload = runner.build_tick_payload(
        record["snapshot"], record["result"], raw=raw, brief=_load_brief()
    )

    layers = payload["debug"]["layers"]
    assert len(layers) == 5
    for entry in layers:
        assert set(entry.keys()) == {"layer", "input", "output"}

    result = record["result"]
    assert layers[0]["input"] is raw
    assert layers[0]["output"] == result["abstraction"]
    assert layers[1]["input"] == result["abstraction"]
    assert layers[1]["output"] == result["threat"]
    assert layers[2]["input"] == result["threat"]
    assert layers[2]["output"] == result["risk"]
    assert layers[3]["input"] == result["risk"]
    assert layers[3]["output"] == result["response"]
    assert layers[4]["input"] == result["response"]
    assert layers[4]["output"] == result["flight_plan"]

    json.dumps(payload)


def test_no_primary_threat_yields_none_primary():
    record = _single_record()
    result = {
        **record["result"],
        "threat": {**record["result"]["threat"], "primary": None},
    }
    payload = runner.build_tick_payload(record["snapshot"], result)
    assert payload["decision"]["threat"]["primary"] is None
