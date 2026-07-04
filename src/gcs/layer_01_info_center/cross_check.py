"""cross_check — 🔵 결정론 대조. NLP 신호/운용자 입력 vs C4I 사실 (대조표 6종, B-1 §5.4).

확신도 조정 (확증 시 상향 + 이유, 하향 없음):
  ① threat 신호 ↔ C4I enemy_tracks (label 매칭)
  ② severity(화력) 신호 ↔ C4I enemy_tracks
  ③ logistics(재보급/예비) 신호 ↔ drone_profile.spare_asset_available (없음 확증)
  ④ civil 신호 ↔ C4I civil_density_draft (medium/high 확증)
경고만 (사실 확인 — 확신도 무변):
  ⑤ mission_purpose 신호 ↔ 운용자 mission_context / C4I known_mission
  ⑥ drone_profile.spare ↔ C4I asset_management

입력 c4i 는 c4i_schema.normalize_c4i 산출 골격. 해당 C4I 항목이 비면 그 대조는 스킵.
"""

from __future__ import annotations

from gcs.layer_01_info_center.c4i_schema import normalize_c4i

CORROBORATION_BONUS = 0.05

_CORROBORATING_DENSITIES = ("medium", "high")


def _track_evidence(phrase: str, tracks: list[dict]) -> str | None:
    """source_phrase 가 트랙 label 에 나타나면 그 label 반환."""
    for t in tracks:
        label = t.get("label") or ""
        if phrase and phrase in label:
            return label
    return None


def _boost(sig: dict, reason: str) -> None:
    sig["confidence"] = min(1.0, sig["confidence"] + CORROBORATION_BONUS)
    sig["adjust_reason"] = reason


def cross_check(
    signals: list[dict],
    drone_profile: dict,
    mission_context: str,
    c4i: dict,
) -> tuple[list[dict], list[dict]]:
    """(adjusted_signals, warnings) 반환. 입력 signals 는 변경하지 않는다(복사본).

    c4i 는 정규화 골격/레거시 dict 모두 수용 (내부에서 normalize — 멱등, 하위호환)."""
    c4i = normalize_c4i(c4i)
    tracks = c4i.get("enemy_tracks") or []
    civil_draft = c4i.get("civil_density_draft") or []
    reg_spare = drone_profile.get("spare_asset_available")

    adjusted: list[dict] = []
    warnings: list[dict] = []

    for sig in signals:
        s = dict(sig)  # 원본 불변
        st = s.get("signal_type")
        phrase = s.get("source_phrase", "")

        if st in ("threat", "severity"):  # ①②
            evidence = _track_evidence(phrase, tracks)
            if evidence is not None:
                _boost(s, f"C4I 적상황 확증: '{evidence}'")
        elif st == "logistics":  # ③ — 예비 없음/재보급 신호를 프로필이 확증
            if reg_spare is False:
                _boost(s, "기체 프로필 확증: 예비기체 미보유 등록")
        elif st == "civil":  # ④
            dens = next((a for a in civil_draft if a.get("density") in _CORROBORATING_DENSITIES), None)
            if dens is not None:
                _boost(s, f"C4I 민간 밀집도 확증: {dens.get('id')}({dens.get('density')})")
        elif st == "mission_purpose":  # ⑤ — 경고만
            purpose = s.get("purpose")
            known = c4i.get("known_mission")
            if purpose and purpose != mission_context:
                warnings.append({
                    "field": "mission_purpose",
                    "registered": mission_context,
                    "directive": purpose,
                    "message": "지시서의 임무목적이 운용자가 선택한 임무유형과 다릅니다",
                })
            elif purpose and known is not None and purpose not in known:
                warnings.append({
                    "field": "mission_purpose",
                    "registered": purpose,
                    "c4i": known,
                    "message": "지시서의 임무목적이 C4I 임무 정보와 불일치합니다",
                })
        adjusted.append(s)

    # ⑥ 예비기체 보유여부 대조 (등록값 검증) — 온보드 계약 키 spare_asset_available.
    c4i_spare = c4i.get("asset_management", {}).get("spare_asset_available")
    if reg_spare is not None and c4i_spare is not None and reg_spare != c4i_spare:
        warnings.append({
            "field": "spare_available",
            "registered": reg_spare,
            "c4i": c4i_spare,
            "message": "등록한 예비기체 보유여부가 C4I 자산관리체계 기록과 다릅니다",
        })

    # (구) 운용자 mission_context ↔ known_mission 직접 대조 유지 (⑤ 보완).
    known_mission = c4i.get("known_mission")
    if known_mission is not None and mission_context and mission_context not in known_mission:
        warnings.append({
            "field": "mission_context",
            "registered": mission_context,
            "c4i": known_mission,
            "message": "선택한 임무유형이 C4I 임무 정보와 불일치합니다",
        })

    return adjusted, warnings
