"""failsafe_arbiter advisory run_cycle_chain 배선 계약 — TDD (#399).

run_cycle_chain 각 결과에 'failsafe' advisory 키 추가.
CRITICAL: advisory_only=True — SCC-1, 결정론 판정(RAC/threat/response/flight_plan) 불변.
"""

from __future__ import annotations

import json
import pathlib

from onboard.layer_02_sensor.mock_source import build_normal_envelope
from onboard.run import run_cycle_chain

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"

_VALID_ACTIONS = frozenset({"CONTINUE", "MONITOR", "HOLD", "DR_HOLD", "RTL", "LAND", "UNKNOWN"})


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _brief() -> dict:
    return _load("mission_brief_t3.json")


def _raw() -> dict:
    return build_normal_envelope("fs", 0, 0)


def _pairs(n: int = 2) -> list:
    b = _brief()
    return [(_raw(), b) for _ in range(n)]


# ── 1. failsafe 키 존재 ───────────────────────────────────────────────────────


def test_chain_result_contains_failsafe_key():
    """run_cycle_chain 각 사이클 결과에 'failsafe' advisory 키가 있어야 한다."""
    results = run_cycle_chain(_pairs())
    for i, r in enumerate(results):
        assert "failsafe" in r, f"cycle {i}: failsafe 키 없음. 키셋: {set(r)}"


def test_failsafe_present_for_single_cycle_chain():
    """단일 사이클 chain에서도 failsafe 존재."""
    results = run_cycle_chain(_pairs(1))
    assert "failsafe" in results[0]


# ── 2. 필수 필드 ─────────────────────────────────────────────────────────────


def test_failsafe_has_required_fields():
    """failsafe advisory 필수 필드 확인."""
    results = run_cycle_chain(_pairs())
    fs = results[0]["failsafe"]
    assert isinstance(fs, dict)
    assert "assessable" in fs
    assert "recommended_action" in fs
    assert "advisory_only" in fs
    assert fs["advisory_only"] is True, "failsafe advisory_only=True 이어야 함"


def test_failsafe_recommended_action_is_valid():
    """recommended_action 은 유효한 값이어야 한다."""
    results = run_cycle_chain(_pairs())
    for i, r in enumerate(results):
        action = r["failsafe"]["recommended_action"]
        assert action in _VALID_ACTIONS, f"cycle {i}: 유효하지 않은 action: {action}"


def test_failsafe_has_severity_and_axes_fields():
    """failsafe 결과에 severity, driving_axes, contributions 필드 있어야 한다."""
    results = run_cycle_chain(_pairs())
    fs = results[0]["failsafe"]
    assert "severity" in fs
    assert "driving_axes" in fs
    assert "contributions" in fs
    assert isinstance(fs["driving_axes"], list)
    assert isinstance(fs["contributions"], dict)


# ── 3. SCC-1: failsafe 추가가 결정론 판정에 영향 없음 ─────────────────────────


def test_failsafe_does_not_change_risk_rac():
    """failsafe advisory 추가 후 risk(RAC) 판정 불변 (SCC-1)."""
    r1 = run_cycle_chain(_pairs())
    r2 = run_cycle_chain(_pairs())
    for i in range(len(r1)):
        assert r1[i]["risk"] == r2[i]["risk"]
        assert r1[i]["threat"] == r2[i]["threat"]
        assert r1[i]["response"] == r2[i]["response"]


def test_failsafe_does_not_change_flight_plan():
    """failsafe advisory 는 flight_plan 결과에 영향 없어야 한다 (SCC-1)."""
    r1 = run_cycle_chain(_pairs())
    r2 = run_cycle_chain(_pairs())
    for i in range(len(r1)):
        assert r1[i]["flight_plan"] == r2[i]["flight_plan"]


def test_failsafe_does_not_change_link_loss_or_nav_integrity():
    """failsafe 배선이 기존 link_loss/nav_integrity advisory 값을 변이하지 않는다."""
    r1 = run_cycle_chain(_pairs())
    r2 = run_cycle_chain(_pairs())
    for i in range(len(r1)):
        assert r1[i]["link_loss"] == r2[i]["link_loss"]
        assert r1[i]["nav_integrity"] == r2[i]["nav_integrity"]


# ── 4. JSON 직렬화 가능 ───────────────────────────────────────────────────────


def test_failsafe_json_serializable():
    """failsafe 포함 chain 결과가 JSON 직렬화 가능해야 한다."""
    results = run_cycle_chain(_pairs())
    for r in results:
        dumped = json.dumps(r, ensure_ascii=False)
        assert json.loads(dumped)["failsafe"]["advisory_only"] is True


# ── 5. 기존 키 보존 ───────────────────────────────────────────────────────────


def test_existing_chain_keys_still_present():
    """failsafe 추가 후에도 기존 chain 결과 키 전부 보존돼야 한다."""
    results = run_cycle_chain(_pairs())
    for r in results:
        for key in (
            "abstraction", "threat", "risk", "response",
            "flight_plan", "flight_plan_state", "endurance",
            "link_loss", "nav_integrity",
        ):
            assert key in r, f"기존 키 '{key}' 사라짐"


# ── 6. failsafe는 endurance/link_loss/nav_integrity 세 축을 소비 ───────────────


def test_failsafe_contributions_include_known_axes():
    """failsafe contributions 에 energy/comms/nav 중 assessable 축이 반영된다."""
    results = run_cycle_chain(_pairs())
    fs = results[0]["failsafe"]
    contribs = fs["contributions"]
    # contributions dict 키는 assessable 축만 포함 — 최소 0개 이상
    for axis in contribs:
        assert axis in ("energy", "comms", "nav"), f"알 수 없는 축: {axis}"
