"""run_cycle_chain — previous_qualities/flight_plan_state 사이클 간 자동 스레딩 (#133 task2).

수동 --prev-qualities 주입 없이 N 사이클 연속 실행 시, 직전 사이클 채널 quality 를
자동으로 다음 사이클 previous_qualities 로 스레딩한다. quality_delta 기반 T5(광학 교란)
탐지가 연속 스트림에서 자연 발화하는지 검증한다.
"""

import json
from pathlib import Path

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import run_cycle_chain

_EX = Path(__file__).resolve().parents[1] / "examples"
if not _EX.exists():
    _EX = Path(__file__).resolve().parents[2] / "examples"


def _brief():
    return json.loads((_EX / "mission_brief_t5.json").read_text(encoding="utf-8"))


def _raw_terrain(conf):
    raw = build_normal_envelope("stream", 0, 0)
    raw["imagery"]["terrain_label"] = {"dominant_class": "open_field", "camera_confidence": conf}
    return raw


def _terrain(result):
    return next(c for c in result["abstraction"]["channels"] if c["channel"] == "terrain_class")


def test_chain_returns_result_per_cycle():
    brief = _brief()
    pairs = [(_raw_terrain(1.0), brief), (_raw_terrain(0.9), brief), (_raw_terrain(0.8), brief)]
    results = run_cycle_chain(pairs)
    assert len(results) == 3
    assert all("abstraction" in r and "threat" in r for r in results)


def test_first_cycle_has_zero_delta():
    brief = _brief()
    results = run_cycle_chain([(_raw_terrain(0.65), brief)])
    # 직전 없음 → delta 0.0 (T5 미탐).
    assert _terrain(results[0])["quality_delta"] == 0.0


def test_quality_auto_threaded_across_cycles():
    # 수동 주입 없이: cycle1 terrain q=1.0 → cycle2 q=0.65 → 자동 스레딩 delta=-0.35.
    brief = _brief()
    results = run_cycle_chain([(_raw_terrain(1.0), brief), (_raw_terrain(0.65), brief)])
    assert _terrain(results[0])["quality_delta"] == 0.0
    assert _terrain(results[1])["quality"] == 0.65
    assert _terrain(results[1])["quality_delta"] == -0.35


def test_t5_fires_naturally_in_continuous_stream():
    # 연속 스트림에서 품질 급락 시 04 primary=T5 자연 발화 (수동 주입 없이).
    brief = _brief()
    results = run_cycle_chain([(_raw_terrain(1.0), brief), (_raw_terrain(0.65), brief)])
    assert results[0]["threat"].get("primary") is None  # prime: T5 아님
    primary = results[1]["threat"].get("primary")
    assert primary is not None and primary["threat_event"] == "T5"


def test_gradual_drop_does_not_fire_t5():
    # 완만한 하락(1.0→0.9→0.8, 사이클당 -0.1)은 T5 미탐(연속에서도 거짓양성 방지).
    brief = _brief()
    results = run_cycle_chain([(_raw_terrain(1.0), brief), (_raw_terrain(0.9), brief), (_raw_terrain(0.8), brief)])
    for r in results:
        p = r["threat"].get("primary")
        assert p is None or p["threat_event"] != "T5"


def test_chain_threads_flight_plan_state_continuity():
    # flight_plan_state(07 디바운스)도 사이클 간 자동 스레딩 → 결과에 존재.
    brief = _brief()
    results = run_cycle_chain([(_raw_terrain(1.0), brief), (_raw_terrain(1.0), brief)])
    assert all("flight_plan_state" in r for r in results)
