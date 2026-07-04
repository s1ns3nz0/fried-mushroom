"""explain_cycle — run_cycle 결과 → 구조화 의사결정 근거(관측→추론→결정→행동).

파생 읽기전용: 파이프라인 출력을 조립해 설명만 만든다. 결정을 바꾸지 않고 입력을
변이하지 않는다. 골든 결과(examples/expected_*.json)를 실데이터 fixture 로 검증한다.
"""

import copy
import json
from pathlib import Path

import pytest

from onboard.explain import explain_cycle

_EX = Path(__file__).resolve().parents[2] / "examples"


def _golden(name):
    return json.load(open(_EX / name, encoding="utf-8"))


def _normal_result():
    """위협 없음 → MAINTAIN 최소 결과(파이프라인 계약 부분집합)."""
    return {
        "abstraction": {"channels": [
            {"channel": "position_consistency", "state": "normal", "quality": 0.95},
            {"channel": "link_status", "state": "normal", "quality": 0.9},
        ]},
        "threat": {"primary": None, "candidates": []},
        "risk": {"ambient_rac": "Low", "candidates": []},
        "response": {"flight_action": "MAINTAIN", "comms_level": "normal",
                     "nav_mode": "gnss", "payload_action": None, "threat_category": None,
                     "rac": "Low", "kill_chain_stage": None, "secondary_threats": []},
        "flight_plan": {"flight_action": "MAINTAIN", "replan_scope": "NONE",
                        "reroute_anchor": "mission_corridor_resume", "target_bearing_deg": None,
                        "altitude_delta_m": 0, "speed_mode": "NORMAL", "route": []},
    }


# ── 구조 계약 ────────────────────────────────────────────────────────────────

def test_steps_are_layers_03_to_07_in_order():
    out = explain_cycle(_normal_result())
    assert [s["layer"] for s in out["steps"]] == ["03", "04", "05", "06", "07"]


def test_derived_readonly_flag_and_no_mutation():
    r = _normal_result()
    snap = copy.deepcopy(r)
    out = explain_cycle(r)
    assert out["derived_readonly"] is True
    assert r == snap  # 입력 무변이


# ── T3 위협 골든 (실데이터) ──────────────────────────────────────────────────

def test_explain_t3_threat_and_provenance():
    out = explain_cycle(_golden("expected_t3.json"))
    assert out["primary_threat_event"] == "T3"
    steps = {s["layer"]: s for s in out["steps"]}
    # 04 위협: T3 + 확신도 + provenance(confidence_source/kill_chain_stage)
    t = steps["04"]
    assert "T3" in t["conclusion"]
    assert t["detail"]["confidence"] == pytest.approx(0.917, abs=1e-3)
    assert t["detail"]["confidence_source"]
    assert t["detail"]["kill_chain_stage"]
    assert t["detail"]["threat_desc"]  # THREAT_CATALOG 설명
    # 05 위험: primary 후보의 RAC
    assert steps["05"]["detail"]["rac"]
    # 06/07 flight_action 일치
    assert steps["06"]["detail"]["flight_action"] == out["flight_action"]
    assert steps["07"]["detail"]["flight_action"] == out["flight_action"]


def test_summary_mentions_action_and_threat():
    out = explain_cycle(_golden("expected_t3.json"))
    assert out["flight_action"] in out["summary"]
    assert "T3" in out["summary"]


# ── 위협 없음 분기 ───────────────────────────────────────────────────────────

def test_normal_no_threat_branch():
    out = explain_cycle(_normal_result())
    steps = {s["layer"]: s for s in out["steps"]}
    assert out["primary_threat_event"] is None
    assert "위협 없음" in steps["04"]["conclusion"]
    # 후보 없으면 05 는 ambient_rac 근거
    assert steps["05"]["detail"]["rac"] == "Low"
    assert out["flight_action"] == "MAINTAIN"


def test_abstraction_step_flags_abnormal_channels():
    r = _normal_result()
    r["abstraction"]["channels"].append(
        {"channel": "acoustic_event", "state": "gunshot", "quality": 0.8})
    out = explain_cycle(r)
    ab = {s["layer"]: s for s in out["steps"]}["03"]
    assert ab["detail"]["channel_count"] == 3
    assert "acoustic_event" in ab["detail"]["abnormal_channels"]
    assert "position_consistency" not in ab["detail"]["abnormal_channels"]  # normal 제외


# ── 견고성 ───────────────────────────────────────────────────────────────────

def test_graceful_on_partial_result():
    out = explain_cycle({})  # 빈 결과 — 크래시 없이 best-effort
    assert [s["layer"] for s in out["steps"]] == ["03", "04", "05", "06", "07"]
    assert out["flight_action"] is None
    assert out["primary_threat_event"] is None


def test_all_golden_scenarios_explainable():
    """모든 골든 시나리오가 예외 없이 설명 가능."""
    for g in sorted(_EX.glob("expected_*.json")):
        out = explain_cycle(json.load(open(g, encoding="utf-8")))
        assert len(out["steps"]) == 5
        assert "summary" in out


def test_format_explanation_text():
    from onboard.explain import format_explanation
    out = explain_cycle(_golden("expected_t3.json"))
    text = format_explanation(out)
    assert "결정:" in text
    assert "T3" in text
    assert "[04] 위협 판정" in text
    # 위협 케이스는 provenance 줄 포함
    assert "provenance" in text
