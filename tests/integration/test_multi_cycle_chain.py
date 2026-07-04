"""다중 사이클 종단 통합 테스트 — quality_delta 연속 흐름 · T5 발화 검증 (#378).

#97 이 extract_qualities + --prev-qualities 로 사이클 간 quality 전달 메커니즘을 만들었지만,
2+ 사이클을 실제로 이어 돌려 quality_delta 가 사이클 N→N+1 로 흐르고 T5 가 발화하는
종단 테스트가 없었음.

커버리지:
1. 수동 루프: run_cycle × 2 + extract_qualities 수동 스레딩
2. run_cycle_chain 편의 래퍼
3. CLI --prev-qualities 2-run 시나리오
"""

from __future__ import annotations

import io
import json
import math
import pathlib
import subprocess
import sys

import pytest

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import extract_qualities, run_cycle, run_cycle_chain

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _brief() -> dict:
    return _load("mission_brief_t5.json")


def _raw_hi() -> dict:
    """camera_confidence=1.0 — 사이클 1 기준 (terrain_class quality=1.0)."""
    raw = build_normal_envelope("HI", 0, 0)
    raw["imagery"]["terrain_label"] = {
        "dominant_class": "open_field",
        "camera_confidence": 1.0,
    }
    return raw


def _raw_t5() -> dict:
    return _load("raw_t5.json")


# ── 1. 수동 루프: extract_qualities 스레딩 ─────────────────────────────────────


def test_extract_qualities_maps_channel_to_quality():
    """extract_qualities 가 채널명→quality float 맵을 반환해야 한다."""
    out = run_cycle(_raw_hi(), _brief())
    q = extract_qualities(out)
    assert isinstance(q, dict)
    assert "terrain_class" in q
    assert isinstance(q["terrain_class"], float)


def test_cycle1_terrain_class_quality_is_1():
    """Cycle 1 (_raw_hi) terrain_class quality = 1.0 이어야 한다."""
    out = run_cycle(_raw_hi(), _brief(), previous_qualities=None)
    q = extract_qualities(out)
    assert math.isclose(q["terrain_class"], 1.0, abs_tol=1e-6)


def test_cycle2_quality_delta_approx_neg035():
    """Cycle 2 terrain_class quality_delta ≈ -0.35 (1.0 → 0.65)."""
    out1 = run_cycle(_raw_hi(), _brief(), previous_qualities=None)
    q1 = extract_qualities(out1)

    out2 = run_cycle(_raw_t5(), _brief(), previous_qualities=q1)
    for ch in out2["abstraction"]["channels"]:
        if ch["channel"] == "terrain_class":
            delta = ch["quality_delta"]
            assert math.isclose(delta, -0.35, abs_tol=0.02), f"expected ≈ -0.35, got {delta}"
            return
    pytest.fail("terrain_class 채널 없음")


def test_cycle2_t5_fires_after_quality_drop():
    """Cycle 1(정상) → Cycle 2(T5 raw) — quality_delta 흐름으로 T5 발화."""
    out1 = run_cycle(_raw_hi(), _brief(), previous_qualities=None)
    q1 = extract_qualities(out1)

    out2 = run_cycle(_raw_t5(), _brief(), previous_qualities=q1)
    primary = out2["threat"].get("primary")
    assert primary is not None, "Cycle 2에서 primary 위협 없음"
    assert primary["threat_event"] == "T5", f"T5 예상, got {primary['threat_event']}"


def test_cycle1_t5_does_not_fire_without_delta():
    """Cycle 1만으로는 (previous_qualities=None) T5 발화 안 됨 — delta=0 이므로."""
    out1 = run_cycle(_raw_t5(), _brief(), previous_qualities=None)
    primary = out1["threat"].get("primary")
    t5_event = primary and primary.get("threat_event") == "T5"
    assert not t5_event, "previous_qualities 없이 T5 발화 — delta 계산 오류 가능성"


def test_qualities_are_threaded_across_all_channels():
    """extract_qualities 가 모든 채널을 담아야 한다 — 단순 terrain_class 만 아님."""
    out = run_cycle(_raw_hi(), _brief())
    q = extract_qualities(out)
    channel_names = {ch["channel"] for ch in out["abstraction"]["channels"]}
    assert channel_names == set(q.keys()), "extract_qualities 채널 누락"


# ── 2. run_cycle_chain 편의 래퍼 ──────────────────────────────────────────────


def test_run_cycle_chain_returns_two_results():
    """run_cycle_chain(2-pair) → 길이 2 리스트."""
    pairs = [(_raw_hi(), _brief()), (_raw_t5(), _brief())]
    results = run_cycle_chain(pairs)
    assert len(results) == 2


