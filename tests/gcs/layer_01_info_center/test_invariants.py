"""layer 01 불변식 — 스펙 핵심 원칙을 property 로 고정.

- 확신도 경계: 모든 signal_card confidence ∈ [CONFIDENCE_FLOOR, 1.0].
- 추적성(NLP 는 지시서만 읽음): 모든 신호 source_phrase 는 directive_text 부분문자열.
- 비변조: cross_check 는 입력 signals 를 mutate 하지 않는다.
- 승인 안전: finalize(approved=False) 는 절대 mission_brief 를 노출하지 않는다.
"""

import copy

import pytest

from gcs.layer_01_info_center.cross_check import cross_check
from gcs.layer_01_info_center.nlp_extract import CONFIDENCE_FLOOR
from gcs.layer_01_info_center.run import assemble_draft, finalize

_DIRECTIVES = [
    "적 저격조 첩보 확인됨. 가용 예비기체 없음.",
    "사이버 위협 확인. 대구경화기 식별.",
    "적 저격조 출현 가능성 있음.",  # hedge → 필터
    "일반 정찰. 특이사항 없음.",  # 무신호
    "재밍 확인됨. 예비드론 없음. 저격조 확인.",
]


def _inputs(directive: str, c4i: dict | None = None) -> dict:
    return {
        "sortie_id": "INV-01",
        "directive_text": directive,
        "mission_context": "정찰",
        "posture": {"watchcon": 3, "defcon": 3, "infocon": 4},
        "drone_profile": {"armament": [], "spare_asset_available": True, "battery_pct": 65},
        "corridor": {"waypoints": [], "bases": {}},
        "weights": {"stealth": 0.4, "survival": 0.35, "info_value": 0.2, "timeliness": 0.05},
        "c4i": c4i if c4i is not None else {},
    }


@pytest.mark.parametrize("directive", _DIRECTIVES)
def test_all_card_confidences_in_floor_to_one(directive) -> None:
    out = assemble_draft(_inputs(directive))
    for card in out["signal_cards"]:
        assert CONFIDENCE_FLOOR <= card["confidence"] <= 1.0


@pytest.mark.parametrize("directive", _DIRECTIVES)
def test_traceability_source_phrase_in_directive(directive) -> None:
    # NLP 는 지시서 원문만 읽는다 — 모든 신호 근거가 지시서 안에 있어야 한다.
    out = assemble_draft(_inputs(directive))
    for card in out["signal_cards"]:
        assert card["source_phrase"] in directive


def test_cross_check_does_not_mutate_input_signals() -> None:
    signals = [{"source_phrase": "저격조", "signal_type": "threat", "threat": "T3", "confidence": 0.85}]
    snapshot = copy.deepcopy(signals)
    cross_check(signals, {"spare_asset_available": True}, "정찰", {"enemy_situation": ["적 저격조 확인"]})
    assert signals == snapshot  # 원본 불변


def test_finalize_rejected_never_leaks_mission_brief() -> None:
    draft = assemble_draft(_inputs("적 저격조 확인됨"))
    res = finalize(draft, approved=False, ts_ms=1)
    assert "mission_brief" not in res
    assert res["status"] == "pending_approval"


def test_corroboration_keeps_confidence_bounded() -> None:
    # 확증 보너스가 반복돼도 1.0 상한을 넘지 않는다.
    c4i = {"enemy_situation": ["적 저격조 확인", "저격조 재확인"]}
    out = assemble_draft(_inputs("적 저격조 확인됨", c4i))
    for card in out["signal_cards"]:
        assert card["confidence"] <= 1.0
