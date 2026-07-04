"""nlp_extract — 결정론 키워드룰 지시서 해석 검증 (TDD).

지시서 원문에서 위협/병참 신호를 뽑고 확실성 수식어로 확신도를 정한다.
확신도 < CONFIDENCE_FLOOR(0.7) 신호는 제외(스펙: 애매한 건 사람에게 안 보임).
"""

from gcs.layer_01_info_center import nlp_extract
from gcs.layer_01_info_center.nlp_extract import CONFIDENCE_FLOOR, extract_signals


def _by_type(signals, signal_type):
    return [s for s in signals if s["signal_type"] == signal_type]


def test_sniper_confirmed_is_high_confidence_threat() -> None:
    sigs = extract_signals("적 저격조 첩보 확인됨")
    threats = _by_type(sigs, "threat")
    assert len(threats) == 1
    assert threats[0]["threat"] == "T3"
    assert threats[0]["confidence"] >= 0.9
    assert "저격조" in threats[0]["source_phrase"]


def test_spare_absent_is_logistics_escalation() -> None:
    sigs = extract_signals("가용 예비기체 없음. 손실 시 재보급 72시간")
    logi = _by_type(sigs, "logistics")
    assert len(logi) == 1
    assert logi[0]["effect"] == "severity_escalate"
    assert logi[0]["confidence"] >= CONFIDENCE_FLOOR


def test_hedged_signal_below_floor_is_filtered() -> None:
    # "가능성 있음" → 낮은 확신도 → 제외.
    sigs = extract_signals("적 저격조 출현 가능성 있음")
    assert _by_type(sigs, "threat") == []


def test_no_keyword_yields_no_signals() -> None:
    assert extract_signals("일반 정찰 임무. 특이사항 없음.") == []


def test_all_confidences_within_unit_interval_and_above_floor() -> None:
    sigs = extract_signals("적 저격조 확인됨. 사이버 위협 확인. 예비기체 없음.")
    assert sigs  # 최소 하나
    for s in sigs:
        assert CONFIDENCE_FLOOR <= s["confidence"] <= 1.0


def test_floor_constant_is_070() -> None:
    assert nlp_extract.CONFIDENCE_FLOOR == 0.7
