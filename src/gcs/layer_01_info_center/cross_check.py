"""cross_check — 🔵 결정론 대조. NLP 신호/운용자 입력 vs C4I 사실.

스펙 2종 처리:
  (1) 확신도 조정 — 위협신호가 C4I 적상황에 독립 확증되면 확신도 상향 + 이유 라벨.
  (2) 불일치 경고 — spare_available/임무목적은 사실 확인이라 확신도 대신 경고만.
C4I 데이터가 없으면(비동기 소스 미도착) 대조를 건너뛴다(무경고, 조립은 진행).
"""

from __future__ import annotations

CORROBORATION_BONUS = 0.05


def _corroborating_evidence(phrase: str, enemy_situation: list[str]) -> str | None:
    """source_phrase 가 C4I 적상황 항목에 나타나면 그 항목 문자열을 반환."""
    for item in enemy_situation:
        if phrase and phrase in item:
            return item
    return None


def cross_check(
    signals: list[dict],
    drone_profile: dict,
    mission_context: str,
    c4i: dict,
) -> tuple[list[dict], list[dict]]:
    """(adjusted_signals, warnings) 반환. 입력 signals 는 변경하지 않는다(복사본)."""
    enemy_situation = c4i.get("enemy_situation", []) or []

    adjusted: list[dict] = []
    for sig in signals:
        s = dict(sig)  # 원본 불변
        if s.get("signal_type") == "threat":
            evidence = _corroborating_evidence(s.get("source_phrase", ""), enemy_situation)
            if evidence is not None:
                s["confidence"] = min(1.0, s["confidence"] + CORROBORATION_BONUS)
                s["adjust_reason"] = f"C4I 적상황 확증: '{evidence}'"
        adjusted.append(s)

    warnings: list[dict] = []

    # (2a) 예비기체 보유여부 대조 (등록값 검증). 온보드 계약 키 spare_asset_available.
    reg_spare = drone_profile.get("spare_asset_available")
    c4i_spare = c4i.get("asset_management", {}).get("spare_asset_available")
    if reg_spare is not None and c4i_spare is not None and reg_spare != c4i_spare:
        warnings.append({
            "field": "spare_available",
            "registered": reg_spare,
            "c4i": c4i_spare,
            "message": "등록한 예비기체 보유여부가 C4I 자산관리체계 기록과 다릅니다",
        })

    # (2b) 임무목적 대조 (mission_context 가 C4I 인지 임무에 포함되는지).
    known_mission = c4i.get("known_mission")
    if known_mission is not None and mission_context not in known_mission:
        warnings.append({
            "field": "mission_context",
            "registered": mission_context,
            "c4i": known_mission,
            "message": "선택한 임무유형이 C4I 임무 정보와 불일치합니다",
        })

    return adjusted, warnings
