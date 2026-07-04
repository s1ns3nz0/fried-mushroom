"""run.assemble_draft ↔ briefing_advisor 배선 검증 (#342).

TDD: assemble_draft 에 store 주입 시 briefing_advisory 필드 첨부,
무-store graceful, 결정 무변경(SCC-1) 불변식을 강제한다.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_INFRA_LOG = Path(__file__).resolve().parents[3] / "infra" / "log"
if str(_INFRA_LOG) not in sys.path:
    sys.path.insert(0, str(_INFRA_LOG))

from gcs.layer_01_info_center.run import assemble_draft


def _inputs(**over):
    base = {
        "sortie_id": "S-WIRE-01",
        "directive_text": "저격조 확인됨. 사이버 재밍 가능성.",
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"spare_asset_available": True, "armament": [], "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "c4i": {"enemy_situation": ["저격조 활동 확인"]},
    }
    base.update(over)
    return base


def _fake_store(records=None):
    """briefing_advisor.build_briefing_advisory 가 호출하는 store.retrieve 를 모킹."""
    store = MagicMock()
    store.retrieve.return_value = records or []
    return store


# ── 1. 무-store graceful ──────────────────────────────────────────────────────


def test_assemble_draft_no_store_no_advisory():
    """store=None 이면 briefing_advisory 필드가 없거나 None — 크래시 없음."""
    out = assemble_draft(_inputs())
    # 기존 필드는 그대로
    assert "draft_brief" in out
    assert "signal_cards" in out
    # advisory 없거나 None
    assert out.get("briefing_advisory") is None


def test_assemble_draft_store_none_explicit():
    """store=None 명시 전달도 graceful."""
    out = assemble_draft(_inputs(), store=None)
    assert out.get("briefing_advisory") is None


# ── 2. store 주입 시 briefing_advisory 필드 첨부 ─────────────────────────────


def test_assemble_draft_with_store_has_advisory():
    """store 주입 시 반환 dict 에 briefing_advisory 키가 있어야 한다."""
    out = assemble_draft(_inputs(), store=_fake_store())
    assert "briefing_advisory" in out, "store 주입 → briefing_advisory 필드 기대"


def test_advisory_has_required_structure():
    """briefing_advisory 는 advisory_only, advisories, generated_ts 를 포함해야 한다."""
    out = assemble_draft(_inputs(), store=_fake_store())
    adv = out["briefing_advisory"]
    assert adv is not None
    assert adv.get("advisory_only") is True, "SCC-1: advisory_only=True 필수"
    assert "advisories" in adv
    assert "generated_ts" in adv
    assert isinstance(adv["advisories"], list)


def test_advisory_threat_events_match_signals():
    """위협 신호 T3 포함 지시서 → advisories 에 T3 항목이 있어야 한다."""
    out = assemble_draft(
        _inputs(directive_text="저격조 확인됨."),  # T3 → threat signal
        store=_fake_store(),
    )
    adv = out["briefing_advisory"]
    t_codes = [a["threat_event"] for a in adv["advisories"]]
    assert "T3" in t_codes, f"T3 advisory 기대, got {t_codes}"


def test_advisory_with_history_populated():
    """코퍼스 이력이 있을 때 sample_size 와 outcome_distribution 이 채워져야 한다."""
    records = [
        {"confidence": 0.9, "outcome": "rtb_success"},
        {"confidence": 0.7, "outcome": "rtb_success"},
        {"confidence": 0.8, "outcome": "mission_abort"},
    ]
    out = assemble_draft(
        _inputs(directive_text="저격조 확인됨."),
        store=_fake_store(records=records),
    )
    adv = out["briefing_advisory"]
    t3_entry = next((a for a in adv["advisories"] if a["threat_event"] == "T3"), None)
    assert t3_entry is not None
    assert t3_entry["sample_size"] == 3
    assert "rtb_success" in t3_entry["outcome_distribution"]


# ── 3. SCC-1: 결정 무변경 ─────────────────────────────────────────────────────


def test_advisory_does_not_change_draft_brief():
    """store 유무와 관계없이 draft_brief 내용이 동일해야 한다 (SCC-1)."""
    out_no_store = assemble_draft(_inputs())
    out_with_store = assemble_draft(_inputs(), store=_fake_store())
    assert out_no_store["draft_brief"] == out_with_store["draft_brief"], (
        "SCC-1 위반: store 주입이 draft_brief 를 변경함"
    )


def test_advisory_does_not_change_signal_cards():
    """store 유무와 관계없이 signal_cards 내용이 동일해야 한다 (SCC-1)."""
    out_no_store = assemble_draft(_inputs())
    out_with_store = assemble_draft(_inputs(), store=_fake_store())
    assert out_no_store["signal_cards"] == out_with_store["signal_cards"], (
        "SCC-1 위반: store 주입이 signal_cards 를 변경함"
    )


def test_advisory_does_not_change_mettc_state():
    """store 유무와 관계없이 mettc_state 내용이 동일해야 한다 (SCC-1)."""
    out_no_store = assemble_draft(_inputs())
    out_with_store = assemble_draft(_inputs(), store=_fake_store())
    assert out_no_store["mettc_state"] == out_with_store["mettc_state"], (
        "SCC-1 위반: store 주입이 mettc_state 를 변경함"
    )


def test_advisory_does_not_change_warnings():
    """store 유무와 관계없이 warnings 가 동일해야 한다 (SCC-1)."""
    out_no_store = assemble_draft(_inputs())
    out_with_store = assemble_draft(_inputs(), store=_fake_store())
    assert out_no_store["warnings"] == out_with_store["warnings"], (
        "SCC-1 위반: store 주입이 warnings 를 변경함"
    )


def test_advisory_only_flag_always_true():
    """briefing_advisory.advisory_only 는 반드시 True (SCC-1 불변식)."""
    out = assemble_draft(_inputs(), store=_fake_store())
    assert out["briefing_advisory"]["advisory_only"] is True


def test_advisory_inputs_are_not_mutated():
    """assemble_draft 는 inputs dict 를 변경하지 않아야 한다."""
    inputs = _inputs()
    original = copy.deepcopy(inputs)
    assemble_draft(inputs, store=_fake_store())
    assert inputs == original, "inputs dict 가 변경됨"