def test_run_cycle_chain_threads_qualities_automatically():
    """run_cycle_chain 이 사이클 간 qualities 를 자동 스레딩해야 한다."""
    pairs = [(_raw_hi(), _brief()), (_raw_t5(), _brief())]
    results = run_cycle_chain(pairs)

    # chain 결과 cycle 2 terrain_class delta ≈ -0.35
    for ch in results[1]["abstraction"]["channels"]:
        if ch["channel"] == "terrain_class":
            delta = ch["quality_delta"]
            assert math.isclose(delta, -0.35, abs_tol=0.02), f"chain delta {delta} ≠ -0.35"
            return
    pytest.fail("terrain_class 채널 없음 (chain 결과)")


def test_run_cycle_chain_t5_fires_in_second_cycle():
    """run_cycle_chain: 두 번째 사이클에서 T5 발화."""
    pairs = [(_raw_hi(), _brief()), (_raw_t5(), _brief())]
    results = run_cycle_chain(pairs)
    primary = results[1]["threat"].get("primary")
    assert primary is not None
    assert primary["threat_event"] == "T5"


def test_run_cycle_chain_matches_manual_loop():
    """run_cycle_chain core 판정 키 == 수동 run_cycle 결과 (결정론 보장).

    run_cycle_chain 은 cross-cycle advisory(link_loss/nav_integrity)를 추가하므로
    전체 dict 동등 비교 대신 core 판정 키만 비교한다.
    """
    pairs = [(_raw_hi(), _brief()), (_raw_t5(), _brief())]

    # 수동 루프
    r1 = run_cycle(_raw_hi(), _brief())
    r2 = run_cycle(_raw_t5(), _brief(), previous_qualities=extract_qualities(r1))

    chain = run_cycle_chain(pairs)
    for key in ("abstraction", "threat", "risk", "response", "flight_plan", "flight_plan_state"):
        assert chain[0][key] == r1[key], f"cycle 0 {key} 불일치"
        assert chain[1][key] == r2[key], f"cycle 1 {key} 불일치"


# ── 3. CLI --prev-qualities 2-run 시나리오 ─────────────────────────────────────


def test_cli_prev_qualities_threads_quality_delta(tmp_path):
    """CLI --prev-qualities: cycle 2 결과에 terrain_class quality_delta ≈ -0.35."""
    raw_hi_p = tmp_path / "raw_hi.json"
    raw_hi_p.write_text(json.dumps(_raw_hi()), encoding="utf-8")
    raw_t5_p = tmp_path / "raw_t5.json"
    raw_t5_p.write_text(json.dumps(_raw_t5()), encoding="utf-8")
    brief_p = _EXAMPLES / "mission_brief_t5.json"
    qualities_p = tmp_path / "qualities.json"

    from onboard import __main__ as cli

    # Run 1: --log で qualities 파일 생성
    buf1 = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf1
    rc1 = cli.main([str(raw_hi_p), str(brief_p)])
    sys.stdout = old_stdout
    assert rc1 == 0
    result1 = json.loads(buf1.getvalue())
    q1 = extract_qualities(result1)
    qualities_p.write_text(json.dumps(q1), encoding="utf-8")

    # Run 2: --prev-qualities
    buf2 = io.StringIO()
    sys.stdout = buf2
    rc2 = cli.main([str(raw_t5_p), str(brief_p), "--prev-qualities", str(qualities_p)])
    sys.stdout = old_stdout
    assert rc2 == 0
    result2 = json.loads(buf2.getvalue())

    for ch in result2["abstraction"]["channels"]:
        if ch["channel"] == "terrain_class":
            delta = ch["quality_delta"]
            assert math.isclose(delta, -0.35, abs_tol=0.02), f"CLI delta {delta}"
            return
    pytest.fail("terrain_class 채널 없음 (CLI run 2)")


def test_cli_prev_qualities_t5_fires(tmp_path):
    """CLI --prev-qualities: cycle 2 에서 T5 primary 발화."""
    raw_hi_p = tmp_path / "raw_hi.json"
    raw_hi_p.write_text(json.dumps(_raw_hi()), encoding="utf-8")
    raw_t5_p = tmp_path / "raw_t5.json"
    raw_t5_p.write_text(json.dumps(_raw_t5()), encoding="utf-8")
    brief_p = _EXAMPLES / "mission_brief_t5.json"
    qualities_p = tmp_path / "qualities.json"

    from onboard import __main__ as cli

    buf1 = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf1
    cli.main([str(raw_hi_p), str(brief_p)])
    sys.stdout = old_stdout
    q1 = extract_qualities(json.loads(buf1.getvalue()))
    qualities_p.write_text(json.dumps(q1), encoding="utf-8")

    buf2 = io.StringIO()
    sys.stdout = buf2
    rc2 = cli.main([str(raw_t5_p), str(brief_p), "--prev-qualities", str(qualities_p)])
    sys.stdout = old_stdout
    assert rc2 == 0
    result2 = json.loads(buf2.getvalue())

    primary = result2["threat"].get("primary")
    assert primary is not None, "CLI 2-run T5 발화 없음"
    assert primary["threat_event"] == "T5"
