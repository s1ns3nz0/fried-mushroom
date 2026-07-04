"""mission_pipeline 01→07 종단 골든 회귀.

set_mission → layer 01 → mission_brief → run_cycle 전체 출력을 CLI(--ts 고정)로
dump 한 정본과 비교. 손편집 금지 — CLI 산출만.

재생성:
    for s in recon strike; do
      python3 -m mission_pipeline examples/set_mission_$s.json examples/raw_t3.json \\
        --approve --ts 1720051200000 > examples/expected_pipeline_$s.json
    done
"""

import json
import pathlib

import pytest

import mission_pipeline as mp

_EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples"
_TS = 1720051200000
_SCENARIOS = ["recon", "strike"]


def _run(scenario: str, capsys) -> dict:
    mp.main([
        str(_EXAMPLES / f"set_mission_{scenario}.json"),
        str(_EXAMPLES / "raw_t3.json"),
        "--approve",
        "--ts",
        str(_TS),
    ])
    return json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("scenario", _SCENARIOS)
def test_pipeline_golden(scenario, capsys) -> None:
    actual = _run(scenario, capsys)
    expected = json.loads((_EXAMPLES / f"expected_pipeline_{scenario}.json").read_text(encoding="utf-8"))
    assert actual == expected, (
        f"{scenario} 종단 출력이 golden 과 diverge. 의도된 변경이면 CLI 로 재생성 후 diff 리뷰."
    )
