"""assemble — set_mission 입력 → 6-필드 MissionBrief draft (TDD)."""

import pytest

from gcs.layer_01_info_center.assemble import MISSION_BRIEF_FIELDS, assemble_brief


def _inputs(**over):
    base = {
        "sortie_id": "S-01",
        "directive_text": "적 저격조 확인됨",  # brief 에는 안 들어감
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": True, "armament": [], "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "c4i": {"enemy_situation": []},  # brief 에는 안 들어감
    }
    base.update(over)
    return base


def test_assembles_exactly_six_fields() -> None:
    brief = assemble_brief(_inputs())
    assert set(brief) == set(MISSION_BRIEF_FIELDS)
    assert set(brief) == {"sortie_id", "mission_context", "posture", "drone_profile", "corridor", "weights"}


def test_drone_profile_passed_through_unchanged() -> None:
    dp = {"spare_available": False, "armament": [{"type": "leaflet", "expendable": True}]}
    brief = assemble_brief(_inputs(drone_profile=dp))
    assert brief["drone_profile"] == dp


def test_directive_and_c4i_excluded_from_brief() -> None:
    brief = assemble_brief(_inputs())
    assert "directive_text" not in brief
    assert "c4i" not in brief


def test_missing_required_field_raises() -> None:
    inp = _inputs()
    del inp["sortie_id"]
    with pytest.raises((KeyError, ValueError)):
        assemble_brief(inp)


def test_values_preserved() -> None:
    brief = assemble_brief(_inputs())
    assert brief["sortie_id"] == "S-01"
    assert brief["mission_context"] == "정찰"
    assert brief["posture"]["infocon"] == 4
