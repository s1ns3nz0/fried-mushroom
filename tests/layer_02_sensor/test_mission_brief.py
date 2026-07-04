"""step2 — mission_brief 골든 파일 테스트."""

import json
from pathlib import Path

import pytest

from onboard.shared.constants import MISSION_CONTEXTS

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
BRIEF_KEYS = {
    "sortie_id",
    "mission_context",
    "posture",
    "drone_profile",
    "corridor",
    "weights",
}


@pytest.mark.parametrize("scenario", ["t3", "t4", "t7"])
def test_brief_valid_json_and_context(scenario):
    brief = json.loads((EXAMPLES_DIR / f"mission_brief_{scenario}.json").read_text("utf-8"))
    assert BRIEF_KEYS.issubset(brief.keys())
    assert brief["mission_context"] in MISSION_CONTEXTS


def test_t7_armament_expendable():
    brief = json.loads((EXAMPLES_DIR / "mission_brief_t7.json").read_text("utf-8"))
    assert brief["drone_profile"]["armament"][0]["expendable"] is True
