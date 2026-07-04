"""02–07 레이어 출력 스키마 conformance 스윕 (#198).

t1~t7 + strike + multi 시나리오 전체를 run_cycle 로 실행해
각 레이어(03 abstraction / 04 threat / 05 risk / 06 response / 07 flight_plan) 출력이
shared/schemas.py 에 정의된 스키마를 준수하는지 assert 한다.

검증 범위:
- 필수 키 존재 (TypedDict __required_keys__)
- 타입 적합성 (str/int/float/list/dict/Literal)
- enum 허용 도메인 명시 assert (flight_action, comms_level, speed_mode, rac, ...)
- JSON 직렬화 가능
- extra 키 없음 (스키마 드리프트 차단)

코드가 정본 (상수/스키마 불변). 문서 불일치 발견 시 별도 이슈.
"""

import json
import pathlib
import sys

import pytest

# helpers
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from helpers.contracts import assert_json_serializable, assert_matches_schema

from onboard.run import run_cycle
from onboard.shared.schemas import (
    AbstractionOutput,
    ChannelOutput,
    FlightPlanOutput,
    ResponseOutput,
    RiskAssessmentOutput,
    RiskCandidate,
    ThreatCandidate,
    ThreatModelingOutput,
)

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _run(raw: str, brief: str, prev_q: str | None = None) -> dict:
    pq = _load(prev_q) if prev_q else None
    return run_cycle(_load(raw), _load(brief), previous_qualities=pq)


_SCENARIOS = [
    ("raw_t1.json", "mission_brief_t1.json", None, "t1"),
    ("raw_t2.json", "mission_brief_t2.json", None, "t2"),
    ("raw_t3.json", "mission_brief_t3.json", None, "t3"),
    ("raw_t4.json", "mission_brief_t4.json", None, "t4"),
    ("raw_t5.json", "mission_brief_t5.json", "qualities_t5_primed.json", "t5"),
    ("raw_t6.json", "mission_brief_t6.json", None, "t6"),
    ("raw_t7.json", "mission_brief_t7.json", None, "t7"),
    ("raw_t3.json", "mission_brief_strike.json", None, "strike"),
    ("raw_multi.json", "mission_brief_multi.json", "qualities_multi_primed.json", "multi"),
]

_IDS = [s[3] for s in _SCENARIOS]

# ── enum 허용 도메인 ──────────────────────────────────────────────────────────
_FLIGHT_ACTIONS = {"MAINTAIN", "REROUTE", "ALTITUDE_CHANGE", "ALTITUDE_CHANGE_REROUTE", "RTL"}
_COMMS_LEVELS = {"L0", "L1", "L2", "L3"}
_SPEED_MODES = {"NORMAL", "CAUTIOUS", "MAX"}
_RAC_LABELS = {"High", "Serious", "Medium", "Low"}
_REPLAN_SCOPES = {"NONE", "LOCAL", "FULL"}
_CHANNEL_STATES = {"normal", "degraded", "anomaly"}
_THREAT_CATEGORIES = {"PHYSICAL", "REMOTE", "NAVIGATION", None}
_AI_RELIABILITY = {"normal", "low"}
_CONFIDENCE_SOURCES = {"ai", "deterministic"}
_KILL_CHAIN_STAGES = {"초기", "중기", "후기"}


# ── 03 abstraction ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,brief,prev_q,_id", _SCENARIOS, ids=_IDS)
def test_abstraction_schema(raw, brief, prev_q, _id):
    result = _run(raw, brief, prev_q)
    ab = result["abstraction"]
    assert_matches_schema(ab, AbstractionOutput)
    assert_json_serializable(ab)
    for ch in ab["channels"]:
        assert_matches_schema(ch, ChannelOutput)
        assert ch["state"] in _CHANNEL_STATES, (
            f"{_id} channel {ch['channel']}: state={ch['state']!r} not in {_CHANNEL_STATES}"
        )
        assert isinstance(ch["quality"], (int, float)), f"{_id}: quality not numeric"
        assert 0.0 <= ch["quality"] <= 1.0, f"{_id} {ch['channel']}: quality {ch['quality']} out of [0,1]"


# ── 04 threat ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,brief,prev_q,_id", _SCENARIOS, ids=_IDS)
def test_threat_schema(raw, brief, prev_q, _id):
    result = _run(raw, brief, prev_q)
    th = result["threat"]
    assert_matches_schema(th, ThreatModelingOutput)
    assert_json_serializable(th)
    for c in th["candidates"]:
        assert_matches_schema(c, ThreatCandidate)
        assert c["confidence_source"] in _CONFIDENCE_SOURCES
        assert c["kill_chain_stage"] in _KILL_CHAIN_STAGES
    if th["primary"] is not None:
        assert_matches_schema(th["primary"], ThreatCandidate)


# ── 05 risk ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,brief,prev_q,_id", _SCENARIOS, ids=_IDS)
def test_risk_schema(raw, brief, prev_q, _id):
    result = _run(raw, brief, prev_q)
    risk = result["risk"]
    assert_matches_schema(risk, RiskAssessmentOutput)
    assert_json_serializable(risk)
    for c in risk["candidates"]:
        assert_matches_schema(c, RiskCandidate)
        assert c["rac"] in _RAC_LABELS, f"{_id}: rac={c['rac']!r} not in {_RAC_LABELS}"
        assert c["priority_rank"] >= 1
    if risk.get("ambient_rac") is not None:
        assert risk["ambient_rac"] in _RAC_LABELS


# ── 06 response ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,brief,prev_q,_id", _SCENARIOS, ids=_IDS)
def test_response_schema(raw, brief, prev_q, _id):
    result = _run(raw, brief, prev_q)
    resp = result["response"]
    assert_matches_schema(resp, ResponseOutput)
    assert_json_serializable(resp)
    assert resp["flight_action"] in _FLIGHT_ACTIONS, (
        f"{_id}: flight_action={resp['flight_action']!r} not in {_FLIGHT_ACTIONS}"
    )
    assert resp["comms_level"] in _COMMS_LEVELS, (
        f"{_id}: comms_level={resp['comms_level']!r} not in {_COMMS_LEVELS}"
    )
    assert resp["threat_category"] in _THREAT_CATEGORIES, (
        f"{_id}: threat_category={resp['threat_category']!r} not in {_THREAT_CATEGORIES}"
    )
    assert resp["ai_reliability"] in _AI_RELIABILITY


# ── 07 flight_plan ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw,brief,prev_q,_id", _SCENARIOS, ids=_IDS)
def test_flight_plan_schema(raw, brief, prev_q, _id):
    result = _run(raw, brief, prev_q)
    fp = result["flight_plan"]
    assert_matches_schema(fp, FlightPlanOutput)
    assert_json_serializable(fp)
    assert fp["flight_action"] in _FLIGHT_ACTIONS, (
        f"{_id}: fp.flight_action={fp['flight_action']!r} not in {_FLIGHT_ACTIONS}"
    )
    assert fp["replan_scope"] in _REPLAN_SCOPES, (
        f"{_id}: replan_scope={fp['replan_scope']!r} not in {_REPLAN_SCOPES}"
    )
    assert fp["speed_mode"] in _SPEED_MODES, (
        f"{_id}: speed_mode={fp['speed_mode']!r} not in {_SPEED_MODES}"
    )
    if fp["target_bearing_deg"] is not None:
        assert isinstance(fp["target_bearing_deg"], (int, float))
        assert 0.0 <= fp["target_bearing_deg"] < 360.0
    for wp in fp["route"]:
        assert "lat" in wp and "lon" in wp and "alt_m" in wp, f"{_id}: route wp missing keys: {wp}"
