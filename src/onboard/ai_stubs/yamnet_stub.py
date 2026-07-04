"""YAMNet 음향분류 2차확인 stub (ADR-002: stub 우선).

실제 모델은 로딩하지 않는다. 1차 임계값매칭이 애매한 경우에만(게이팅) 호출되며, raw
acoustic 의 mock 라벨 힌트(`mock_label`)를 읽어 고정 결과를 리턴한다.
"""

_DEFAULT = {"event_type": "unknown", "yamnet_confidence": 0.5}


def classify_acoustic(raw_acoustic: dict) -> dict:
    """acoustic.mock_label 힌트 → 2차 음향 분류. 힌트 없으면 unknown."""
    hint = raw_acoustic.get("mock_label")
    if hint:
        return {"event_type": hint, "yamnet_confidence": 0.8}
    return dict(_DEFAULT)
