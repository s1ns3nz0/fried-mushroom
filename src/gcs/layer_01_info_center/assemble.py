"""assemble — 🔵 결정론. set_mission 입력에서 온보드 MissionBrief 6필드 구성.

drone_profile 은 상수라 최상위로 그대로 통과(임무정보와 분리). directive_text/c4i
등 대조·해석용 입력은 브리핑에 넣지 않는다. 필수 필드 누락은 조용히 넘기지 않고
명시적 에러(임무 저작 시맨틱).
"""

from __future__ import annotations

# 온보드 MissionBrief 계약 (src/onboard/shared/schemas.py). 임의 변경 금지.
MISSION_BRIEF_FIELDS = (
    "sortie_id",
    "mission_context",
    "posture",
    "drone_profile",
    "corridor",
    "weights",
)


def assemble_brief(inputs: dict) -> dict:
    """set_mission 입력 → MissionBrief draft (6 필드만)."""
    missing = [f for f in MISSION_BRIEF_FIELDS if f not in inputs]
    if missing:
        raise ValueError(f"mission_brief 필수 필드 누락: {missing}")
    return {f: inputs[f] for f in MISSION_BRIEF_FIELDS}
