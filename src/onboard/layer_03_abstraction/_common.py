"""03 채널 공용 헬퍼 (채널 아님 — 순수 유틸).

채널 모듈끼리 서로 import 하는 것은 금지(step3)지만, 이 유틸은 채널이 아니라
ChannelOutput 조립/quality_delta 계산만 담당한다.
"""

from onboard.shared.schemas import ChannelOutput

_QUALITY_NDIGITS = 4


def clamp01(x: float) -> float:
    """0.0~1.0 범위로 클램프."""
    return max(0.0, min(1.0, x))


def make_output(
    channel: str,
    state: str,
    quality: float,
    payload: dict,
    previous_quality: float | None,
) -> ChannelOutput:
    """ChannelOutput 조립. quality_delta = quality - previous_quality (없으면 0.0)."""
    q = round(clamp01(quality), _QUALITY_NDIGITS)
    delta = 0.0 if previous_quality is None else round(q - previous_quality, _QUALITY_NDIGITS)
    return {
        "channel": channel,
        "state": state,
        "quality": q,
        "quality_delta": delta,
        "payload": payload,
    }
