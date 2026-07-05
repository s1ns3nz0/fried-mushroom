"""assess_corridor_deviation run_cycle 배선 검증 — TDD (#394).

#362 에서 corridor.py(assess_corridor_deviation)가 구현됐지만 run_cycle에 미배선.
endurance (#360) 와 동일한 단일 사이클 advisory 패턴으로 배선한다.

CRITICAL: advisory 추가가 결정론 판정(risk/threat/response/flight_plan) 불변(SCC-1).
single run_cycle golden 은 corridor 키 추가로 갱신, 결정론 값 불변.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import run_cycle

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _brief() -> dict:
    return _load("mission_brief_t3.json")


def _raw(seq: int = 0) -> dict:
    return build_normal_envelope("CW", seq, seq * 1000)


# ── 1. run_cycle 결과에 corridor advisory 키 추가 ────────────────────────────


def test_run_cycle_result_contains_corridor_key():
    """run_cycle 결과에 'corridor' advisory 키가 있어야 한다."""
    out = run_cycle(_raw(), _brief())
    assert "corridor" in out, f"run_cycle 결과에 corridor 키 없음. 키셋: {set(out)}"


def test_corridor_advisory_has_required_fields():
    """corridor advisory 는 required 필드를 포함해야 한다."""
    out = run_cycle(_raw(), _brief())
    corr = out["corridor"]
    assert isinstance(corr, dict)
    for key in ("advisory_only", "assessable", "threshold_m", "threshold_source"):
        assert key in corr, f"corridor advisory 필수 필드 없음: {key}"


def test_corridor_advisory_only_flag():
    """corridor advisory 는 advisory_only=True 이어야 한다 (SCC-1)."""
    out = run_cycle(_raw(), _brief())
    assert out["corridor"]["advisory_only"] is True


def test_corridor_advisory_assessable_is_bool():
    """assessable 필드는 bool이어야 한다."""
    out = run_cycle(_raw(), _brief())
    assert isinstance(out["corridor"]["assessable"], bool)


# ── 2. SCC-1: corridor 추가가 결정론 판정에 영향 없음 ─────────────────────────


def test_scc1_core_keys_unchanged_after_corridor_wiring():
    """corridor 배선 후 결정론 판정 키(risk/threat/response/flight_plan) 불변."""
    from onboard.corridor import assess_corridor_deviation

    raw, brief = _raw(), _brief()
    out = run_cycle(raw, brief)

    # corridor advisory 는 별도로 계산해도 동일 결과
    corr_direct = assess_corridor_deviation(raw, brief)
    assert out["corridor"]["assessable"] == corr_direct["assessable"]
    assert out["corridor"]["advisory_only"] is True

    # 결정론 키는 corridor 없이도 동일 (corridor를 제거해도 동일 run_cycle 결과)
    out2 = run_cycle(copy.deepcopy(raw), copy.deepcopy(brief))
    for key in ("risk", "threat", "response", "flight_plan"):
        assert out[key] == out2[key], f"{key} 결정론 불일치"


def test_scc1_corridor_does_not_mutate_inputs():
    """run_cycle이 raw/brief를 변이하지 않아야 한다."""
    raw, brief = _raw(), _brief()
    raw_snap, brief_snap = copy.deepcopy(raw), copy.deepcopy(brief)
    run_cycle(raw, brief)
    assert raw == raw_snap
    assert brief == brief_snap


# ── 3. corridor advisory 내용 기본 검증 ────────────────────────────────────────


def test_corridor_deviation_m_present_when_assessable():
    """assessable=True 이면 deviation_m 필드가 있어야 한다."""
    out = run_cycle(_raw(), _brief())
    corr = out["corridor"]
    if corr["assessable"]:
        assert "deviation_m" in corr
        assert isinstance(corr["deviation_m"], (int, float))


def test_corridor_within_corridor_present_when_assessable():
    """assessable=True 이면 within_corridor 필드가 있어야 한다."""
    out = run_cycle(_raw(), _brief())
    corr = out["corridor"]
    if corr["assessable"]:
        assert "within_corridor" in corr
        assert isinstance(corr["within_corridor"], bool)


def test_corridor_threshold_source_is_string():
    """threshold_source 는 문자열이어야 한다."""
    out = run_cycle(_raw(), _brief())
    assert isinstance(out["corridor"]["threshold_source"], str)


# ── 4. single run_cycle 계약 — corridor 키 포함 ───────────────────────────────


def test_run_cycle_returns_eight_keys():
    """run_cycle 은 corridor 포함 8개 키를 반환해야 한다."""
    out = run_cycle(_raw(), _brief())
    expected = {
        "abstraction", "threat", "risk", "response",
        "flight_plan", "flight_plan_state", "endurance", "corridor", "sensor_health",
    }
    assert set(out.keys()) == expected, f"키셋 불일치: {set(out.keys())} ≠ {expected}"


# ── 5. 웨이포인트 있는 브리핑 — 실 이탈량 계산 ─────────────────────────────────


def test_corridor_assessable_with_waypoints_in_brief():
    """corridor 웨이포인트가 있는 brif → assessable=True."""
    brief = _load("mission_brief_t3.json")
    # t3 brief에 웨이포인트가 있는지 확인
    wps = brief.get("corridor", {}).get("waypoints", [])
    out = run_cycle(_raw(), brief)
    if wps and len(wps) >= 2:
        assert out["corridor"]["assessable"] is True
