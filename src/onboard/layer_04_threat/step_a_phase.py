"""Step A — 임무 국면 확인.

mission_phase 채널의 payload.declared, mission_phase_confidence 를 그대로 반환.
재계산하지 않는다 — 국면 판정은 03 소관 (04.md Step A 원칙).
"""

from __future__ import annotations

from onboard.shared.schemas import AbstractionOutput


def run(abstraction: AbstractionOutput) -> tuple[str, float]:
    mp = next(
        ch for ch in abstraction["channels"] if ch["channel"] == "mission_phase"
    )
    payload = mp["payload"]
    return payload["declared"], payload["mission_phase_confidence"]
