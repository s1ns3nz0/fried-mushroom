"""종단 배선: 지시서(set_mission) → GCS 01 승인 → MissionBrief → 온보드 파이프라인.

골든 케이스: examples/set_mission_t3.json (t3 브리핑 + 지시서/C4I) → GCS CLI 산출
브리핑이 examples/raw_t3.json 과 함께 온보드 run_cycle 을 T3 골든과 동일하게 구동해야 한다.
GCS 산출물이 온보드 계약(6필드)을 실제로 만족하는지의 살아있는 증명 (B-1 §5.3).
"""

import json
from pathlib import Path

from gcs.__main__ import main as gcs_main
from onboard.run import run_cycle

_SET_MISSION = "examples/set_mission_t3.json"
_RAW = "examples/raw_t3.json"
_GOLDEN_BRIEF = "examples/mission_brief_t3.json"


def _gcs_brief(tmp_path) -> dict:
    out = tmp_path / "brief.json"
    rc = gcs_main([_SET_MISSION, "--approve", "--out", str(out), "--ts-ms", "0"])
    assert rc == 0
    return json.loads(out.read_text(encoding="utf-8"))


def test_gcs_brief_matches_golden_t3(tmp_path) -> None:
    # 레거시 corridor 보존(waypoint/base 원본 passthrough) 포함 — 골든과 완전 일치.
    brief = _gcs_brief(tmp_path)
    golden = json.loads(Path(_GOLDEN_BRIEF).read_text(encoding="utf-8"))
    assert brief == golden


def test_gcs_brief_drives_onboard_cycle(tmp_path) -> None:
    brief = _gcs_brief(tmp_path)
    raw = json.loads(Path(_RAW).read_text(encoding="utf-8"))
    result = run_cycle(raw, brief)
    golden_result = run_cycle(raw, json.loads(Path(_GOLDEN_BRIEF).read_text(encoding="utf-8")))
    assert result == golden_result, "GCS 산출 브리핑은 골든 브리핑과 동일한 사이클 결과를 내야 함"
    assert result["flight_plan"]["flight_action"], "온보드 사이클이 비행 지시를 산출해야 함"
