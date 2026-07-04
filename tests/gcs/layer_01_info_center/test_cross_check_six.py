"""cross_check 대조표 6종 완성 검증 (TDD, 01 문서·B-1 §5.4).

①적활동↔tracks ②화력↔tracks ③재보급/예비신호↔profile ④민간↔밀집도초안 (확신도 조정+이유)
⑤임무목적(NLP)↔운용자선택·C4I ⑥spare↔자산관리 (경고만).
입력 c4i 는 normalize_c4i 산출 골격.
"""

from gcs.layer_01_info_center.c4i_schema import normalize_c4i
from gcs.layer_01_info_center.cross_check import cross_check


def _sig(signal_type, phrase, conf=0.85, **extra):
    return {"source_phrase": phrase, "signal_type": signal_type, "confidence": conf, **extra}


def _c4i(**over):
    return normalize_c4i(over)


def test_1_threat_corroborated_by_structured_track() -> None:
    sigs = [_sig("threat", "저격조", threat="T3")]
    c4i = _c4i(enemy_tracks=[{"kind": "humint", "label": "적 저격조 활동", "confidence": 0.8}])
    adjusted, _ = cross_check(sigs, {}, "정찰", c4i)
    assert adjusted[0]["confidence"] > 0.85 and adjusted[0]["adjust_reason"]


def test_2_firepower_severity_corroborated() -> None:
    sigs = [_sig("severity", "박격포", effect="severity_escalate", domain="firepower")]
    c4i = _c4i(enemy_tracks=[{"kind": "radar_track", "label": "박격포 진지 탐지", "confidence": 0.9}])
    adjusted, _ = cross_check(sigs, {}, "정찰", c4i)
    assert adjusted[0]["confidence"] > 0.85 and adjusted[0]["adjust_reason"]


def test_3_resupply_signal_corroborated_by_profile() -> None:
    # 재보급/예비 신호 + 프로필 spare 없음 → 신호 확증 (확신도↑ + 이유).
    sigs = [_sig("logistics", "예비기체 없음", effect="severity_escalate")]
    adjusted, _ = cross_check(sigs, {"spare_asset_available": False}, "정찰", _c4i())
    assert adjusted[0]["confidence"] > 0.85 and adjusted[0]["adjust_reason"]


def test_3_resupply_signal_contradicted_stays() -> None:
    # 프로필 spare 있음 → 확증 없음(확신도 불변) — 조정은 확증만, 하향 없음.
    sigs = [_sig("logistics", "예비기체 없음", effect="severity_escalate")]
    adjusted, _ = cross_check(sigs, {"spare_asset_available": True}, "정찰", _c4i())
    assert adjusted[0]["confidence"] == 0.85 and "adjust_reason" not in adjusted[0]


def test_4_civil_signal_corroborated_by_density_draft() -> None:
    sigs = [_sig("civil", "민가", effect="roe_caution")]
    c4i = _c4i(civil_density_draft=[{"id": "c-1", "center": [0, 0], "radius": 10, "density": "high"}])
    adjusted, _ = cross_check(sigs, {}, "정찰", c4i)
    assert adjusted[0]["confidence"] > 0.85 and adjusted[0]["adjust_reason"]


def test_5_purpose_mismatch_warning_only() -> None:
    # NLP 목적(타격) vs 운용자 선택(정찰) → 경고, 확신도 무변.
    sigs = [_sig("mission_purpose", "타격", purpose="타격")]
    adjusted, warnings = cross_check(sigs, {}, "정찰", _c4i())
    assert [w for w in warnings if w["field"] == "mission_purpose"]
    assert adjusted[0]["confidence"] == 0.85


def test_5_purpose_match_no_warning() -> None:
    sigs = [_sig("mission_purpose", "정찰", purpose="정찰")]
    _, warnings = cross_check(sigs, {}, "정찰", _c4i())
    assert [w for w in warnings if w["field"] == "mission_purpose"] == []


def test_6_spare_mismatch_warning_kept() -> None:
    # 기존 ⑥ 회귀 — normalize 골격 입력에서도 동작.
    _, warnings = cross_check([], {"spare_asset_available": True}, "정찰",
                              _c4i(asset_management={"spare_asset_available": False}))
    assert [w for w in warnings if w["field"] == "spare_available"]


def test_legacy_string_c4i_still_corroborates() -> None:
    # 레거시 enemy_situation → report 트랙 승격 경유 확증 (하위호환).
    sigs = [_sig("threat", "저격조", threat="T3")]
    adjusted, _ = cross_check(sigs, {}, "정찰", _c4i(enemy_situation=["적 저격조 확인"]))
    assert adjusted[0]["confidence"] > 0.85


def test_no_c4i_skips_all_track_checks() -> None:
    sigs = [_sig("threat", "저격조", threat="T3"), _sig("civil", "민간", effect="roe_caution")]
    adjusted, warnings = cross_check(sigs, {}, "정찰", _c4i())
    assert all(s["confidence"] == 0.85 for s in adjusted)
