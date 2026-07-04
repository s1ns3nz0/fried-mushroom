"""nlp_extract 라운드2 확장 룰 검증 (TDD) — 대조표 6종에 필요한 신호 4종.

heavy_weapons(화력 심각도) / resupply(재보급) / civil_area(민간) / mission_purpose(임무목적).
기존 threat/logistics 룰 회귀는 test_nlp_extract.py 가 잠근다.
"""

from gcs.layer_01_info_center.nlp_extract import extract_signals


def _types(sigs):
    return {s["signal_type"] for s in sigs}


def test_heavy_weapons_severity_signal() -> None:
    sigs = extract_signals("적 박격포 진지 확인됨")
    sev = [s for s in sigs if s["signal_type"] == "severity"]
    assert len(sev) == 1
    assert sev[0]["domain"] == "firepower"
    assert sev[0]["confidence"] >= 0.9


def test_daegugyeong_fires_both_threat_and_severity() -> None:
    # 대구경화기 = T3 위협(기존) + 화력 심각도(신규) 동시 — 다른 signal_type.
    sigs = extract_signals("대구경화기 식별")
    assert "threat" in _types(sigs) and "severity" in _types(sigs)


def test_resupply_signal() -> None:
    sigs = extract_signals("손실 시 재보급까지 72시간 소요 확인")
    logi = [s for s in sigs if s["signal_type"] == "logistics" and s.get("domain") == "resupply"]
    assert len(logi) == 1
    assert logi[0]["effect"] == "severity_escalate"


def test_civil_area_signal() -> None:
    sigs = extract_signals("작전지역 인근 민가 밀집 확인")
    civ = [s for s in sigs if s["signal_type"] == "civil"]
    assert len(civ) == 1
    assert civ[0]["effect"] == "roe_caution"


def test_mission_purpose_extracted() -> None:
    sigs = extract_signals("본 임무는 정찰 감시 임무이다. 목표지역 확인.")
    mp = [s for s in sigs if s["signal_type"] == "mission_purpose"]
    assert len(mp) == 1
    assert mp[0]["purpose"] == "정찰"


def test_hedged_new_rules_filtered() -> None:
    sigs = extract_signals("박격포 배치 가능성. 민간 지역 추정.")
    assert "severity" not in _types(sigs)
    assert "civil" not in _types(sigs)


def test_no_purpose_no_signal() -> None:
    assert [s for s in extract_signals("특이사항 없음") if s["signal_type"] == "mission_purpose"] == []
