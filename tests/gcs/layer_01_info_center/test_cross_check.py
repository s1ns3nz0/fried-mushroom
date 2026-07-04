"""cross_check — NLP 신호/운용자 입력 vs C4I 사실 대조 (TDD).

두 종류: (1) 위협신호가 C4I 적상황에 확증되면 확신도 상향(+이유),
(2) spare_available·임무목적 불일치는 확신도 무변 경고만(사실 확인이지 확률 아님).
"""

from gcs.layer_01_info_center.cross_check import cross_check


def _threat_signal(conf=0.85):
    return {"source_phrase": "저격조", "signal_type": "threat", "threat": "T3", "confidence": conf}


def test_corroborated_threat_confidence_increases() -> None:
    sigs = [_threat_signal(0.85)]
    c4i = {"enemy_situation": ["적 저격조 활동 첩보 확인"]}
    adjusted, warnings = cross_check(sigs, {}, "정찰", c4i)
    assert adjusted[0]["confidence"] > 0.85
    assert adjusted[0]["confidence"] <= 1.0
    assert adjusted[0].get("adjust_reason")  # 이유 라벨


def test_uncorroborated_threat_confidence_unchanged() -> None:
    sigs = [_threat_signal(0.85)]
    adjusted, _ = cross_check(sigs, {}, "정찰", {"enemy_situation": ["차량 이동 관측"]})
    assert adjusted[0]["confidence"] == 0.85
    assert "adjust_reason" not in adjusted[0]


def test_spare_mismatch_is_warning_not_confidence() -> None:
    sigs = [_threat_signal(0.85)]
    dp = {"spare_asset_available": True}
    c4i = {"asset_management": {"spare_asset_available": False}}
    adjusted, warnings = cross_check(sigs, dp, "정찰", c4i)
    spare_w = [w for w in warnings if w["field"] == "spare_available"]
    assert len(spare_w) == 1
    assert spare_w[0]["registered"] is True and spare_w[0]["c4i"] is False
    assert adjusted[0]["confidence"] == 0.85  # 사실 불일치는 확신도 안 건드림


def test_spare_match_no_warning() -> None:
    _, warnings = cross_check([], {"spare_asset_available": False}, "정찰", {"asset_management": {"spare_asset_available": False}})
    assert [w for w in warnings if w["field"] == "spare_available"] == []


def test_mission_mismatch_warning() -> None:
    _, warnings = cross_check([], {}, "정찰", {"known_mission": "타격 작전"})
    assert [w for w in warnings if w["field"] == "mission_context"]


def test_mission_match_no_warning() -> None:
    _, warnings = cross_check([], {}, "정찰", {"known_mission": "정찰 감시 임무"})
    assert [w for w in warnings if w["field"] == "mission_context"] == []


def test_no_c4i_no_adjustment_no_warnings() -> None:
    sigs = [_threat_signal(0.85)]
    adjusted, warnings = cross_check(sigs, {"spare_asset_available": True}, "정찰", {})
    assert adjusted[0]["confidence"] == 0.85
    assert warnings == []
