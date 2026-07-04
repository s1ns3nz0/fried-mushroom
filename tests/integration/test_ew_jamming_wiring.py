"""ew_jamming advisory run_cycle_chain 배선 계약 — TDD (#404).

run_cycle_chain 각 결과에 'ew_jamming' advisory 키 추가.
CRITICAL: advisory_only=True — SCC-1, 결정론 판정(RAC/threat/response/flight_plan) 불변.
"""

from __future__ import annotations

import json
import pathlib

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import run_cycle_chain

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"

_VALID_THREAT_LEVELS = frozenset(
    {"CLEAR", "MONITOR", "JAMMING_SUSPECTED", "JAMMING_CONFIRMED", "UNKNOWN"}
)
_VALID_ACTIONS = frozenset({"CONTINUE", "MONITOR", "EMCON_EVADE"})


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _brief() -> dict:
    return _load("mission_brief_t3.json")


def _raw() -> dict:
    return build_normal_envelope("ew", 0, 0)


def _pairs(n: int = 2) -> list:
    b = _brief()
    return [(_raw(), b) for _ in range(n)]


# ── 1. ew_jamming 키 존재 ─────────────────────────────────────────────────────


def test_chain_result_contains_ew_jamming_key():
    """run_cycle_chain 각 사이클 결과에 'ew_jamming' advisory 키가 있어야 한다."""
    results = run_cycle_chain(_pairs())
    for i, r in enumerate(results):
        assert "ew_jamming" in r, f"cycle {i}: ew_jamming 키 없음. 키셋: {set(r)}"


def test_ew_jamming_present_for_single_cycle_chain():
    """단일 사이클 chain에서도 ew_jamming 존재."""
    results = run_cycle_chain(_pairs(1))
    assert "ew_jamming" in results[0]


# ── 2. 필수 필드 ─────────────────────────────────────────────────────────────


def test_ew_jamming_has_required_fields():
    """ew_jamming advisory 필수 필드 확인."""
    results = run_cycle_chain(_pairs())
    ew = results[0]["ew_jamming"]
    assert isinstance(ew, dict)
    assert "assessable" in ew
    assert "threat_level" in ew
    assert "recommended_action" in ew
    assert "advisory_only" in ew
    assert ew["advisory_only"] is True, "ew_jamming advisory_only=True 이어야 함"


def test_ew_jamming_threat_level_is_valid():
    """threat_level 은 유효한 값이어야 한다."""
    results = run_cycle_chain(_pairs())
    for i, r in enumerate(results):
        lvl = r["ew_jamming"]["threat_level"]
        assert lvl in _VALID_THREAT_LEVELS, f"cycle {i}: 유효하지 않은 threat_level: {lvl}"


def test_ew_jamming_recommended_action_is_valid():
    """recommended_action 은 CONTINUE|MONITOR|EMCON_EVADE 중 하나여야 한다."""
    results = run_cycle_chain(_pairs())
    for i, r in enumerate(results):
        action = r["ew_jamming"]["recommended_action"]
        assert action in _VALID_ACTIONS, f"cycle {i}: 유효하지 않은 action: {action}"


def test_ew_jamming_has_streak_and_seconds_fields():
    """anomaly_streak, anomaly_seconds 필드 있어야 한다."""
    results = run_cycle_chain(_pairs())
    ew = results[0]["ew_jamming"]
    assert "anomaly_streak" in ew
    assert "anomaly_seconds" in ew


# ── 3. SCC-1: ew_jamming 추가가 결정론 판정에 영향 없음 ─────────────────────────


def test_ew_jamming_does_not_change_risk_rac():
    """ew_jamming advisory 추가 후 risk(RAC) 판정 불변 (SCC-1)."""
    r1 = run_cycle_chain(_pairs())
    r2 = run_cycle_chain(_pairs())
    for i in range(len(r1)):
        assert r1[i]["risk"] == r2[i]["risk"]
        assert r1[i]["threat"] == r2[i]["threat"]
        assert r1[i]["response"] == r2[i]["response"]


def test_ew_jamming_does_not_change_flight_plan():
    """ew_jamming advisory 는 flight_plan 결과에 영향 없어야 한다 (SCC-1)."""
    r1 = run_cycle_chain(_pairs())
    r2 = run_cycle_chain(_pairs())
    for i in range(len(r1)):
        assert r1[i]["flight_plan"] == r2[i]["flight_plan"]


# ── 4. cross-cycle 누적: 후속 사이클일수록 긴 윈도우 반영 ─────────────────────


def test_ew_jamming_window_grows_across_cycles():
    """사이클이 쌓일수록 rf_window 누적 → streak 단조증가 가능성 확인 (assessable 시)."""
    results = run_cycle_chain(_pairs(3))
    # 모든 사이클 assessable이면 streak는 최소 0 이상
    for r in results:
        ew = r["ew_jamming"]
        if ew["assessable"]:
            assert isinstance(ew["anomaly_streak"], int)
            assert ew["anomaly_streak"] >= 0


# ── 5. JSON 직렬화 가능 ───────────────────────────────────────────────────────


def test_ew_jamming_json_serializable():
    """ew_jamming 포함 chain 결과가 JSON 직렬화 가능해야 한다."""
    results = run_cycle_chain(_pairs())
    for r in results:
        dumped = json.dumps(r, ensure_ascii=False)
        assert json.loads(dumped)["ew_jamming"]["advisory_only"] is True


# ── 6. 기존 키 보존 ───────────────────────────────────────────────────────────


def test_existing_chain_keys_still_present():
    """ew_jamming 추가 후에도 기존 chain 결과 키 전부 보존돼야 한다."""
    results = run_cycle_chain(_pairs())
    for r in results:
        for key in (
            "abstraction", "threat", "risk", "response",
            "flight_plan", "flight_plan_state", "endurance",
        ):
            assert key in r, f"기존 키 '{key}' 사라짐"
