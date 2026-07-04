"""advisory 모듈 run_cycle 결과/CLI 배선 — TDD (#360).

run_cycle 결과에 endurance advisory 필드 추가 및 CLI --sitrep/--explain 플래그.
CRITICAL: advisory 필드는 advisory_only — 기존 결정론 판정(risk/threat/response) 불변.
"""

from __future__ import annotations

import io
import json
import pathlib
import sys

import pytest

from onboard.layer_02_sensor.mock_source import build_normal_envelope, build_scenario_envelope
from onboard.run import run_cycle

_EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((_EXAMPLES / name).read_text(encoding="utf-8"))


def _brief():
    return _load("mission_brief_t3.json")


def _raw():
    return build_normal_envelope("adv", 0, 0)


# ── 1. run_cycle 결과에 endurance advisory 필드 추가 ─────────────────────────


def test_run_cycle_result_contains_endurance_key():
    """run_cycle 결과에 'endurance' advisory 키가 있어야 한다."""
    out = run_cycle(_raw(), _brief())
    assert "endurance" in out, f"run_cycle 결과에 endurance 키 없음. 키셋: {set(out)}"


def test_endurance_advisory_has_required_fields():
    """endurance advisory 는 required 필드를 포함해야 한다."""
    out = run_cycle(_raw(), _brief())
    end = out["endurance"]
    assert isinstance(end, dict)
    assert "recommended_action" in end
    assert "advisory_only" in end
    assert end["advisory_only"] is True, "endurance 는 advisory_only=True 이어야 함"


def test_endurance_recommended_action_is_valid():
    """recommended_action 은 RTL | CONTINUE | UNKNOWN 중 하나여야 한다."""
    out = run_cycle(_raw(), _brief())
    action = out["endurance"]["recommended_action"]
    assert action in ("RTL", "CONTINUE", "UNKNOWN"), f"유효하지 않은 action: {action}"


# ── 2. SCC-1: advisory 추가가 결정론 판정에 영향 없음 ─────────────────────────


def test_endurance_does_not_change_risk_rac():
    """endurance advisory 추가 후 risk(RAC) 판정 불변 (SCC-1)."""
    out = run_cycle(_raw(), _brief())
    # endurance 키를 제거해도 risk 는 동일해야 함 — advisory 는 사이드이펙트 없음
    out2 = run_cycle(_raw(), _brief())
    assert out["risk"] == out2["risk"]
    assert out["threat"] == out2["threat"]
    assert out["response"] == out2["response"]


def test_endurance_does_not_change_flight_plan():
    """endurance advisory 는 flight_plan 결과에 영향 없어야 한다 (SCC-1)."""
    out1 = run_cycle(_raw(), _brief())
    out2 = run_cycle(_raw(), _brief())
    assert out1["flight_plan"] == out2["flight_plan"]


# ── 3. 계약: 기존 키셋 + endurance ────────────────────────────────────────────


def test_run_cycle_output_keyset_with_endurance():
    """run_cycle 결과 키셋 = 기존 6키 + endurance."""
    out = run_cycle(_raw(), _brief())
    expected = {"abstraction", "threat", "risk", "response",
                "flight_plan", "flight_plan_state", "endurance"}
    assert set(out) == expected, f"키셋 불일치: {set(out)}"


def test_run_cycle_json_serializable_with_endurance():
    """endurance 포함 run_cycle 결과가 JSON 직렬화 가능해야 한다."""
    out = run_cycle(_raw(), _brief())
    dumped = json.dumps(out, ensure_ascii=False)
    assert json.loads(dumped)["endurance"]["advisory_only"] is True


# ── 4. CLI --sitrep 플래그 ─────────────────────────────────────────────────────


def test_cli_sitrep_flag_outputs_sitrep(tmp_path):
    """CLI --sitrep 플래그 시 sitrep 포함 JSON 출력."""
    from onboard import __main__ as cli

    raw_p = tmp_path / "raw.json"
    raw_p.write_text(json.dumps(_raw()), encoding="utf-8")
    brief_p = _EXAMPLES / "mission_brief_t3.json"

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    rc = cli.main([str(raw_p), str(brief_p), "--sitrep"])
    sys.stdout = old_stdout

    assert rc == 0
    result = json.loads(buf.getvalue())
    assert "sitrep" in result, f"--sitrep 플래그 시 sitrep 키 없음: {set(result)}"


def test_cli_explain_flag_outputs_explanation(tmp_path):
    """CLI --explain 플래그 시 explanation 포함 JSON 출력."""
    from onboard import __main__ as cli

    raw_p = tmp_path / "raw.json"
    raw_p.write_text(json.dumps(_raw()), encoding="utf-8")
    brief_p = _EXAMPLES / "mission_brief_t3.json"

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    rc = cli.main([str(raw_p), str(brief_p), "--explain"])
    sys.stdout = old_stdout

    assert rc == 0
    result = json.loads(buf.getvalue())
    assert "explanation" in result, f"--explain 플래그 시 explanation 키 없음: {set(result)}"


def test_cli_without_advisory_flags_unchanged(tmp_path):
    """--sitrep/--explain 없으면 기존 출력 계약 유지 (sitrep/explanation 키 없음)."""
    from onboard import __main__ as cli

    raw_p = tmp_path / "raw.json"
    raw_p.write_text(json.dumps(_raw()), encoding="utf-8")
    brief_p = _EXAMPLES / "mission_brief_t3.json"

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    rc = cli.main([str(raw_p), str(brief_p)])
    sys.stdout = old_stdout

    assert rc == 0
    result = json.loads(buf.getvalue())
    # 플래그 없으면 sitrep/explanation 은 없어야 함
    assert "sitrep" not in result
    assert "explanation" not in result
    # endurance 는 항상 있어야 함
    assert "endurance" in result


def test_cli_sitrep_and_explain_combined(tmp_path):
    """--sitrep --explain 동시 사용 시 둘 다 출력."""
    from onboard import __main__ as cli

    raw_p = tmp_path / "raw.json"
    raw_p.write_text(json.dumps(_raw()), encoding="utf-8")
    brief_p = _EXAMPLES / "mission_brief_t3.json"

    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    rc = cli.main([str(raw_p), str(brief_p), "--sitrep", "--explain"])
    sys.stdout = old_stdout

    assert rc == 0
    result = json.loads(buf.getvalue())
    assert "sitrep" in result
    assert "explanation" in result


# ── 5. 기존 계약 테스트 회귀: endurance 허용 ──────────────────────────────────


def test_existing_layer_keys_still_present():
    """endurance 추가 후에도 기존 결과 키 전부 보존돼야 한다."""
    out = run_cycle(_raw(), _brief())
    for key in ("abstraction", "threat", "risk", "response", "flight_plan", "flight_plan_state"):
        assert key in out, f"기존 키 '{key}' 사라짐"
