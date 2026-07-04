"""골든 케이스 신선도 가드 — 온보드 02-07 전 시나리오 (#177).

현 파이프라인 출력이 examples/expected_tN.json 과 완전 일치하는지 parametrize 로 검증.
CI 가 향후 파이프라인 변경 시 드리프트를 조기 차단한다.

검증 원칙:
- run_cycle 직접 호출(float 동일 Python 버전 내 결정론) + CLI subprocess(직렬화 왕복)를 모두 커버.
- float 이식성: JSON 직렬화 후 동일 값임을 assert (Python 3.11 기준 결정론).
- 골든 변경은 D4D 문서 사유 필수 — 임의 수정 금지(CLAUDE.md).
"""

import json
import pathlib
import subprocess
import sys

import pytest

from onboard.run import run_cycle

EXAMPLES = pathlib.Path(__file__).resolve().parents[2] / "examples"

_SCENARIOS = [
    ("raw_t1.json", "mission_brief_t1.json", None, "expected_t1.json"),
    ("raw_t2.json", "mission_brief_t2.json", None, "expected_t2.json"),
    ("raw_t3.json", "mission_brief_t3.json", None, "expected_t3.json"),
    ("raw_t4.json", "mission_brief_t4.json", None, "expected_t4.json"),
    ("raw_t5.json", "mission_brief_t5.json", "qualities_t5_primed.json", "expected_t5.json"),
    ("raw_t6.json", "mission_brief_t6.json", None, "expected_t6.json"),
    ("raw_t7.json", "mission_brief_t7.json", None, "expected_t7.json"),
    ("raw_t3.json", "mission_brief_strike.json", None, "expected_strike.json"),
]

_IDS = ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "strike"]


def _load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


# ── 1. run_cycle 직접 호출 (float 결정론, 레이어 내부 경로) ─────────────────────


@pytest.mark.parametrize("raw,brief,prev_q,expected", _SCENARIOS, ids=_IDS)
def test_golden_freshness_run_cycle(raw, brief, prev_q, expected):
    """run_cycle 출력이 골든과 완전 일치해야 한다."""
    previous_qualities = _load(prev_q) if prev_q else None
    actual = run_cycle(_load(raw), _load(brief), previous_qualities=previous_qualities)
    golden = _load(expected)
    assert actual == golden, (
        f"골든 드리프트 감지: {expected}\n"
        "재생성 시 D4D 문서 사유 명시 후 PR 본문에 diff 요약 필수."
    )


# ── 2. CLI subprocess (직렬화 왕복 — JSON dumps/loads 경로 포함) ────────────────


@pytest.mark.parametrize("raw,brief,prev_q,expected", _SCENARIOS, ids=_IDS)
def test_golden_freshness_cli(raw, brief, prev_q, expected):
    """CLI(python -m onboard) 출력이 골든과 완전 일치해야 한다 (직렬화 왕복 포함)."""
    src_root = str(EXAMPLES.parents[0] / "src")
    cmd = [sys.executable, "-m", "onboard", str(EXAMPLES / raw), str(EXAMPLES / brief)]
    if prev_q:
        cmd += ["--prev-qualities", str(EXAMPLES / prev_q)]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": src_root},
    )
    assert result.returncode == 0, f"CLI 오류 ({expected}):\n{result.stderr[:500]}"
    actual = json.loads(result.stdout)
    golden = _load(expected)
    assert actual == golden, (
        f"CLI 골든 드리프트 감지: {expected}\n"
        "재생성 시 D4D 문서 사유 명시 후 PR 본문에 diff 요약 필수."
    )
