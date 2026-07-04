"""link_integrity — 🔵 결정론. 체크섬 실패율·시퀀스 누락 판독."""

from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

_CHECKSUM_FAIL_ANOMALY = 0.05


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    c2 = raw["c2_link"]
    checksum_fail_rate = c2["checksum_fail_rate"]
    seq_gap_count = c2["seq_gap_count"]

    state = (
        "anomaly"
        if checksum_fail_rate > _CHECKSUM_FAIL_ANOMALY or seq_gap_count > 0
        else "normal"
    )

    # quality = 판독기 건전성(A-1/#28): 무결성 계측은 결정론적이라 값이 나빠도
    # 측정 신뢰도는 높다. 위협 크기(체크섬 실패율·seq_gap)는 payload 로 전달한다.
    # (계측기 자체 손상 — 샘플 부족 등 — 시에만 degraded/quality↓, MVP 는 훅만 문서화.)
    quality = 0.95

    payload = {"checksum_fail_rate": checksum_fail_rate, "seq_gap_count": seq_gap_count}
    return make_output("link_integrity", state, quality, payload, previous_quality)
