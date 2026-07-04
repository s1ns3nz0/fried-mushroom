"""run — 2단계 오케스트레이터(assemble_draft → finalize) 검증 (TDD)."""

import pytest

from gcs.layer_01_info_center.assemble import MISSION_BRIEF_FIELDS
from gcs.layer_01_info_center.run import assemble_draft, finalize


def _inputs(**over):
    base = {
        "sortie_id": "S-01",
        "directive_text": "적 저격조 첩보 확인됨. 가용 예비기체 없음.",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": True, "armament": [], "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "c4i": {
            "enemy_situation": ["적 저격조 활동 확인"],
            "asset_management": {"spare_asset_available": False},
            "known_mission": "정찰 감시",
        },
    }
    base.update(over)
    return base


def test_assemble_draft_structure() -> None:
    # 라운드2: mettc_state 추가(상위집합). draft_brief 6필드 계약은 유지.
    out = assemble_draft(_inputs())
    assert {"draft_brief", "signal_cards", "warnings"} <= set(out)
    assert set(out["draft_brief"]) == set(MISSION_BRIEF_FIELDS)


def test_signal_cards_carry_directive_signals() -> None:
    out = assemble_draft(_inputs())
    phrases = {c["source_phrase"] for c in out["signal_cards"]}
    assert "저격조" in phrases
    for c in out["signal_cards"]:
        assert c["confidence"] >= 0.7
        assert c["interpretation"]


def test_corroboration_reason_on_card() -> None:
    out = assemble_draft(_inputs())
    sniper = next(c for c in out["signal_cards"] if c["source_phrase"] == "저격조")
    assert sniper["adjust_reason"]  # C4I 적상황 확증 반영


def test_spare_mismatch_warning_surfaced() -> None:
    out = assemble_draft(_inputs())  # 등록 True vs C4I False
    assert [w for w in out["warnings"] if w["field"] == "spare_available"]


def test_finalize_approved_returns_onboard_brief() -> None:
    draft = assemble_draft(_inputs())
    res = finalize(draft, approved=True, ts_ms=1720000000000)
    assert set(res["mission_brief"]) == set(MISSION_BRIEF_FIELDS)
    assert res["approved_ts_ms"] == 1720000000000


def test_finalize_rejected_is_pending() -> None:
    draft = assemble_draft(_inputs())
    res = finalize(draft, approved=False, ts_ms=1720000000000)
    assert res["status"] == "pending_approval"
    assert "mission_brief" not in res
    assert "warnings" in res


def test_missing_directive_yields_no_cards_but_still_drafts() -> None:
    inp = _inputs()
    del inp["directive_text"]
    out = assemble_draft(inp)
    assert out["signal_cards"] == []
    assert set(out["draft_brief"]) == set(MISSION_BRIEF_FIELDS)
