"""종단 골든 회귀 테스트 (step9 §3).

각 시나리오의 종단 출력(run_cycle 전체 dict)을 커밋된 golden 과 비교한다.
시맨틱 테스트(test_e2e_semantics)가 스펙 의미를 직접 인코딩하는 반면,
이 테스트는 전체 출력 스냅샷을 그대로 잠가 예기치 않은 회귀를 잡는다.

golden 재생성 (손편집 금지 — CLI 산출만):
    for s in t1 t2 t3 t4 t7; do
      PYTHONPATH=src python3 -m onboard examples/raw_$s.json examples/mission_brief_$s.json \\
        > tests/integration/golden/expected_$s.json
    done

golden 이 의도적으로 바뀌어야 할 때만 위 명령으로 재생성 후 diff 를 리뷰한다.
"""

import json
import pathlib

import pytest

from onboard.run import run_cycle

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
GOLDEN = pathlib.Path(__file__).resolve().parent / "golden"

SCENARIOS = ["t1", "t2", "t3", "t4", "t7"]


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_e2e_golden(scenario: str) -> None:
    raw = _load(EXAMPLES / f"raw_{scenario}.json")
    mission_brief = _load(EXAMPLES / f"mission_brief_{scenario}.json")
    expected = _load(GOLDEN / f"expected_{scenario}.json")

    actual = run_cycle(raw, mission_brief)

    assert actual == expected, (
        f"{scenario} 종단 출력이 golden 과 diverge. 의도된 변경이면 "
        f"CLI 로 expected_{scenario}.json 재생성 후 diff 리뷰."
    )
