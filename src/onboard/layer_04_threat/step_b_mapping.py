"""Step B — 신호 → 위협 매핑.

`SIGNAL_TO_THREAT` 의 condition 문자열을 (channel, predicate, threat) 하드코딩
룰 테이블로 표현한다. `eval`/`exec` 금지 (보안, CLAUDE.md CRITICAL / ADR-003).

반환:
  matched: [
    {"threat_event": "T3",
     "matched_channels": [{"name", "base_weight", "quality", "state"}, ...]},
    ...
  ]
  background_exposure_score: terrain_class.payload.exposure_score (없으면 0.0)
"""

from __future__ import annotations

from typing import Callable

from onboard.shared.constants import (
    CHANNEL_WEIGHTS,
    DEFAULT_CHANNEL_WEIGHT,
    QUALITY_DELTA_DROP_THRESHOLD,
    TIME_TO_COLLISION_THRESHOLD_S,
)
from onboard.shared.schemas import AbstractionOutput, ChannelOutput

# ---------------------------------------------------------------------------
# 단일채널 룰 — (channel, predicate(channel_dict) -> bool, threat)
# predicate 는 해당 채널의 ChannelOutput dict 전체를 받는다.
# ---------------------------------------------------------------------------


def _t3_proximity(ch: ChannelOutput) -> bool:
    return ch["state"] == "anomaly" and ch["payload"].get("weapon_shape") is True


def _t3_acoustic(ch: ChannelOutput) -> bool:
    return ch["payload"].get("event_type") == "gunshot"


def _t1_position(ch: ChannelOutput) -> bool:
    return ch["payload"].get("gps_imu_residual_m", 0) > 5.0


def _t1_rf(ch: ChannelOutput) -> bool:
    return ch["payload"].get("wideband_anomaly") is True


def _t2_link_integrity(ch: ChannelOutput) -> bool:
    return (
        ch["payload"].get("checksum_fail_rate", 0) > 0.05
        or ch["payload"].get("seq_gap_count", 0) > 0
    )


def _t2_encryption(ch: ChannelOutput) -> bool:
    return ch["payload"].get("downgrade_detected") is True


def _t7_obstacle(ch: ChannelOutput) -> bool:
    # 고정거리 대신 충돌예상시간(거리÷접근속도) 기준 — 기체 속도와 무관하게 일관.
    distance_m = ch["payload"].get("distance_m")
    closure_rate_mps = ch["payload"].get("closure_rate_mps", 0)
    # 음수 거리는 물리적으로 무의미(음수 TTC → 오탐). distance<0 도 배제.
    if distance_m is None or distance_m < 0 or closure_rate_mps <= 0:
        return False
    return distance_m / closure_rate_mps < TIME_TO_COLLISION_THRESHOLD_S


def _t5_quality_delta(ch: ChannelOutput) -> bool:
    # quality_delta 는 채널 최상위 필드 (payload 아님).
    return ch.get("quality_delta", 0) < QUALITY_DELTA_DROP_THRESHOLD


_SINGLE_CHANNEL_RULES: list[tuple[str, Callable[[ChannelOutput], bool], str]] = [
    ("proximity_object", _t3_proximity, "T3"),
    ("acoustic_event", _t3_acoustic, "T3"),
    ("position_consistency", _t1_position, "T1"),
    ("rf_spectrum", _t1_rf, "T1"),
    ("link_integrity", _t2_link_integrity, "T2"),
    ("encryption_status", _t2_encryption, "T2"),
    ("obstacle_proximity", _t7_obstacle, "T7"),
    ("proximity_object", _t5_quality_delta, "T5"),
    ("terrain_class", _t5_quality_delta, "T5"),
]


# ---------------------------------------------------------------------------
# T4 — 다중채널 동시조건 (세 조건 모두 참일 때만 매칭)
# ---------------------------------------------------------------------------


def _t4_proximity(ch: ChannelOutput) -> bool:
    return ch["payload"].get("class") in ("person", "vehicle") and ch["payload"].get(
        "closing"
    ) is True


def _t4_phase_mismatch(ch: ChannelOutput) -> bool:
    return ch["payload"].get("match") is False


def _t4_link_abnormal(ch: ChannelOutput) -> bool:
    return ch["state"] != "normal"


_T4_CONDITIONS: list[tuple[str, Callable[[ChannelOutput], bool]]] = [
    ("proximity_object", _t4_proximity),
    ("mission_phase", _t4_phase_mismatch),
    ("link_status", _t4_link_abnormal),
]


def _base_weight(channel: str) -> float:
    return CHANNEL_WEIGHTS.get(channel, DEFAULT_CHANNEL_WEIGHT)


def _matched_channel(ch: ChannelOutput) -> dict:
    return {
        "name": ch["channel"],
        "base_weight": _base_weight(ch["channel"]),
        "quality": ch["quality"],
        "state": ch["state"],
    }


def _check_t4_multi_channel(by_channel: dict[str, ChannelOutput]) -> list[str] | None:
    """세 조건 모두 참이면 매칭 채널 이름 리스트, 아니면 None."""
    if not all(name in by_channel for name, _ in _T4_CONDITIONS):
        return None
    if all(pred(by_channel[name]) for name, pred in _T4_CONDITIONS):
        return [name for name, _ in _T4_CONDITIONS]
    return None


def run(abstraction: AbstractionOutput) -> tuple[list[dict], float]:
    by_channel: dict[str, ChannelOutput] = {
        ch["channel"]: ch for ch in abstraction["channels"]
    }

    # threat -> {channel_name: matched_channel dict} (채널 중복 제거)
    grouped: dict[str, dict[str, dict]] = {}

    def _add(threat: str, channel_name: str) -> None:
        grouped.setdefault(threat, {})[channel_name] = _matched_channel(
            by_channel[channel_name]
        )

    for channel_name, predicate, threat in _SINGLE_CHANNEL_RULES:
        ch = by_channel.get(channel_name)
        if ch is None:
            continue
        if predicate(ch):
            _add(threat, channel_name)

    t4_channels = _check_t4_multi_channel(by_channel)
    if t4_channels is not None:
        for channel_name in t4_channels:
            _add("T4", channel_name)

    matched = [
        {"threat_event": threat, "matched_channels": list(channels.values())}
        for threat, channels in grouped.items()
    ]

    terrain = by_channel.get("terrain_class")
    exposure = (
        terrain["payload"].get("exposure_score", 0.0) if terrain is not None else 0.0
    )

    return matched, exposure
