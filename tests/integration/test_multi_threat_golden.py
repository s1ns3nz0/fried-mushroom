"""다중 위협 동시 시나리오 골든 케이스 (#188).

시나리오: T5(광학교란) + T3(근접 physical) 동시 활성.
- T3(Serious): weapon person + acoustic gunshot → 지배 위협(primary).
- T5(Medium): terrain_class quality_delta급락(1.0→0.65, prev_qualities 주입) → 부차 위협.

검증:
1. 골든 완전 일치 (run_cycle + CLI 두 경로).
2. 의미적 assert: worst-case RAC = T3(Serious) 지배, flight_action 정합, 07 anchor 정합.
"""

import json
import pathlib
import subprocess
import sys

import pytest

from onboard.run import run_cycle

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _run_multi() -> dict:
    return run_cycle(
        _load("raw_multi.json"),
        _load("mission_brief_multi.json"),
        previous_qualities=_load("qualities_multi_primed.json"),
    )


# ── 1. 골든 완전 일치 ────────────────────────────────────────────────────────


def test_multi_threat_golden_run_cycle():
    """run_cycle 출력이 expected_multi.json 골든과 완전 일치해야 한다."""
    actual = _run_multi()
    golden = _load("expected_multi.json")
    assert actual == golden, "다중 위협 골든 드리프트 — expected_multi.json 재생성 필요"


def test_multi_threat_golden_cli():
    """CLI(python -m onboard) 출력이 expected_multi.json 골든과 완전 일치해야 한다."""
    src_root = str(EXAMPLES.parents[0] / "src")
    cmd = [
        sys.executable, "-m", "onboard",
        str(EXAMPLES / "raw_multi.json"),
        str(EXAMPLES / "mission_brief_multi.json"),
        "--prev-qualities", str(EXAMPLES / "qualities_multi_primed.json"),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONPATH": src_root},
    )
    assert result.returncode == 0, f"CLI 오류:\n{result.stderr[:500]}"
    actual = json.loads(result.stdout)
    golden = _load("expected_multi.json")
    assert actual == golden, "CLI 다중 위협 골든 드리프트"


# ── 2. 의미적 assert ─────────────────────────────────────────────────────────


def test_multi_threat_both_candidates_present():
    """T3 + T5 두 위협이 모두 risk.candidates 에 존재해야 한다."""
    result = _run_multi()
    events = {c["threat_event"] for c in result["risk"]["candidates"]}
    assert "T3" in events, f"T3 없음: {events}"
    assert "T5" in events, f"T5 없음: {events}"


def test_multi_threat_t3_dominates_as_primary():
    """T3(Serious)가 worst-case 로 primary 가 되어야 한다 (T5 Medium 보다 심각)."""
    result = _run_multi()
    assert result["response"]["primary_threat_event"] == "T3", (
        f"primary={result['response']['primary_threat_event']!r}, T3 이어야 함"
    )
    assert result["response"]["rac"] == "Serious", (
        f"primary RAC={result['response']['rac']!r}, Serious 이어야 함"
    )


def test_multi_threat_t5_as_secondary():
    """T5 가 response.secondary_threats 에 포함돼야 한다."""
    result = _run_multi()
    secondary_events = [s["threat_event"] for s in result["response"]["secondary_threats"]]
    assert "T5" in secondary_events, (
        f"secondary_threats에 T5 없음: {secondary_events}"
    )


def test_multi_threat_flight_action_consistent_with_t3():
    """T3(Serious, PHYSICAL) 지배 시 flight_action 이 risk.candidates T3 와 정합해야 한다."""
    result = _run_multi()
    fp_action = result["flight_plan"]["flight_action"]
    resp_action = result["response"]["flight_action"]
    assert fp_action == resp_action, (
        f"flight_plan.flight_action({fp_action!r}) ≠ response.flight_action({resp_action!r})"
    )
    # T3 Serious PHYSICAL → ALTITUDE_CHANGE 또는 REROUTE 계열이어야 함.
    assert fp_action in ("ALTITUDE_CHANGE", "REROUTE", "RTL"), (
        f"T3 Serious 대응치고 flight_action={fp_action!r} 이 예상 범위 밖"
    )


def test_multi_threat_worst_rac_is_serious():
    """risk.candidates 중 최악 RAC 가 Serious 이어야 한다 (T3 기여)."""
    _RAC_RANK = {"Low": 0, "Medium": 1, "Serious": 2, "High": 3}
    result = _run_multi()
    worst = max(
        (c["rac"] for c in result["risk"]["candidates"]),
        key=lambda r: _RAC_RANK.get(r, -1),
    )
    assert worst in ("Serious", "High"), f"worst RAC={worst!r}, Serious/High 이어야 함"
