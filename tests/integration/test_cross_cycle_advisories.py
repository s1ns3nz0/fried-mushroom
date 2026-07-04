"""link_loss · nav_integrity cross-cycle advisory — run_cycle_chain 배선 검증 (#389).

#372/#373 으로 standalone 모듈이 추가됐으나 파이프라인에 미배선.
이 테스트는 run_cycle_chain 결과에서 link_window/nav_window 를 추출해
assess_link_loss/assess_nav_integrity 가 의미있는 advisory 를 내는지 검증한다.

CRITICAL: advisory 추가가 결정론 판정(risk/threat/response/flight_plan) 불변(SCC-1).
single run_cycle 출력(golden) 은 변경하지 않는다.
"""

from __future__ import annotations

import copy
import json
import math
import pathlib

import pytest

from onboard.layer_02_sensor.mock_source import build_normal_envelope, build_scenario_envelope
from onboard.link_loss import assess_link_loss
from onboard.nav_integrity import assess_nav_integrity
from onboard.run import (
    extract_link_window,
    extract_nav_window,
    run_cycle,
    run_cycle_chain,
)

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _brief() -> dict:
    return _load("mission_brief_t3.json")


def _raw_normal(seq: int = 0) -> dict:
    return build_normal_envelope("CCA", seq, seq * 1000)


# ── 1. 헬퍼: extract_link_window / extract_nav_window ──────────────────────────


def test_extract_link_window_returns_list_of_channel_dicts():
    """extract_link_window 가 link_status ChannelOutput 리스트를 반환해야 한다."""
    results = run_cycle_chain([(_raw_normal(0), _brief()), (_raw_normal(1), _brief())])
    window = extract_link_window(results)
    assert isinstance(window, list)
    assert len(window) == 2
    for entry in window:
        assert entry["channel"] == "link_status"
        assert "state" in entry


def test_extract_nav_window_returns_list_of_channel_dicts():
    """extract_nav_window 가 position_consistency ChannelOutput 리스트를 반환해야 한다."""
    results = run_cycle_chain([(_raw_normal(0), _brief()), (_raw_normal(1), _brief())])
    window = extract_nav_window(results)
    assert isinstance(window, list)
    assert len(window) == 2
    for entry in window:
        assert entry["channel"] == "position_consistency"
        assert "state" in entry


def test_extract_link_window_empty_chain():
    """빈 chain → 빈 window."""
    assert extract_link_window([]) == []


def test_extract_nav_window_empty_chain():
    """빈 chain → 빈 window."""
    assert extract_nav_window([]) == []


def test_extract_link_window_length_matches_chain():
    """window 길이 == chain 길이 (1사이클 = 1 window 항목)."""
    n = 4
    pairs = [(_raw_normal(i), _brief()) for i in range(n)]
    results = run_cycle_chain(pairs)
    assert len(extract_link_window(results)) == n
    assert len(extract_nav_window(results)) == n


# ── 2. assess_link_loss — real pipeline 채널 출력 소비 ────────────────────────


def test_assess_link_loss_with_real_pipeline_normal():
    """정상 링크 3사이클 → CONTINUE 권고."""
    pairs = [(_raw_normal(i), _brief()) for i in range(3)]
    results = run_cycle_chain(pairs)
    window = extract_link_window(results)
    out = assess_link_loss(window)
    assert out["advisory_only"] is True
    assert out["assessable"] is True
    assert out["recommended_action"] == "CONTINUE"


def test_assess_link_loss_required_fields():
    """assess_link_loss 반환값 필수 필드 검증."""
    results = run_cycle_chain([(_raw_normal(0), _brief())])
    out = assess_link_loss(extract_link_window(results))
    for key in ("advisory_only", "assessable", "recommended_action", "current_state"):
        assert key in out, f"필수 필드 없음: {key}"


def test_assess_link_loss_no_mutation_scc1():
    """assess_link_loss 가 입력 window 를 변이하지 않아야 한다 (SCC-1)."""
    results = run_cycle_chain([(_raw_normal(i), _brief()) for i in range(3)])
    window = extract_link_window(results)
    snap = copy.deepcopy(window)
    assess_link_loss(window)
    assert window == snap


