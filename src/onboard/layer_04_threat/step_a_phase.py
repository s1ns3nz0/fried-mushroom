"""Step A — 임무 국면 확인.

mission_phase 채널의 payload.declared, mission_phase_confidence 를 그대로 반환.
재계산하지 않는다 — 국면 판정은 03 소관 (04.md Step A 원칙).

mission_phase 채널이 없거나(예: layer 03 미구현 stub abstraction) payload 키가
비면 ("unknown", 0.0) 으로 격하한다 — orchestrator _STUB_OUTPUT["04"] 어휘와 정렬.
"""

from __future__ import annotations

from onboard.shared.schemas import AbstractionOutput

_UNKNOWN_PHASE: tuple[str, float] = ("unknown", 0.0)


def run(abstraction: AbstractionOutput) -> tuple[str, float]:
    mp = next(
        (ch for ch in abstraction["channels"] if ch["channel"] == "mission_phase"),
        None,
    )
    if mp is None:
        return _UNKNOWN_PHASE
    payload = mp["payload"]
    if "declared" not in payload or "mission_phase_confidence" not in payload:
        return _UNKNOWN_PHASE
    return payload["declared"], payload["mission_phase_confidence"]
