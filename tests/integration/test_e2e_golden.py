"""종단 골든 회귀 테스트.

examples/expected_tN.json = CLI(python -m onboard) 산출 정본. 손편집 금지.
run_cycle 출력이 정본과 완전 일치하는지 검증한다 (스펙 변경 시 golden 재생성 필요).
"""

import json
import pathlib

from onboard.run import run_cycle

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def _run(raw_name: str, brief_name: str, prev_qualities_name: str | None = None) -> dict:
    previous_qualities = _load(prev_qualities_name) if prev_qualities_name is not None else None
    return run_cycle(_load(raw_name), _load(brief_name), previous_qualities=previous_qualities)


def _assert_golden(actual: dict, expected_name: str) -> None:
    expected = _load(expected_name)
    assert actual == expected, f"golden mismatch: {expected_name}"


def test_golden_t1() -> None:
    _assert_golden(_run("raw_t1.json", "mission_brief_t1.json"), "expected_t1.json")


def test_golden_t2() -> None:
    _assert_golden(_run("raw_t2.json", "mission_brief_t2.json"), "expected_t2.json")


def test_golden_t3() -> None:
    _assert_golden(_run("raw_t3.json", "mission_brief_t3.json"), "expected_t3.json")


def test_golden_t4() -> None:
    _assert_golden(_run("raw_t4.json", "mission_brief_t4.json"), "expected_t4.json")


def test_golden_t7() -> None:
    _assert_golden(_run("raw_t7.json", "mission_brief_t7.json"), "expected_t7.json")


def test_golden_t6() -> None:
    _assert_golden(_run("raw_t6.json", "mission_brief_t6.json"), "expected_t6.json")


def test_golden_t5() -> None:
    # T5(레이저/광학 교란) 는 quality_delta 급락 파생필드로만 탐지 → previous_qualities 필요.
    # CLI(`python -m onboard ... --prev-qualities`) 와 동일하게 정본 주입 (#79/#97).
    _assert_golden(
        _run("raw_t5.json", "mission_brief_t5.json", "qualities_t5_primed.json"),
        "expected_t5.json",
    )


def test_golden_strike() -> None:
    _assert_golden(_run("raw_t3.json", "mission_brief_strike.json"), "expected_strike.json")