# ── 3. assess_nav_integrity — real pipeline 채널 출력 소비 ───────────────────


def test_assess_nav_integrity_with_real_pipeline_normal():
    """정상 항법 3사이클 → CONTINUE 권고."""
    pairs = [(_raw_normal(i), _brief()) for i in range(3)]
    results = run_cycle_chain(pairs)
    window = extract_nav_window(results)
    out = assess_nav_integrity(window)
    assert out["advisory_only"] is True
    assert out["assessable"] is True
    assert out["recommended_action"] == "CONTINUE"


def test_assess_nav_integrity_required_fields():
    """assess_nav_integrity 반환값 필수 필드 검증."""
    results = run_cycle_chain([(_raw_normal(0), _brief())])
    out = assess_nav_integrity(extract_nav_window(results))
    for key in ("advisory_only", "assessable", "recommended_action", "current_state"):
        assert key in out, f"필수 필드 없음: {key}"


def test_assess_nav_integrity_no_mutation_scc1():
    """assess_nav_integrity 가 입력 window 를 변이하지 않아야 한다 (SCC-1)."""
    results = run_cycle_chain([(_raw_normal(i), _brief()) for i in range(3)])
    window = extract_nav_window(results)
    snap = copy.deepcopy(window)
    assess_nav_integrity(window)
    assert window == snap


# ── 4. run_cycle_chain — link_loss · nav_integrity 배선 ─────────────────────


def test_chain_result_contains_link_loss_key():
    """run_cycle_chain 각 결과에 link_loss advisory 키가 있어야 한다."""
    pairs = [(_raw_normal(i), _brief()) for i in range(3)]
    results = run_cycle_chain(pairs)
    for i, r in enumerate(results):
        assert "link_loss" in r, f"cycle {i} 에 link_loss 키 없음"


def test_chain_result_contains_nav_integrity_key():
    """run_cycle_chain 각 결과에 nav_integrity advisory 키가 있어야 한다."""
    pairs = [(_raw_normal(i), _brief()) for i in range(3)]
    results = run_cycle_chain(pairs)
    for i, r in enumerate(results):
        assert "nav_integrity" in r, f"cycle {i} 에 nav_integrity 키 없음"


def test_chain_link_loss_advisory_only():
    """chain 결과 link_loss 는 advisory_only=True 이어야 한다 (SCC-1)."""
    results = run_cycle_chain([(_raw_normal(0), _brief())])
    assert results[0]["link_loss"]["advisory_only"] is True


def test_chain_nav_integrity_advisory_only():
    """chain 결과 nav_integrity 는 advisory_only=True 이어야 한다 (SCC-1)."""
    results = run_cycle_chain([(_raw_normal(0), _brief())])
    assert results[0]["nav_integrity"]["advisory_only"] is True


def test_chain_scc1_core_keys_unchanged():
    """link_loss/nav_integrity 배선 후 core 판정 키(risk/threat/response/flight_plan) 불변."""
    pairs = [(_raw_normal(i), _brief()) for i in range(2)]
    # chain 으로 실행
    chain = run_cycle_chain(pairs)
    # 단독 run_cycle 로 비교 (previous_qualities 수동 스레딩)
    from onboard.run import extract_qualities, extract_flight_plan_state
    r1_solo = run_cycle(_raw_normal(0), _brief())
    r2_solo = run_cycle(_raw_normal(1), _brief(), previous_qualities=extract_qualities(r1_solo),
                        previous_flight_plan_state=extract_flight_plan_state(r1_solo))
    for key in ("risk", "threat", "response", "flight_plan"):
        assert chain[0][key] == r1_solo[key], f"cycle 0 {key} 불일치"
        assert chain[1][key] == r2_solo[key], f"cycle 1 {key} 불일치"


def test_single_run_cycle_not_affected():
    """단일 run_cycle 결과에 link_loss/nav_integrity 키가 없어야 한다 (single-cycle 계약 불변)."""
    out = run_cycle(_raw_normal(0), _brief())
    assert "link_loss" not in out, "단일 run_cycle 에 link_loss 추가됨 — single-cycle 계약 위반"
    assert "nav_integrity" not in out, "단일 run_cycle 에 nav_integrity 추가됨 — single-cycle 계약 위반"
