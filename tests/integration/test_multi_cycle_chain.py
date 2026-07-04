"""다중 사이클 종단 — quality_delta 연속 흐름 → T5 발화 (#378).

#97 이 사이클 간 quality 전달(extract_qualities/--prev-qualities)을 만들었으나, 2+ 사이클을
실제로 이어 돌려 quality_delta 가 N→N+1 로 흐르고 T5(레이저/광학 교란: terrain_class
quality 급락)가 2번째 사이클에서 발화하는 종단 통합 테스트가 없었다. 이를 잠근다.

시나리오: cycle0 = pristine terrain(camera_confidence 1.0) → terrain quality 1.0.
cycle1 = raw_t5(camera_confidence 0.65) → terrain quality 0.65 → quality_delta -0.35
(≤ QUALITY_DELTA_DROP_THRESHOLD -0.3) → T5 primary 발화.
"""

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

from onboard.run import extract_qualities, run_cycle, run_cycle_chain

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_SRC = str(Path(__file__).resolve().parents[2] / "src")


def _load(name):
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _pristine_and_degraded():
    """cycle0(정상 terrain 고품질) + cycle1(raw_t5 저하) 쌍."""
    brief = _load("mission_brief_t5.json")
    degraded = _load("raw_t5.json")  # terrain camera_confidence 0.65
    pristine = copy.deepcopy(degraded)
    pristine["imagery"].setdefault("terrain_label", {})["camera_confidence"] = 1.0
    return pristine, degraded, brief


def _terrain(result):
    return next(c for c in result["abstraction"]["channels"] if c["channel"] == "terrain_class")


def _primary(result):
    return (result["threat"].get("primary") or {}).get("threat_event")


def test_run_cycle_chain_t5_fires_second_cycle():
    pristine, degraded, brief = _pristine_and_degraded()
    results = run_cycle_chain([(pristine, brief), (degraded, brief)])
    assert len(results) == 2
    # cycle0: 고품질, 위협 없음.
    assert _terrain(results[0])["quality"] == 1.0
    assert _primary(results[0]) != "T5"
    # cycle1: quality_delta ≈ -0.35 → T5 primary 발화.
    tc1 = _terrain(results[1])
    assert tc1["quality_delta"] == -0.35
    assert _primary(results[1]) == "T5"


def test_manual_two_run_extract_qualities_threading():
    # run_cycle_chain 없이 수동 2회 + extract_qualities 스레딩도 동일 결과(메커니즘 잠금).
    pristine, degraded, brief = _pristine_and_degraded()
    r0 = run_cycle(pristine, brief)
    q0 = extract_qualities(r0)
    assert q0["terrain_class"] == 1.0
    r1 = run_cycle(degraded, brief, previous_qualities=q0)
    assert _terrain(r1)["quality_delta"] == -0.35
    assert _primary(r1) == "T5"


def test_quality_delta_zero_without_priming():
    # 프라이밍 없이 단일 사이클(previous 없음)이면 delta 0 → T5 미발화(대조군).
    _, degraded, brief = _pristine_and_degraded()
    r = run_cycle(degraded, brief)
    assert _terrain(r)["quality_delta"] == 0.0
    assert _primary(r) != "T5"


def _cli(args, tmp_path, prev_qualities=None):
    cmd = [sys.executable, "-m", "onboard", *args]
    if prev_qualities is not None:
        qf = tmp_path / "prevq.json"
        qf.write_text(json.dumps(prev_qualities), encoding="utf-8")
        cmd += ["--prev-qualities", str(qf)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": _SRC})
    assert r.returncode == 0, r.stderr[:400]
    return json.loads(r.stdout)


def test_cli_prev_qualities_two_run_t5(tmp_path):
    pristine, degraded, brief = _pristine_and_degraded()
    pf = tmp_path / "raw_pristine.json"
    pf.write_text(json.dumps(pristine), encoding="utf-8")
    df = tmp_path / "raw_degraded.json"
    df.write_text(json.dumps(degraded), encoding="utf-8")
    bf = tmp_path / "brief.json"
    bf.write_text(json.dumps(brief), encoding="utf-8")

    # cycle0: pristine → qualities 추출.
    r0 = _cli([str(pf), str(bf)], tmp_path)
    q0 = {c["channel"]: c["quality"] for c in r0["abstraction"]["channels"]}
    assert q0["terrain_class"] == 1.0
    # cycle1: degraded + --prev-qualities → T5.
    r1 = _cli([str(df), str(bf)], tmp_path, prev_qualities=q0)
    tc1 = next(c for c in r1["abstraction"]["channels"] if c["channel"] == "terrain_class")
    assert tc1["quality_delta"] == -0.35
    assert (r1["threat"].get("primary") or {}).get("threat_event") == "T5"
