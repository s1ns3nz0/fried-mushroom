"""rf_spectrum — 🔵 결정론. 광대역 RF 스캔 이상탐지.

구체 임계값이 D4D 문서에 없어 함수 내부 상수로 둔다 (MVP placeholder). raw
ew.rf_wideband_scan 이 스펙트럼 샘플 배열(samples)을 주면 max/median 비율로 판정하고,
불리언만 오면 그 값을 그대로 사용한다.
"""

from statistics import median

from onboard.layer_03_abstraction._common import make_output
from onboard.layer_02_sensor.schema import RawSensorEnvelope
from onboard.shared.schemas import ChannelOutput

_MAX_MEDIAN_RATIO_THRESHOLD = 8.0  # MVP placeholder


def _detect_anomaly(scan: dict) -> bool:
    samples = scan.get("samples")
    if samples:
        med = median(samples)
        if med > 0:
            return max(samples) / med > _MAX_MEDIAN_RATIO_THRESHOLD
    return bool(scan.get("wideband_anomaly", False))


def run(raw: RawSensorEnvelope, previous_quality: float | None = None) -> ChannelOutput:
    ew = raw["ew"]
    scan = ew["rf_wideband_scan"]
    wideband_anomaly = _detect_anomaly(scan)

    state = "anomaly" if wideband_anomaly else "normal"
    quality = 0.80  # 광대역 수신기 신뢰도 대리값 (MVP proxy)

    payload = {"wideband_anomaly": wideband_anomaly, "bearing_deg": ew["rf_bearing_deg"]}
    return make_output("rf_spectrum", state, quality, payload, previous_quality)
