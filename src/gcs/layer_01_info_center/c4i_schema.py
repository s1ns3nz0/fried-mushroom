"""c4i_schema — 🔵 결정론. 구조화 C4I 입력 정규화 (B-1 §5.2).

정본: enemy_tracks[] (구조화 트랙). 레거시 enemy_situation[] (문자열)은
{kind:"report", label, confidence:0.5} 트랙으로 승격 수용한다.
부분/부재 입력은 빈 골격으로 정규화 — 대조 단계가 스킵 판단.
"""

from __future__ import annotations

# 레거시 문자열 보고의 승격 confidence (단일 출처 미확인 보고 수준).
LEGACY_REPORT_CONFIDENCE = 0.5


def normalize_c4i(raw: dict | None) -> dict:
    """C4I 원시 dict → 정규화 골격. 입력은 변경하지 않는다."""
    raw = raw or {}

    tracks = [dict(t) for t in raw.get("enemy_tracks") or []]
    for s in raw.get("enemy_situation") or []:
        tracks.append({"kind": "report", "label": s, "confidence": LEGACY_REPORT_CONFIDENCE})

    return {
        "enemy_tracks": tracks,
        "asset_management": dict(raw.get("asset_management") or {}),
        "civil_density_draft": [dict(a) for a in raw.get("civil_density_draft") or []],
        "posture_feed": dict(raw.get("posture_feed") or {}) or None,
        "known_mission": raw.get("known_mission"),
    }
